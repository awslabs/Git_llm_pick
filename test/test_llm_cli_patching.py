"""Tests picking commits end to end, using cached LLM answers."""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import contextlib
import os
import shutil
import tempfile
from unittest.mock import patch

from git_llm_pick.git_commands import git_get_commits_contextdiff
from git_llm_pick.git_llm_pick import main
from git_llm_pick.patch_matching import commits_have_equal_hunks
from git_llm_pick.utils import run_command

TEST_DIR_PATH = os.path.dirname(os.path.realpath(__file__))
TEST_ARTEFACTS_DIR = os.path.join(TEST_DIR_PATH, "patch_artifacts", "cli_patching")


@contextlib.contextmanager
def pushd(new_dir):
    """Similar to shell's pushd, popd is implicit"""
    previous_dir = os.getcwd()
    os.chdir(new_dir)
    try:
        yield
    finally:
        os.chdir(previous_dir)


def test_llm_pick_on_git():
    """Test that we can use the CLI to pick commits with the LLM."""

    cache_file = os.path.join(TEST_ARTEFACTS_DIR, "patch_cache.json")

    mock_commit_message = """commit c491436daf7e03bac8dbdab34f07b8dcb2feca5c
Author: Norbert Manthey <nmanthey@amazon.de>
Date:   Fri Aug 1 12:13:14 2025 +0200

    Add this change
"""

    with tempfile.TemporaryDirectory() as tmpdir, pushd(tmpdir), patch(
        "git_llm_pick.llm_patching.get_commit_message"
    ) as get_commit_message, patch("git_llm_pick.llm_patching.generate_nonce", return_value="12345678"):

        # Make sure the input for the LLM is independent of timestamp or commit ID
        get_commit_message.return_value = mock_commit_message

        # Prepare git repo
        run_command(["git", "init", "."])
        local_file = "lib.c"

        # Create branch "main-series" with lib.c file, and two changes
        success, _, _ = run_command(["git", "branch", "-m", "main-series"])
        assert success, "Should be able to rename branch"
        shutil.copy(os.path.join(TEST_ARTEFACTS_DIR, "lib-v1.c"), local_file)
        success, _, _ = run_command(["git", "add", local_file])
        assert success, "Should be able to add file"
        success, _, _ = run_command(["git", "commit", "-m", "Initial commit", local_file])
        assert success, "Should be able to create initial commit"
        success, base_commit, _ = run_command(["git", "rev-parse", "HEAD"], check=True)
        assert success, "Should be able to get commit ID"
        base_commit = base_commit.strip()

        shutil.copy(os.path.join(TEST_ARTEFACTS_DIR, "lib-v2.c"), local_file)
        success, _, _ = run_command(["git", "commit", "-m", "Add second change", local_file])
        assert success, "Should be able to commit the second change"
        success, _, _ = run_command(["git", "rev-parse", "HEAD"], check=True)
        assert success, "Should be able to get commit ID"

        shutil.copy(os.path.join(TEST_ARTEFACTS_DIR, "lib-v3.c"), local_file)
        success, _, _ = run_command(["git", "commit", "-m", "Add this change", local_file])
        assert success, "Should be able to commit the third change"
        success, tip_commit, _ = run_command(["git", "rev-parse", "HEAD"], check=True)
        assert success, "Should be able to get the tip commit ID"
        tip_commit = tip_commit.strip()

        # Create branch "small-series" with lib.c file, try to get third change
        success, _, _ = run_command(["git", "checkout", "-b", "small-series", base_commit])
        assert success, "Should be able to checkout a new branch"

        # Focus on LLM part
        args = [
            f"--llm-pick=cache_file={cache_file}",
            "--skip-pick",
            "--min-fuzz",
            "1",
            "--max-fuzz",
            "1",
            "--max-context-backports",
            "0",
            "-x",
            tip_commit,
        ]

        # Run llm-picking with cached LLM result, and mocked commit messages
        ret = main(args_override=args)
        assert ret == 0, "Patching should succeed"
        with open(local_file, "r") as generated_file:
            generated_file_content = generated_file.read()

            assert "int sum_array" not in generated_file_content, "Should not keep change 2 code in file"
            assert "int diff_array" in generated_file_content, "Fixed function should be in code"
            assert (
                "for (int i = min_size; i < size1; i++)" in generated_file_content
            ), "Fixed function should be in code"
            assert (
                "for (int i = min_size; i < size2; i++)" in generated_file_content
            ), "Fixed function should be in code"

        # Backported commit is similar to actual commit
        assert commits_have_equal_hunks(tip_commit, "HEAD")
        commit_diff = git_get_commits_contextdiff(tip_commit, "HEAD")
        import logging

        logging.debug("Commit diff: %s", commit_diff)
        assert commit_diff

        # Succeed patching if high edit distance limit is given
        success, _, _ = run_command(["git", "reset", "--hard", base_commit])
        assert success
        ret = main(args_override=["--llm-limit-char-diff", "100"] + args)
        assert ret == 0, "With high edit distance, the change should apply"

        # Fail patching in case we restrict the allowed edit distance (--llm-limit-char-diff 1)
        success, _, _ = run_command(["git", "reset", "--hard", base_commit])
        assert success
        ret = main(args_override=["--llm-limit-char-diff", "1"] + args)
        assert ret == 1, "With limited edit distance, the change should not be applied"

        # Succeed patching in case we do not detect a filter phrase
        success, _, _ = run_command(["git", "reset", "--hard", base_commit])
        assert success
        ret = main(args_override=["--llm-filter-phrases", "Complex filter phrase"] + args)
        assert ret == 0, "With the commit as filter phrase, picking is expected to succeed"

        # Fail patching in case we detect a filter phrase (e.g. "Add this change")
        success, _, _ = run_command(["git", "reset", "--hard", base_commit])
        assert success
        ret = main(args_override=["--llm-filter-phrases", "Add this change"] + args)
        assert ret == 1, "With the commit as filter phrase, picking is expected to fail"

        # Succeed patching in case we do allow a high number of changes
        success, _, _ = run_command(["git", "reset", "--hard", base_commit])
        assert success
        ret = main(args_override=["--llm-input-lines", "20"] + args)
        assert ret == 0, "With a high change line limit, the change should be applied"

        # Fail patching in case we do not allow many changed lines
        success, _, _ = run_command(["git", "reset", "--hard", base_commit])
        assert success
        ret = main(args_override=["--llm-input-lines", "1"] + args)
        assert ret == 1, "With a low change line limit, no change should be applied"

        # Backport with context commits, but without the LLM
        success, _, _ = run_command(["git", "reset", "--hard", base_commit])
        assert success
        full_args = [
            "--skip-pick",
            "--no-llm-pick",
            "--max-context-backports",
            "2",
            "-x",
            tip_commit,
        ]
        ret = main(args_override=full_args)
        assert ret == 0, "Allow to apply commit by using context commit first"
        success, log_output, _ = run_command(["git", "log", "--pretty=format:%H", "HEAD"])
        assert len(log_output.splitlines()) == 3
        assert log_output.splitlines()[-1] == base_commit
