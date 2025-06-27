"""Tests for patch matching functionality."""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import Mock

from git_llm_pick.patch_matching import find_section_header_of_matching_hunk


def test_find_section_header_of_matching_hunk_success():
    """Test successful retrieval of section header from matching hunk."""
    # Create rejected hunk without section header
    rejected_hunk = Mock()
    rejected_hunk.source_start = 10
    rejected_hunk.section_header = None
    rejected_line = "int main() {"
    rejected_hunk.source = [rejected_line]

    # Create original hunk with section header
    original_hunk = Mock()
    original_hunk.source_start = 12
    original_hunk.section_header = "int main()"
    original_line = "int main() {"
    original_hunk.source = [original_line]

    original_hunks = [original_hunk]

    result = find_section_header_of_matching_hunk(rejected_hunk, original_hunks)

    assert result == "int main()"


def test_find_section_header_of_matching_hunk_no_match():
    """Test that no section header is returned when no matching hunk is found."""
    # Create rejected hunk
    rejected_hunk = Mock()
    rejected_hunk.source_start = 10
    rejected_line = Mock()
    rejected_line.value = "void func1() {"
    rejected_hunk.source = [rejected_line]

    # Create original hunk with different content
    original_hunk = Mock()
    original_hunk.source_start = 50
    original_hunk.section_header = "void func2()"
    original_line = Mock()
    original_line.value = "void func2() {"
    original_hunk.source = [original_line]

    original_hunks = [original_hunk]

    result = find_section_header_of_matching_hunk(rejected_hunk, original_hunks)

    assert result is None


def test_find_section_header_of_matching_hunk_empty_list():
    """Test that None is returned when original hunks list is empty."""
    rejected_hunk = Mock()
    rejected_hunk.source_start = 10

    result = find_section_header_of_matching_hunk(rejected_hunk, [])

    assert result is None


def test_find_section_header_of_matching_hunk_no_section_header():
    """Test that hunks without section headers are skipped."""
    rejected_hunk = Mock()
    rejected_hunk.source_start = 10

    # Original hunk without section header
    original_hunk = Mock()
    original_hunk.source_start = 10
    original_hunk.section_header = None

    original_hunks = [original_hunk]

    result = find_section_header_of_matching_hunk(rejected_hunk, original_hunks)

    assert result is None


def test_find_section_header_of_matching_hunk_line_offset_too_large():
    """Test that hunks with large line number differences are not matched."""
    rejected_hunk = Mock()
    rejected_hunk.source_start = 10

    # Original hunk with line offset > 100
    original_hunk = Mock()
    original_hunk.source_start = 150
    original_hunk.section_header = "int main()"

    original_hunks = [original_hunk]

    result = find_section_header_of_matching_hunk(rejected_hunk, original_hunks)

    assert result is None


def test_find_section_header_of_matching_hunk_low_similarity():
    """Test that hunks with low content similarity are not matched."""
    rejected_hunk = Mock()
    rejected_hunk.source_start = 10
    rejected_lines = [Mock(), Mock(), Mock()]
    rejected_lines[0].value = "int main() {"
    rejected_lines[1].value = '    printf("Hello");'
    rejected_lines[2].value = "    return 0;"
    rejected_hunk.source = rejected_lines

    # Original hunk with completely different content
    original_hunk = Mock()
    original_hunk.source_start = 12
    original_hunk.section_header = "int main()"
    original_lines = [Mock(), Mock(), Mock()]
    original_lines[0].value = "void different() {"
    original_lines[1].value = "    exit(1);"
    original_lines[2].value = "    abort();"
    original_hunk.source = original_lines

    original_hunks = [original_hunk]

    result = find_section_header_of_matching_hunk(rejected_hunk, original_hunks)

    assert result is None
