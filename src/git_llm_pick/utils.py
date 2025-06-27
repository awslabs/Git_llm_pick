#!/usr/bin/env python3

"""
Utility functions to interact with files and help with patching.
"""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import logging
import os
import re
import subprocess
from typing import List, Set, Tuple

import Levenshtein

from git_llm_pick import SUPPORTED_GIT_ARGS

log = logging.getLogger(__name__)


def run_command(cmd: list, check: bool = False, input_data: str = None) -> Tuple[bool, str, str]:
    """Run a command and return its status, stdout, and stderr."""
    log.debug("Running command %r ...", cmd)
    try:
        result = subprocess.run(cmd, check=check, capture_output=True, text=True, input=input_data)
        log.debug("Command %r returned %d", cmd, result.returncode)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.CalledProcessError as e:
        log.debug("Command %r failed: %r", cmd, e)
        return False, "", str(e)


def get_file_lines(filename: str) -> int:
    """Return lines of file without loading entire file into memory."""
    with open(filename, "rb") as f:
        # The for _ in f construct implicitly calls f.readline(), and hence counts lines
        return sum(1 for _ in f)


def find_code_section_end(start_line, lines=None) -> int:
    """
    Find the end line of a C function by counting brackets.
    Handles C-style comments and preprocessor directives.
    """

    brace_count = 0
    line_num = start_line - 1  # Convert to 0-based indexing

    while line_num < len(lines):
        line = lines[line_num]
        i = 0

        while i < len(line):
            # Count braces
            if line[i] == "{":
                brace_count += 1
            elif line[i] == "}":
                brace_count -= 1
                if brace_count == 0:
                    return line_num + 1  # Convert back to 1-based indexing
            i += 1

        line_num += 1

    return None  # In case we don't find the end


def code_section_location(function_line, file_content_lines):
    """Return startline and endline for the given function as tuple together with the file lines, or raise Runtime error."""

    if not function_line:
        raise RuntimeError("No function line given to be detected in lines")
    start_line = 1
    log.debug("Searching line '%s' in %d provided lines", function_line, len(file_content_lines))
    for line in file_content_lines:
        if function_line in line:
            break
        start_line += 1
    if start_line > len(file_content_lines):
        raise RuntimeError(
            f"Failed to find function line {function_line}, from {len(file_content_lines)} lines, checked {start_line} lines"
        )
    end_line = find_code_section_end(start_line, file_content_lines)
    if not end_line:
        log.debug(
            "Failed to find function end for line %s, showing all lines after function start (line %d):%s",
            function_line,
            start_line,
            "\n".join(file_content_lines[start_line:]),
        )
        raise RuntimeError(f"Failed to find end of function {function_line}")

    log.debug(
        "Found function line in source file in line %d -- %d (total lines: %d)",
        start_line,
        end_line,
        len(file_content_lines),
    )
    return start_line, end_line, file_content_lines


def warn_on_unsupported_args(git_args):
    """Let user know about used parameters that are not supported."""
    unsupported_git_args = [x for x in git_args if x not in SUPPORTED_GIT_ARGS]
    if unsupported_git_args:
        log.warning(
            "Attempting fuzzy-pick while ignoring given arguments: %r",
            unsupported_git_args,
        )


def normalize_path(git_path: str, repository_root: str) -> str:
    """Return a normalized absolute path of a git_path relative to the git repository root."""

    # Git path has the prefix from the commit output
    if git_path.startswith(("a/", "b/", "i/", "w/", "c/", "o/")):
        git_path = git_path[2:]

    if os.path.isabs(git_path):
        normalized_path = os.path.normpath(git_path)
    else:
        normalized_path = os.path.normpath(os.path.join(repository_root, git_path))

    # Resolve any symbolic links and relative components
    try:
        resolved_path = os.path.realpath(normalized_path)
    except (OSError, ValueError) as e:
        raise RuntimeError(f"Failed to resolve path '{git_path}': {e}") from e

    return resolved_path


def validate_path_within_repository(path: str, repository_root: str) -> bool:
    """Return whether a path is within the repository root path."""
    try:
        normalized_path = normalize_path(path, repository_root)
        repository_root_resolved = os.path.realpath(repository_root)

        return (
            normalized_path.startswith(repository_root_resolved + os.sep) or normalized_path == repository_root_resolved
        )
    except RuntimeError:
        return False


def extract_paths_from_patch(patch_content: str) -> Set[str]:
    """Extract file paths from patch content."""

    paths = set()

    # Patterns to match file paths in patch headers
    patterns = [
        r"^diff --git a/(.+) b/(.+)$",  # diff --git a/file b/file
        r"^--- (.+)$",  # --- a/file or --- file
        r"^\+\+\+ (.+)$",  # +++ b/file or +++ file
        r"^Index: (.+)$",  # Index: file
        r"^rename from (.+)$",  # rename from old_file
        r"^rename to (.+)$",  # rename to new_file
        r"^copy from (.+)$",  # copy from source_file
        r"^copy to (.+)$",  # copy to dest_file
    ]

    for line in patch_content.splitlines():
        for pattern in patterns:
            match = re.match(pattern, line)
            if match:
                # Handle patterns that capture multiple groups (like diff --git)
                for group in match.groups():
                    if group and group != "/dev/null":
                        # Clean up common prefixes and suffixes
                        cleaned_path = group.strip()
                        if cleaned_path.startswith(("a/", "b/")):
                            cleaned_path = cleaned_path[2:]
                        # Remove timestamp suffixes (e.g., "file.c\t2023-01-01 12:00:00")
                        cleaned_path = cleaned_path.split("\t")[0]
                        if cleaned_path:
                            paths.add(cleaned_path)

    log.debug("Extracted %d paths from patch: %s", len(paths), sorted(paths))
    return paths


def get_git_repository_root():
    """Get the absolute path of root directory of the current git repository."""
    success, stdout, _ = run_command(["git", "rev-parse", "--show-toplevel"])
    if not success:
        return None
    return stdout.strip()


def get_invalid_repository_paths(file_paths: List[str], repository_root: str = None) -> List[str]:
    """Return all path that are outside the repository root."""
    repository_root = repository_root or get_git_repository_root()
    if repository_root is None:
        raise RuntimeError("Not in a git repository and no repository root provided")

    # Validate each path
    invalid_paths = []
    for path in file_paths:
        if not validate_path_within_repository(path, repository_root):
            invalid_paths.append(path)
            log.warning("Invalid file path detected: %s", path)

    if invalid_paths:
        log.error("Found %d invalid file paths out of %d total paths", len(invalid_paths), len(file_paths))
    else:
        log.debug("All %d file paths are valid", len(file_paths))
    return invalid_paths


def get_invalid_patch_paths(patch_content: str, repository_root: str = None) -> List[str]:
    """Validate that all paths in a patch are within the repository root."""

    # Extract all paths from the patch
    file_paths = extract_paths_from_patch(patch_content)
    log.debug("Found %d path in patch", len(file_paths))

    return get_invalid_repository_paths(list(file_paths), repository_root)


def string_edit_distance(src: str, dst: str) -> int:
    """Return Levenshtein edit distance between two strings.
    Args:
        src: Source string
        dst: Destination string
    """

    # pylint: disable=E1101
    return Levenshtein.distance(src, dst)
