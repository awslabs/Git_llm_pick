#!/usr/bin/env python3

"""
Git command wrapper methods.
"""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import logging
import os
from difflib import context_diff
from typing import List, Tuple

from unidiff import PatchSet

from git_llm_pick.utils import run_command

log = logging.getLogger(__name__)


def git_changed_files(commit_id) -> List[str]:
    """Get the list of files changed in a commit."""
    success, stdout, _ = run_command(["git", "show", "--name-only", "--format=", commit_id])
    if not success:
        return None
    return stdout.splitlines()


def git_added_files(commit_id) -> List[str]:
    """Get the list of files added in a commit."""
    success, stdout, _ = run_command(["git", "show", "--diff-filter=A", "--name-only", "--format=", commit_id])
    if not success:
        return None
    return stdout.splitlines()


def git_check_files_diff_free(file_list: List[str]) -> bool:
    """Check if the files in the list are diff-free."""
    for file in file_list:
        success, _, _ = run_command(["git", "diff", "--exit-code", "--", file])
        if not success:
            return False
        success, _, _ = run_command(["git", "diff", "--cached", "--exit-code", "--", file])
        if not success:
            return False
    return True


def git_reset_files(file_list: List[str], remove_rej_files: bool = False, introduced_files: List[str] = None):
    """Reset the files in the list, and remove related reject files if requested."""
    overall_success = True
    for file in file_list:
        if remove_rej_files:
            if os.path.exists(file + ".rej"):
                os.remove(file + ".rej")

        # Remove introduced files, if any are given, do not perform git operations on it
        if introduced_files and file in introduced_files:
            os.unlink(file)
            continue

        success, _, _ = run_command(["git", "reset", "--", file])
        success, _, _ = run_command(["git", "checkout", "--", file])
        _, status, _ = run_command(["git", "status", "--porcelain", file])
        # In case the commit brings files that are added, remove them again
        log.debug("Obtained git status for file %s: %s", file, status)
        if status and status.strip() == f"DU {file}":
            run_command(["git", "rm", file])
        if not success:
            overall_success = False
    return overall_success


def git_commit_date(commit_id):
    """Return commit date for the given commit."""
    success, stdout, _ = run_command(["git", "show", "-s", "--format=%ct", commit_id])
    if not success or stdout.strip() == "":
        return 0
    return int(stdout.strip())


def get_commit_message(commit: str) -> str:
    """Return commit message."""
    success, commit_message, _ = run_command(["git", "show", "-s", commit])
    if not success:
        raise RuntimeError(f"Failed to extract commit message for commit {commit}")
    return commit_message


def get_commit_subject(commit: str) -> str:
    """Return commit subject."""
    success, commit_subject, _ = run_command(["git", "show", "-s", "--format=%s", commit])
    if not success:
        raise RuntimeError(f"Failed to extract commit subject for commit {commit}")
    return commit_subject.strip()


def commit_is_present_in_branch(commit_id: str, num_commits_to_check: int = 100) -> bool:
    """Check if a commit's subject line is unique in the branch history."""

    log.debug(
        "Check commit %s being present in current branch's %scommits",
        commit_id,
        f"last {num_commits_to_check} " if num_commits_to_check >= 0 else "",
    )
    if num_commits_to_check == 0:
        return False

    # Get the subject of the commit we're checking
    commit_subject = get_commit_subject(commit_id)

    # Get subjects of recent commits, to check whether already present
    cmd = ["git", "log", "--format=%s"]
    if num_commits_to_check > 0:
        cmd += [f"-n{num_commits_to_check}"]
    success, recent_subject_output, stderr = run_command(cmd)
    if not success:
        log.warning("Failed to extract recent commit subjects with stderr: %s", stderr)
        return False
    recent_subjects = recent_subject_output.splitlines()
    return commit_subject in recent_subjects


def commit_function_location(file_path, function_line, show_commit="HEAD"):
    """Return startline and endline for the given function as tuple together with the file lines, or raise Runtime error."""

    success, full_file_content, stderr = run_command(["git", "show", "-s", f"{show_commit}:{file_path}"])
    if not success:
        log.warning("Failed to extract future file content with stderr: %s", stderr)
        raise RuntimeError(f"Failed to extract future file content for file {file_path} for commit {show_commit}")

    log.debug(
        "Detect function line %s in file with %d lines for commit %s",
        function_line,
        len(full_file_content),
        show_commit,
    )
    from git_llm_pick.utils import code_section_location

    return code_section_location(function_line, full_file_content.splitlines())


def git_cherry_pick(commit_id: str, args=[]) -> Tuple[bool, str]:
    """Cherry-pick commit ID with optional additional arguments, return success."""

    success, stdout, stderr = run_command(["git", "cherry-pick"] + args + [commit_id])
    if success:
        print(stdout)
    return success, stderr


def git_amend_and_sign_head_commit(extra_message: str = None, git_notes: str = None) -> Tuple[bool, str]:
    """Add the given message to the commit message of HEAD, and a signed-off-by line."""
    success, commit_msg, _ = run_command(["git", "log", "-1", "--format=%B", "HEAD"])
    if not success:
        return False, "Failed to get commit message"

    log.debug("Create commit with extra message: %s", extra_message)
    extension = "\n" + extra_message if extra_message else ""
    success, _, stderr = run_command(["git", "commit", "--amend", "-s", "-m", commit_msg + extension])
    if not success:
        return False, stderr
    if git_notes:
        log.debug("Add git notes: %s", git_notes)
        success, _, stderr = run_command(["git", "notes", "add", "-m", git_notes])
        if not success:
            return False, stderr
    return True, None


def get_diff_from_commit(commit_id: str, diff_lines: int = -1) -> PatchSet:
    """Get the diff for the specified commit."""
    cmd = ["git", "show"]
    if diff_lines > 0:
        cmd += f"--unified={diff_lines}"
    success, commit_diff, _ = run_command(cmd + [commit_id])
    if not success:
        return None
    return PatchSet(commit_diff)


def git_get_commits_contextdiff(commit_id_left: str, commit_id_right: str) -> str:
    """Return the diff of the content of two commits."""

    def get_hunk_content(hunk):
        """Extract the content of a hunk from the diff."""
        return "\n".join([str(line) for line in hunk])

    def hunks_have_same_content(left_hunk, right_hunk):
        """Compare if two hunks have the same content, ignoring metadata like line numbers."""
        # Get lines from both hunks
        left_lines = [line.value.strip() for line in left_hunk]
        right_lines = [line.value.strip() for line in right_hunk]

        # Compare actual content, ignoring whitespace
        if len(left_lines) != len(right_lines):
            return False
        for left, right in zip(left_lines, right_lines):
            if left != right:
                return False
        return True

    left_patchset = get_diff_from_commit(commit_id_left)
    right_patchset = get_diff_from_commit(commit_id_right)

    # Filter hunks that are similar enough
    left_patchset_codechanges = {}
    for patch in left_patchset:
        for hunk in patch:
            if not hunk.section_header:
                continue
            index = f"{patch.target_file}:{hunk.section_header}:{get_hunk_content(hunk)}"
            if index in left_patchset_codechanges:
                raise RuntimeError("Duplicate hunks in incoming patch, cannot be handled")
            left_patchset_codechanges[index] = hunk

    right_patchset_codechanges = {}
    for patch in right_patchset:
        for hunk in patch:
            index = f"{patch.target_file}:{hunk.section_header}:{get_hunk_content(hunk)}"
            if index in right_patchset_codechanges:
                raise RuntimeError("Duplicate hunks in compared patch, cannot be handled")
            if index in left_patchset_codechanges and hunks_have_same_content(left_patchset_codechanges[index], hunk):
                left_patchset_codechanges.pop(index)
            else:
                right_patchset_codechanges[index] = hunk

    left_patch = "\n".join([str(x) for x in (sorted(left_patchset_codechanges.values()))])
    right_patch = "\n".join([str(x) for x in (sorted(right_patchset_codechanges.values()))])

    # Convert patches to lists of lines
    left_lines = [x for x in left_patch.splitlines(keepends=True) if not x.startswith("index")]
    right_lines = [x for x in right_patch.splitlines(keepends=True) if not x.startswith("index")]

    # Generate unified diff
    diff = context_diff(left_lines, right_lines)
    diff_lines = "".join(diff).splitlines()
    log.debug("Patch diff: %r", diff_lines)
    return "\n".join(diff_lines[3:])


def get_blame_commits_for_range(commit_parent: str, filename: str, start: int, end: int) -> list[str]:
    """Get git blame information for a specific line range in a file."""

    cmd = ["git", "blame", "-l", f"-L {start},{end}", commit_parent, "--", filename]
    success, output, _ = run_command(cmd)
    if not success:
        return None

    blame_info = []
    for line in output.splitlines():
        if not line:
            continue
        parts = line.split(" ", 1)
        commit = parts[0]
        blame_info.append(commit)

    return blame_info


def find_context_commits(commit_id: str, context: int = 3) -> set[str]:
    """Find all commits that touched code near the changes in the given commit."""
    context_commits = set()
    patch_set = get_diff_from_commit(commit_id, 0)
    if not patch_set:
        log.debug("Failed to retrieve patch set from commit %s", commit_id)
        return None

    for patched_file in patch_set:
        filename = patched_file.path
        for hunk in patched_file:
            # Calculate the range to blame, including context
            start = max(1, hunk.target_start - context)
            end = hunk.target_start + hunk.target_length + context

            blame_info = get_blame_commits_for_range(f"{commit_id}^", filename, start, end)
            if not blame_info:
                continue
            for context_commit in blame_info:
                if context_commit != commit_id and not context_commit.startswith("^"):
                    context_commits.add(context_commit)

    return context_commits


def backport_commit_context(commit_id: str, max_context_backports: int = 0, nr_history_commits: int = 5):
    """When cherry-picking a commit, check its history, and context, for required commits."""

    log.info(
        "Attempting to apply at most %d context commits before picking commit %s", max_context_backports, commit_id
    )
    changed_files = git_changed_files(commit_id)
    git_log_base_cmd = [
        "git",
        "log",
        "-n",
        str(nr_history_commits),
        "--oneline",
        "--pretty=format:%H",
    ]
    history_success, history_commit_output, _ = run_command(git_log_base_cmd + [commit_id, "--"] + changed_files)
    if not history_success:
        return False, "Failed to get history commits"
    history_commits = history_commit_output.splitlines()
    log.debug("History commits found for repository: %r", history_commits)

    context_commits = find_context_commits(commit_id=commit_id)
    log.debug("Found context commits for commit %s: %r", commit_id, context_commits)

    # Filter context commits to recent commits, and only use the most recent max_context_backports commits
    recent_context_commits = [c for c in history_commits if c in context_commits]
    recent_context_commits = recent_context_commits[-max_context_backports:]

    log.debug(
        "From %d history commits, and %d context commits, return %d commits as relevant history commits",
        len(history_commits),
        len(context_commits),
        len(recent_context_commits),
    )

    if not recent_context_commits:
        return False, "No context commits found for commit history"

    commit_subject = get_commit_subject(commit_id)
    msg = f"Applied {len(recent_context_commits)} context commits to pick commit {commit_id}"
    for context_commit in recent_context_commits:
        success, stderr = git_cherry_pick(context_commit, args=["-x"])
        if not success:
            log.debug("Failed picking commit %s with %s", context_commit, stderr)
            rollback_success, _, _ = run_command(["git", "cherry-pick", "--abort"])
            if not rollback_success:
                raise RuntimeError("error: Failed to rollback cherry-picking context commit")
            msg = f"Failed to cherry-pick commit {context_commit}"
            break
        # Add dependency info, ignore failures
        git_amend_and_sign_head_commit(f'Cherry-picked as dependency for "{commit_subject}"')

    return success, msg
