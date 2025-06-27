"""Tests for LLMs scripts module."""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

from git_llm_pick.llm_scripts import get_hunk_patching_template, get_section_patching_template


def test_templates_available():
    """Test whether we can open the templates."""

    hunk_template = get_hunk_patching_template()
    assert hunk_template, "Hunk template cannot be empty"

    section_template = get_section_patching_template()
    assert section_template, "Section template cannot be empty"
