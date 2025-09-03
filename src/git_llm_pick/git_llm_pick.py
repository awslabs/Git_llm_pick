#!/usr/bin/env python3

"""
An extension to git cherry-pick that allows fuzzy picking.

This script provides enhanced cherry-pick functionality by adding support for fuzzy patching.
When a normal git cherry-pick fails, it will attempt to apply the patch with fuzzy matching,
allowing for successful cherry-picks even when the context lines don't match exactly.

The script first tries a normal git cherry-pick, and if that fails, it attempts to apply
the patch with a configurable fuzz factor. The fuzz factor determines how many lines of
context are ignored when matching the patch location.

The tool supports the basic operations of git-cherry-pick, and warns in
case parameters are used that the tool does not know.

To improve confidence in the change, the tool can run a validation
command after the modification. The change is rolled back in case the
validation fails. This way, the higher fuzziness in patching can be
mitigated.

Usage:
    git-llm-pick.py [git-llm-pick-options] [git-cherry-pick-options] <commit>
"""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import argparse
import logging
import os
import re
import shlex
import sys
from dataclasses import dataclass
from typing import List, Tuple

from git_llm_pick import SUPPORTED_GIT_ARGS
from git_llm_pick.git_commands import (
    backport_commit_context,
    commit_is_present_in_branch,
    git_added_files,
    git_amend_and_sign_head_commit,
    git_changed_files,
    git_check_files_diff_free,
    git_cherry_pick,
    git_get_commits_contextdiff,
    git_reset_files,
)
from git_llm_pick.llm_patching import LlmLimits, LlmPatcher
from git_llm_pick.patch_matching import commits_have_equal_hunks
from git_llm_pick.utils import (
    get_invalid_patch_paths,
    get_invalid_repository_paths,
    run_command,
    warn_on_unsupported_args,
)

log = logging.getLogger(__name__)


def hunk_context_lines(hunk, extra_context_lines, max_file_lines) -> Tuple[int, int]:
    """Return the context line range for a file and a given hunk."""

    log.debug(
        "Create context for hunk %s (%d file lines), and context lines %d. Source %d len %d. Target %d len %d ...",
        hunk.section_header,
        max_file_lines,
        extra_context_lines,
        hunk.source_start,
        hunk.source_length,
        hunk.target_start,
        hunk.target_length,
    )

    max_hunk_size = max(hunk.source_length, hunk.target_length)
    first_start = min(hunk.source_start, hunk.target_start)
    last_end = max(hunk.source_start + max_hunk_size, hunk.target_start + max_hunk_size)
    start_line = max(1, first_start - extra_context_lines)
    end_line = min(max_file_lines, last_end + extra_context_lines)
    log.debug("File context lines to present: %d - %d", start_line, end_line)
    return start_line, end_line


def apply_patch_fuzzy(
    patch_content: str,
    fuzz_factor: int,
    keep_rej_files: bool = False,
) -> Tuple[bool, str, str]:
    """Apply the patch with fuzzy matching, keep state on error, return success, stderr, command."""
    if not patch_content:
        return False, "No patch content given", None

    args = [] if keep_rej_files else ["--reject-file=-", "--quiet"]
    log.debug("Attempting fuzzy-pick with fuzz=%s and patch of size %d ...", fuzz_factor, len(patch_content))
    patch_cmd = ["patch", "-p1", "--no-backup-if-mismatch", f"--fuzz={fuzz_factor}"] + args
    success, _, stderr = run_command(patch_cmd, input_data=patch_content)
    log.debug("Result of applying patch with fuzz=%s: %r", fuzz_factor, success)
    return success, stderr, " ".join(patch_cmd)


@dataclass
class PathRewriteRule:
    """Store pattern for path rewriting, and apply it to path"""

    src_pattern: str
    dst_pattern: str

    def rewrite_path(self, paths: list[str]) -> list[str]:
        """Rewrite paths that have been given, and return the new list."""
        if not paths:
            return paths
        return [x.replace(self.src_pattern, self.dst_pattern) for x in paths]


class FuzzyPatcher:
    """Apply a commit in a less strict manner."""

    def __init__(
        self,
        commit_id: str,
        min_fuzz_factor: int = 2,
        max_fuzz_factor: int = 2,
        keep_commit_author: bool = True,
        llm_patcher=None,
        path_rewrite_rules: list[PathRewriteRule] = [],
    ):
        self.commit_id = commit_id
        self.min_fuzz_factor = min_fuzz_factor
        self.max_fuzz_factor = max_fuzz_factor
        self.changed_files = git_changed_files(self.commit_id)
        self.added_files = git_added_files(self.commit_id)
        self.patch_file_content = None
        self.keep_commit_author = keep_commit_author
        self.llm_patcher = llm_patcher
        self.path_rewrite_rules = path_rewrite_rules if path_rewrite_rules is not None else []

        # Rewrite changed files, before they are used in the fuzzy patcher
        for rewrite_rule in self.path_rewrite_rules:
            self.changed_files = rewrite_rule.rewrite_path(self.changed_files)
            self.added_files = rewrite_rule.rewrite_path(self.added_files)

        # Validate that all changed and added files are within the repository root
        all_files = (self.changed_files or []) + (self.added_files or [])
        if all_files:
            try:
                invalid_paths = get_invalid_repository_paths(all_files)
                if invalid_paths:
                    raise RuntimeError(f"Commit contains files outside repository root: {invalid_paths}")
            except RuntimeError as e:
                log.error("Failed to validate file paths for commit %s: %s", commit_id, e)
                raise

    def create_patch(self, context_lines=None) -> bool:
        """Create a patch file from the commit."""

        if self.patch_file_content is not None:
            return True

        lines = ["-U" + str(context_lines)] if context_lines else []
        success, stdout, _ = run_command(["git", "show"] + lines + [self.commit_id])
        if success:
            for rewrite_rule in self.path_rewrite_rules:
                # Replace path_src with path_dst in lines starting with "--- ", "+++ " or git diff that contain path_src
                stdout = re.sub(
                    r"^(---|\+\+\+|diff --git ) .*" + re.escape(rewrite_rule.src_pattern) + r".*",
                    lambda m, src=rewrite_rule.src_pattern, dst=rewrite_rule.dst_pattern: m.group().replace(src, dst),
                    stdout,
                    flags=re.MULTILINE,
                )

            # Validate that all paths in the patch are within the repository root
            try:
                invalid_paths = get_invalid_patch_paths(stdout)
                if invalid_paths:
                    log.error("Patch contains invalid paths outside repository root: %s", invalid_paths)
                    return False
            except RuntimeError as e:
                log.error("Failed to validate patch paths: %s", e)
                return False

            log.debug("Created patch to apply:\n%s", stdout)
            self.patch_file_content = stdout
        return success

    def create_commit(self, extra_message, explain_message="") -> Tuple[bool, str]:
        """Create a commit from the applied changes."""

        if not self.changed_files:
            return False, "No changed files found to create a commit from"

        # Get original commit message
        success, commit_msg, stderr = run_command(["git", "log", "-1", "--format=%B", self.commit_id])
        if not success:
            return False, f"Failed to get commit message with {stderr}"

        # Get the author of the given commit
        author_parameters = []
        if self.keep_commit_author:
            success, author, stderr = run_command(["git", "log", "-1", "--format=%an <%ae>", self.commit_id])
            if not success:
                return False, f"Failed to get commit author with {stderr}"
            author_parameters = [f"--author={author}"]

        # Append extra message if provided
        if extra_message:
            log.debug("Create commit with extra message:\n%s", extra_message)
            commit_msg += f"\n{extra_message}"

        # In case we introduced new files, add them to the commit to be created
        if self.added_files:
            success, _, stderr = run_command(["git", "add"] + self.added_files)
            if not success:
                return False, f"Failed to add introduced files to repository with {stderr}"

        # Create new commit
        success, _, stderr = run_command(
            ["git", "commit", "-s", "-m", commit_msg]
            + author_parameters
            + self.changed_files
            + (self.added_files if self.added_files else [])
        )

        try:
            commits_diff = git_get_commits_contextdiff("HEAD", self.commit_id)
            log.debug("Commit diff: %s", commits_diff)

            explanation = f"\nExplanation for pick:\n{explain_message}\n"

            git_notes = f"""
Applied commit with git-llm-pick.
{explanation}

Diff between this commit and upstream commit {self.commit_id}:

{commits_diff}
"""

            # Try to add backport notes to commit, but only if none are present yet
            log.debug("Adding git notes: %s", git_notes)
            notes_success, _, notes_stderr = run_command(["git", "notes", "add", "-m", git_notes])
            if not notes_success:
                log.warning("Failed to add notes, with: %s", notes_stderr)
        except Exception:
            log.warning("Failed to extend commit with diff notes")
            log.debug("Failure trace for adding notes", exc_info=True)

        return success, stderr

    def try_fuzzy_patch(self, commit_change=True, keep_reject_files=True) -> Tuple[bool, str]:
        """Main method to attempt fuzzy patching."""
        if not git_check_files_diff_free(self.changed_files):
            return (False, f"error: Changed files have a diff, clean them before! {' '.join(self.changed_files)}")

        if not self.create_patch():
            return False, "error: Failed to create patch content"

        for changed_file in self.changed_files:
            if changed_file in self.added_files:
                if os.path.exists(changed_file):
                    return False, f"error: Added file {changed_file} already exists"
                continue
            if not os.path.exists(changed_file):
                return False, f"error: Changed file {changed_file} does not exist"

        success = False
        for fuzz_factor in range(self.min_fuzz_factor, self.max_fuzz_factor + 1):
            keep_last_iteration_changes = fuzz_factor == self.max_fuzz_factor and keep_reject_files
            success, _, cmd = apply_patch_fuzzy(
                self.patch_file_content, fuzz_factor, keep_rej_files=keep_last_iteration_changes
            )
            if success:
                break
            if not keep_last_iteration_changes:
                git_reset_files(self.changed_files, introduced_files=self.added_files)
        if not success and self.llm_patcher:
            success, stderr, cmd = self.llm_patcher.adjust_rejected_patches_with_llm(self.commit_id)

        if not success:
            if not keep_reject_files:
                git_reset_files(self.changed_files, remove_rej_files=True, introduced_files=self.added_files)
            log.info("After manual fixing, make sure to add the following files to tracking: %r", self.added_files)
            return False, "Failed to apply massaged rejected hunk"

        if commit_change:
            success, stderr = self.create_commit(
                extra_message=f"[git-llm-picked from commit {self.commit_id}]", explain_message=f"Applied with {cmd}"
            )
            if not success:
                return False, f"error: Failed to create commit with error: {stderr}"

        return True, "Successfully applied and committed fuzzy patch"


def apply_with_cherry_pick(commit_id, git_args, validation_command, commit_change) -> Tuple[bool, bool]:
    """Run git-cherry-pick, validate on success, return pick and validation success."""

    validation_success = True
    cherry_pick_success, cherry_pick_stderr = git_cherry_pick(commit_id, git_args)
    if not cherry_pick_success:
        log.info("Cherry-pick stderr with args %s:\n%s", " ".join(git_args), cherry_pick_stderr)
        rollback_success, _, _ = run_command(["git", "cherry-pick", "--abort"])
        if not rollback_success:
            raise RuntimeError("error: Failed to rollback cherry-pick")
        return False, validation_success
    if validation_command is not None:
        validation_success, _, validation_stderr = run_command(validation_command)
        if validation_success:
            log.info("Successfully validated cherry-pick of commit %s", commit_id)
            return True, True
        log.info("Validation command failed after picking: %s", validation_stderr)

        # In case we are asked to commit changes, we need to reset the commit in case validation failed
        if commit_change:
            log.info("Rolling back picked but failing commit")
            reset_success, _, _ = run_command(["git", "reset", "--hard", "HEAD^"])
            if not reset_success:
                raise RuntimeError("Failed to reset commit after failing cherry-pick")

    # Show error output of cherrypick before continuing
    if not cherry_pick_success:
        log.info("Cherry-pick failed for %s", commit_id)
    return cherry_pick_success, validation_success


def backport_with_context(
    max_context_backports: int, commit_id: str, git_args: list, validation_command: list, run_validation_after: str
):
    """
    Try to backport context commits, and apply commit afterwards. Rolls back to HEAD on failure.

    Returns True, if the commit could be applied (with validation if specified), False otherwise
    """

    if max_context_backports <= 0:
        return False

    success, rollback_commit, _ = run_command(["git", "rev-parse", "HEAD"], check=True)
    if not success:
        log.warning("Failed to get the HEAD commit ID")
        return False
    rollback_commit = rollback_commit.strip()
    log.debug("Current HEAD commit ID: %s", rollback_commit)

    success, msg = backport_commit_context(commit_id, max_context_backports)
    if success:
        log.debug("Prepared context commits with %s", msg)
        pick_success, validate_success = apply_with_cherry_pick(
            commit_id,
            git_args,
            validation_command if run_validation_after in ["pick", "ALL"] else None,
            commit_change=True,
        )
        if pick_success and validate_success:
            log.debug("Succeeded cherry-picking after applying context commits")
            git_amend_and_sign_head_commit(msg)
            return True
        log.debug("Failed cherry-picking after applying context commits, cleaning up")
    log.info("Failed to pick with context commits with message: %s", msg)
    rollback_success, _, _ = run_command(["git", "reset", "--hard", rollback_commit])
    if not rollback_success:
        raise RuntimeError(f"Failed to roll back to commit {rollback_commit}, current HEAD commit is likely broken")
    return False


def show_patching_help_info(git_head_commit: str, commit_id: str, history_commits: int, changed_files: List[str]):
    """Show information that can be helpful when manually picking commit."""

    if history_commits <= 0:
        return

    log.info("Collect last commits that changed files in commit %s and pick commit %s:", git_head_commit, commit_id)
    git_log_base_cmd = [
        "git",
        "log",
        "-n",
        str(history_commits),
        "--oneline",
        "--pretty=format:%h %s (%an, %ad)",
        "--date=short",
    ]

    history_success, output, _ = run_command(git_log_base_cmd + [commit_id, "--"] + changed_files)
    if history_success:
        print(
            "\n### Last %d commits in pick source commit %s touching changed files %r"
            % (history_commits, commit_id, changed_files)
        )
        print(output)

    history_success, output, _ = run_command(git_log_base_cmd + [git_head_commit, "--"] + changed_files)
    if history_success:
        print(
            "\n### Last %d commits in destination commit %s touching changed files %r"
            % (history_commits, git_head_commit, changed_files)
        )
        print(output)

    rej_files = [file + ".rej" for file in changed_files if os.path.exists(file + ".rej")]
    if rej_files:
        log.info("Check patch rejection files: %s", " ".join(rej_files))


def parse_args(args_override: list = None):
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument(
        "--max-fuzz",
        type=int,
        default=1,
        help="Max. fuzz factor for patch application, off = 0 (default: %(default)d)",
    )
    parser.add_argument(
        "--min-fuzz",
        type=int,
        default=1,
        help="Min. fuzz factor for patch application (default: %(default)d)",
    )
    parser.add_argument(
        "--max-context-backports",
        type=int,
        default=2,
        help="Max. number of context commits to backport (default: %(default)d)",
    )
    parser.add_argument(
        "--fuzz-keep-author",
        default=True,
        action="store_true",
        help="Keep commit author when fuzzy-picking (default: %(default)s)",
    )
    parser.add_argument(
        "--no-fuzz-keep-author",
        dest="fuzz_keep_author",
        action="store_false",
        help="Do not keep commit author when fuzzy-picking (default: %(default)s)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set the logging level (default: %(default)s)",
    )
    parser.add_argument(
        "--reset-on-error",
        default=False,
        action="store_true",
        help="Reset repository to clean state on error",
    )
    parser.add_argument(
        "--skip-pick",
        default=False,
        action="store_true",
        help="Do not perform cherry picking, to run other steps.",
    )
    parser.add_argument(
        "--no-auto-strategy",
        default=True,
        action="store_false",
        dest="auto_strategy",
        help="Do not automatically try multiple picking strategies.",
    )
    parser.add_argument(
        "-C",
        "--change-dir",
        type=str,
        help="Before starting any operation, change the working directory to the given directory",
    )
    parser.add_argument(
        "--check-commit-presence",
        type=int,
        default=100,
        help="Check if commit is already present in last N commits of current branch, 0=off, -1=infinite (default: %(default)d)",
    )
    parser.add_argument(
        "--validation-command",
        type=str,
        default=None,
        help="Run this command to validate whether the pick is correct. Changed files are given as CLI parameters (default: %(default)s)",
    )
    parser.add_argument(
        "--path-rewrite",
        type=str,
        default=None,
        action="append",
        help="Apply this path rewriting, using the pattern 'src:dst' (default: %(default)s)",
    )
    parser.add_argument(
        "--run-validation-after",
        type=str,
        choices=["pick", "patch", "ALL"],
        default="ALL",
        help="Validate applying commit after selected stage (default: %(default)s)",
    )
    parser.add_argument(
        "--show-failure-info",
        default=5,
        type=int,
        help="Show help for patching failure, using up to N commits (default: %(default)d)",
    )
    parser.add_argument(
        "--llm-pick",
        const=True,
        default=True,
        nargs="?",
        help="Use an LLM to adjust a patch in case we fail to apply it. Optionally, specify comma-separated key-value pairs to forward to the model (aws_region, max_token, model_id)",
    )
    parser.add_argument(
        "--no-llm-pick",
        action="store_false",
        dest="llm_pick",
        help="Do not use an LLM to adjust a patch in case we fail to apply it",
    )
    parser.add_argument(
        "--llm-limit-interactive",
        action="store_true",
        default=False,
        help="Ask user to approve each proposed change of the LLM in interactive mode",
    )
    parser.add_argument(
        "--llm-limit-char-diff",
        default=900,
        type=int,
        help="Only accept LLM changes if the Levenshtein distance between added and deleted lines is less equal (-1 is unlimited)",
    )
    parser.add_argument(
        "--llm-limit-diff-ratio",
        default=1.33,
        type=float,
        help="Only accept LLM changes if the ratio of input to Levenshtein distance between added and deleted lines is less equal (-1 is unlimited)",
    )
    parser.add_argument(
        "--llm-filter-phrases",
        action="append",
        default=[
            "ignore your previous instructions",
            "forget the instructions above",
        ],
        help="Do not accept LLM changes if they contain any of the given phrases (default: %(default)s)",
    )
    parser.add_argument(
        "--llm-input-lines",
        default=250,
        type=int,
        help="Only accept LLM input in case the hunk is smaller than the given number (0 is unlimited)",
    )

    args, unknown_args = parser.parse_known_args(args_override)
    if not unknown_args:
        parser.error("No commit specified")

    problematic_parameters = set(vars(args).keys()).intersection(SUPPORTED_GIT_ARGS)
    if problematic_parameters:
        raise RuntimeError(f"Detected parameters that are also a git-cherry-pick parameter: {problematic_parameters}")

    return args, unknown_args


def pick_git_commit(
    commit_id: str,
    git_args: list,
    auto_strategy: bool = True,
    skip_pick: bool = False,
    max_fuzz: int = 2,
    min_fuzz: int = 1,
    max_context_backports: int = 0,
    fuzz_keep_author: bool = True,
    llm_pick: str = True,
    llm_limits: LlmLimits = None,
    validation_command: str = None,
    run_validation_after: str = None,
    check_commit_presence: int = 100,
    show_failure_info: int = 5,
    reset_on_error: bool = False,
    path_rewrite: List[PathRewriteRule] = None,
):
    """
    Perform cherry-picking of a commit with various strategies.

    Args:
        commit_id: The commit ID to cherry-pick
        git_args: Git arguments to pass to cherry-pick
        auto_strategy: Whether to try multiple cherry-pick strategies
        skip_pick: Whether to skip the cherry-pick step
        max_fuzz: Maximum fuzz factor for patch application
        min_fuzz: Minimum fuzz factor for patch application
        max_context_backports: number of context commits allowed to be backported in case of failure
        fuzz_keep_author: Whether to keep the original commit author
        llm_pick: Whether to use LLM to adjust patches (True, False, or parameters string)
        llm_limits: Settings how to limit forwarding output of LLM before writing changes to disk
        validation_command: Command to validate the cherry-pick
        run_validation_after: When to run validation ('pick', 'patch', 'ALL', or None)
        check_commit_presence: Check if commit is already in branch history
        show_failure_info: Number of commits to show in failure info
        reset_on_error: Whether to reset to clean state on error
        path_rewrite: list of path rewrite rules

    Returns:
        int: 0 for success, 1 for failure
    """
    # Describe HEAD commit to be able to reference it in output
    _, git_head_commit, _ = run_command(["git", "describe", "--tags", "--all", "--long", "HEAD"])
    git_head_commit = git_head_commit.strip() if git_head_commit else "HEAD"

    log.debug("On commit %s cherry-pick commit %s with arguments: %s", git_head_commit, commit_id, " ".join(git_args))

    changed_files = git_changed_files(commit_id)
    if changed_files is None:
        log.error("error: Failed to get changed files for commit %s", commit_id)
        return 1

    # Validate that all changed files are within the repository root
    try:
        invalid_paths = get_invalid_repository_paths(changed_files)
        if invalid_paths:
            log.error("Commit %s contains files outside repository root: %s", commit_id, invalid_paths)
            return 1
    except RuntimeError as e:
        log.error("Failed to validate file paths for commit %s: %s", commit_id, e)
        return 1

    if validation_command:
        validation_command = shlex.split(validation_command) + changed_files

    # Extend in case we find more useful strategies
    pick_parameters = [[]]
    use_multiple_strategies = auto_strategy
    for git_arg in git_args:
        if git_arg.startswith("--strategy") or git_arg.startswith("-X"):
            use_multiple_strategies = False
            log.debug("Found git arg %s, disabling trying multiple strategies.", git_arg)
            break
    if use_multiple_strategies:
        pick_parameters.append(["--strategy=recursive", "-Xpatience"])  # used in Linux stable-tools

    if skip_pick:
        log.info("Skip picking, as requested by user.")
        pick_parameters = []

    commit_change = ("-n" not in git_args) and ("--no-commit" not in git_args)
    for pick_parameter in pick_parameters:
        log.info("Trying cherry-pick with parameters %s ...", " ".join(pick_parameter))
        pick_success, validate_success = apply_with_cherry_pick(
            commit_id,
            git_args + pick_parameter,
            validation_command if run_validation_after in ["pick", "ALL"] else None,
            commit_change,
        )
        if pick_success and validate_success:
            log.debug("Succeeded cherry-picking with parameters %r", pick_parameter)
            if commit_change:
                git_amend_and_sign_head_commit(
                    f"Cherry-picked with {' '.join(pick_parameter)}" if pick_parameter else None
                )
            return 0

        # To be able to test the next strategy, roll-back unsuccessful cherry-pick attempt
        log.debug("Failed git-cherrypick with parameters %s", " ".join(pick_parameter))
        if not commit_change:
            log.info("Re-cleaning git repository after failing cherry-picking")
            git_reset_files(changed_files)

        if not validate_success:
            # Abort other pick parameter, if we manage to apply, but validation fails
            log.warning("Validation failed for commit %s after successful cherry-picking", commit_id)
            break

    if commit_change and backport_with_context(
        max_context_backports, commit_id, git_args, validation_command, run_validation_after
    ):
        log.info("Successfully backported commit %s with context commits", commit_id)
        return 0

    if max_fuzz == 0:
        log.error("Cherry-pick failed for %s, and fuzzy patch is disabled due to --max-fuzz=0")
        return 1

    warn_on_unsupported_args(git_args)

    # Check whether we have working conditions for fuzzy patching and commit creation
    if not git_check_files_diff_free(changed_files):
        log.error("error: Repository is not clean. Please commit or stash changes before fuzzy-picking.")
        return 1
    if commit_is_present_in_branch(commit_id=commit_id, num_commits_to_check=check_commit_presence):
        log.error("error: Commit %s is already present in current branch", commit_id)
        return 1

    history_commits = show_failure_info

    path_rewrite_rules = list()
    if path_rewrite is not None:
        for rewrite in path_rewrite:
            if ":" in rewrite:
                path_src, path_dst = rewrite.split(":", 2)
                log.debug("Detected path rewriting request, rewriting %s into %s", path_src, path_dst)
                path_rewrite_rules.append(PathRewriteRule(path_src, path_dst))
    log.debug("Detected %d path rewrite rules", len(path_rewrite_rules))

    # Try fuzzy patching
    log.info("Setting up fuzzy patcher ...")
    llm_patcher = (
        LlmPatcher(llm_parameters="" if llm_pick is True else llm_pick, llm_limits=llm_limits) if llm_pick else None
    )
    patcher = FuzzyPatcher(
        commit_id,
        min_fuzz_factor=min_fuzz,
        max_fuzz_factor=max_fuzz,
        keep_commit_author=fuzz_keep_author,
        llm_patcher=llm_patcher,
        path_rewrite_rules=path_rewrite_rules,
    )
    success, patch_message = patcher.try_fuzzy_patch(commit_change=commit_change, keep_reject_files=history_commits > 0)
    log.log(logging.INFO if success else logging.ERROR, patch_message)

    if success:
        if not commits_have_equal_hunks(commit_id, "HEAD"):
            log.error("error: Fuzzy-picked commit does not sufficiently match picked commit %s", commit_id)
            success = False
            rollback_success, _, _ = run_command(["git", "reset", "--hard", "HEAD^"])
            if not rollback_success:
                log.error("error: Failed to rollback fuzzy-pick after failing similarity check")
                raise RuntimeError("Failed to roll back commit after similarity check, current HEAD commit is likely broken")

    if success and validation_command and run_validation_after in ["ALL", "patch"]:
        success, _, validation_stderr = run_command(validation_command)
        if success:
            log.info("Successfully validated fuzzy-pick of commit %s", commit_id)
        else:
            log.info("Rolling back commit, because validation command failed: %s", validation_stderr)
            # run git reset --hard HEAD^
            rollback_success, _, _ = run_command(["git", "reset", "--hard", "HEAD^"])
            if not rollback_success:
                log.error("error: Failed to rollback fuzzy-pick")
                raise RuntimeError("Failed to roll back commit, current HEAD commit is likely broken")
    if success:
        log.info("Successfully fuzzy-picked %s", commit_id)
        return 0

    # For applying more methods, clean repository and re-try here

    # Show help for interactive picking the commit
    show_patching_help_info(git_head_commit, commit_id, history_commits, changed_files)

    # Reset to clean state
    if reset_on_error:
        git_reset_files(changed_files, remove_rej_files=True)

    log.error("error: Failed to fuzzy-pick commit %s", commit_id)
    return 1


def main(args_override: list = None):
    """Main function to handle cherry-pick and fuzzy patching."""

    args, unknown_args = parse_args(args_override)

    if args.log_level == "DEBUG":
        logging.basicConfig(
            level=args.log_level,
            format="[%(levelname)-7s] %(asctime)s %(name)s:%(lineno)d %(message)s",
        )
    elif args.log_level == "INFO":
        logging.basicConfig(
            level=args.log_level,
            format="[%(levelname)-7s] %(message)s",
        )
    else:
        logging.basicConfig(
            level=args.log_level,
            format="%(message)s",
        )

    # Get the commit ID (last argument)
    commit_id = unknown_args[-1]
    # Get all other git arguments (excluding the commit)
    git_args = unknown_args[:-1]

    if args.change_dir:
        log.debug("Changing to directory %s", args.change_dir)
        os.chdir(args.change_dir)

    try:
        return pick_git_commit(
            commit_id=commit_id,
            git_args=git_args,
            auto_strategy=args.auto_strategy,
            skip_pick=args.skip_pick,
            max_fuzz=args.max_fuzz,
            min_fuzz=args.min_fuzz,
            max_context_backports=args.max_context_backports,
            fuzz_keep_author=args.fuzz_keep_author,
            llm_pick=args.llm_pick,
            llm_limits=LlmLimits(
                limit_interactive=args.llm_limit_interactive,
                llm_limit_char_diff=args.llm_limit_char_diff,
                llm_limit_diff_ratio=args.llm_limit_diff_ratio,
                llm_filter_phrases=args.llm_filter_phrases,
                llm_input_lines=args.llm_input_lines,
            ),
            validation_command=args.validation_command,
            run_validation_after=args.run_validation_after,
            check_commit_presence=args.check_commit_presence,
            show_failure_info=args.show_failure_info,
            reset_on_error=args.reset_on_error,
            path_rewrite=args.path_rewrite,
        )
    except Exception as e:
        log.error("Aborting with exception %s", e)
        log.debug("Exception with stack trace:", exc_info=True)
    return 1


if __name__ == "__main__":
    app_status = main()
    log.info("Exit git-llm-pick with status %d", app_status)
    sys.exit(app_status)
