"""Tests for utility functions."""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

from git_llm_pick.utils import string_edit_distance


def test_edit_distance_simple():

    assert string_edit_distance("abc", "abc") == 0
    assert string_edit_distance("abc", "ac") == 1
    assert string_edit_distance("abc", "acd") == 2
    assert string_edit_distance("abc", "abcd") == 1
    assert string_edit_distance("abc", "dac") == 2
    assert string_edit_distance("  abc", "  dac") == 2
    assert string_edit_distance("  aaabc", "  aadac") == 2
    assert string_edit_distance("abc", "ABC") == 3
