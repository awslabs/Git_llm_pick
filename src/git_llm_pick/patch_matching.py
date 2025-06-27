"""
Module implementing matching on patches and hunks.
"""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import logging
import os
from typing import Any, List, Optional

from unidiff import PatchSet

from git_llm_pick.utils import run_command

log = logging.getLogger(__name__)

# Only match hunks if the searchable hunk is not too far away
HUNK_SECTION_HEADER_MATCHING_MAX_LINE_OFFSET = 100

# Only consider a hunk matching, if the overlap is at least 95 percent
HUNK_SECTION_HEADER_MATCHING_MIN_MATCHING_PERCENT = 95


def parse_commit_hunks(commit_id: str) -> Optional[dict]:
    """Parse hunks from a commit and return a dictionary mapping file paths to their hunks."""

    # Get the patch content from the commit
    success, patch_content, stderr = run_command(["git", "show", commit_id])
    if not success:
        log.warning("Failed to get patch content for commit %s: %s", commit_id, stderr)
        return None

    try:
        patch_set = PatchSet(patch_content)

        file_hunks = {}
        for patch in patch_set:
            # Remove the path prefix as used in git (defaults to a/ and b/, but can be configured)
            file_path = None
            if os.sep in patch.target_file:
                file_path = patch.target_file.split(os.sep, 1)[1]
            if not file_path:
                log.warning("Failed to parse file path from %s", patch.target_file)
                continue
            if file_path not in file_hunks:
                file_hunks[file_path] = []
            file_hunks[file_path].extend(list(patch))

        log.debug("Parsed %d files with hunks from commit %s", len(file_hunks), commit_id)
        return file_hunks

    except Exception as e:
        log.warning("Failed to parse patch content for commit %s: %s", commit_id, str(e))
        return None


def find_section_header_of_matching_hunk(rejected_hunk: Any, original_hunks: Optional[List]) -> Optional[str]:
    """Find a matching hunk from the original commit that has a section header.

    Args:
        rejected_hunk (Any): The hunk from the rejected patch that lacks a section header (unidiff.Hunk)
        original_hunks (List): List of hunks from the original commit for the same file

    Returns:
        Optional[str]: The section header from the matching original hunk, or None if no match found
    """

    if not original_hunks:
        return None

    # Try to match based on source line numbers and content similarity
    for original_hunk in original_hunks:
        if not original_hunk.section_header or not original_hunk.section_header.strip():
            continue

        # Check if line numbers are close (allowing for some offset due to previous changes)
        line_diff = abs(rejected_hunk.source_start - original_hunk.source_start)
        if line_diff > HUNK_SECTION_HEADER_MATCHING_MAX_LINE_OFFSET:  # Allow reasonable offset
            continue

        # Check content similarity by comparing some lines
        log.debug("Check rejected_hunk %r with %r", rejected_hunk, [line for line in rejected_hunk.source])
        rejected_lines = [line.strip() for line in rejected_hunk.source if line.strip()]
        original_lines = [line.strip() for line in original_hunk.source if line.strip()]

        if not rejected_lines or not original_lines:
            continue

        # Calculate similarity
        matching_lines = 0
        for rejected_line in rejected_lines:
            if rejected_line in original_lines:
                matching_lines += 1

        similarity = matching_lines / max(len(rejected_lines), len(original_lines))
        if similarity >= HUNK_SECTION_HEADER_MATCHING_MIN_MATCHING_PERCENT / 100.0:
            log.debug(
                "Found matching hunk with section header '%s' (similarity: %.2f)",
                original_hunk.section_header,
                similarity,
            )
            return original_hunk.section_header

    return None


def commits_have_equal_hunks(commit_ref1, commit_ref2):
    """Parse the two commits, and make sure they have the same amount of hunks and changed files."""

    if not commit_ref1 or not commit_ref2:
        return False

    hunks1 = parse_commit_hunks(commit_ref1)
    hunks2 = parse_commit_hunks(commit_ref2)

    if not hunks1 or not hunks2:
        return False

    nr_changed_files1 = len(hunks1)
    nr_changed_files2 = len(hunks2)
    nr_hunks1 = sum(len(hunks1[file]) for file in hunks1)
    nr_hunks2 = sum(len(hunks2[file]) for file in hunks2)
    log.debug(
        "Compare commits %s and %s with changed files %d vs %d and changed hunks %d vs %d",
        commit_ref1,
        commit_ref2,
        nr_changed_files1,
        nr_changed_files2,
        nr_hunks1,
        nr_hunks2,
    )

    # Return true, if the number of total hunks, i.e. elements in the lists, is the same
    if nr_changed_files1 == nr_changed_files2 and nr_hunks1 == nr_hunks2:
        return True
    log.warning("Commits %s and %s have different hunks", commit_ref1, commit_ref2)
    return False
