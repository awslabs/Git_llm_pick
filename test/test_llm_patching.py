"""Tests Patching Hunks without Section"""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import contextlib
import logging
import os
import shutil
import tempfile
from unittest.mock import patch

from unidiff import PatchSet

from git_llm_pick.llm_patching import LlmLimits, LlmPatcher

TEST_DIR_PATH = os.path.dirname(os.path.realpath(__file__))
TEST_ARTEFACTS_DIR = os.path.join(TEST_DIR_PATH, "patch_artifacts", "hunk_patching")


@contextlib.contextmanager
def pushd(new_dir):
    """Similar to shell's pushd, popd is implicit"""
    previous_dir = os.getcwd()
    os.chdir(new_dir)
    try:
        yield
    finally:
        os.chdir(previous_dir)


def test_hunk_patching():
    """Test that a cached answer can be used to patch a known file."""

    # Cache file can be copied from a first version of the test with an empty cache file
    cache_file = os.path.join(TEST_ARTEFACTS_DIR, "patch_cache.json")
    patch_file = os.path.join(TEST_ARTEFACTS_DIR, "div.patch")
    target_file = "base.c"

    for limits in [None, LlmLimits(), LlmLimits(llm_limit_char_diff=1000), LlmLimits(llm_input_lines=100)]:

        with tempfile.TemporaryDirectory() as tmpdir:

            # Copy file TEST_DIR_PATH / patch_artifacts / hunk_patching / userfaultfd.c into tmp dir
            shutil.copyfile(os.path.join(TEST_ARTEFACTS_DIR, target_file), os.path.join(tmpdir, target_file))
            # Use pre-initialized cache file, which has the LLM answer for this example prepared
            llm_patcher = LlmPatcher(llm_parameters="cache_file=" + cache_file, llm_limits=limits)

            with pushd(tmpdir):
                with patch("git_llm_pick.llm_patching.generate_nonce", return_value="12345678"):
                    patchset = PatchSet.from_filename(patch_file, encoding="utf-8")
                    hunks_with_empty_section = patchset[0]
                    logging.debug("Hunks with empty section: %r", hunks_with_empty_section)
                    success, _, _ = llm_patcher.apply_hunks_with_empty_section(
                        hunks_with_empty_section=hunks_with_empty_section,
                        patch_target_file=target_file,
                        commit_message="",
                    )

                    # For human inspection, copy out the file
                    shutil.copyfile(os.path.join(tmpdir, target_file), f"/tmp/{target_file}")

                    # Check file base.c was patched
                    with open(target_file, "r") as f:
                        patched_file_lines = f.readlines()

                    function_line = "float divide(int a, int b) {\n"
                    division_text = "Error: Division by zero"
                    return_line = "    return (float)a / b;\n"

                    assert any(
                        division_text in line for line in patched_file_lines
                    ), f"Failed to find {division_text} in expected output"

                    function_line_index = patched_file_lines.index(function_line)
                    patched_line1_index = next(i for i, line in enumerate(patched_file_lines) if division_text in line)
                    patched_line2_index = patched_file_lines.index(return_line)

                    assert function_line_index > 0
                    assert function_line_index < patched_line1_index
                    assert patched_line1_index < patched_line2_index

            assert success


def test_hunk_query_replacements():
    """Test that the fields to be replaced in the query are actually replaced."""

    # Cache file can be copied from a first version of the test with an empty cache file
    patch_file = os.path.join(TEST_ARTEFACTS_DIR, "div.patch")
    target_file = "base.c"

    with tempfile.TemporaryDirectory() as tmpdir:

        # Copy file TEST_DIR_PATH / patch_artifacts / hunk_patching / base.c into tmp dir
        shutil.copyfile(os.path.join(TEST_ARTEFACTS_DIR, target_file), os.path.join(tmpdir, target_file))
        # Use pre-initialized cache file, which has the LLM answer for this example prepared
        llm_patcher = LlmPatcher()
        with pushd(tmpdir), patch("git_llm_pick.llm_patching.generate_nonce", return_value="12345678"), patch(
            "git_llm_pick.llm_client.LlmClient"
        ) as mocked_llm_client:
            # Use mocked answer to not use AWS service
            mocked_llm_client.return_value.ask.return_value = "I could not modify the code as requested"

            patchset = PatchSet.from_filename(patch_file, encoding="utf-8")
            hunks_with_empty_section = patchset[0]
            logging.debug("Hunks with empty section: %r", hunks_with_empty_section)
            fail_success, _, _ = llm_patcher.apply_hunks_with_empty_section(
                hunks_with_empty_section=hunks_with_empty_section,
                patch_target_file=target_file,
                commit_message="",
            )

            # Check the PROMPT_NONCE was replaced in input query
            mocked_llm_client.return_value.ask.assert_called_once()

            unexpected_pattern = [
                "COMMIT_MESSAGE",
                "REJECTED_HUNK_CONTENT",
                "SOURCE_FILE_NAME",
                "DESTINATION_FUNCTION",
                "SOURCE_FUNCTION",
            ]
            for pattern in unexpected_pattern:
                assert pattern not in mocked_llm_client.return_value.ask.call_args[0][0]
            assert "12345678" in mocked_llm_client.return_value.ask.call_args[0][0]

            # Replacement call from user input stays in message
            assert "{PROMPT_NONCE}" in mocked_llm_client.return_value.ask.call_args[0][0]

            assert not fail_success
