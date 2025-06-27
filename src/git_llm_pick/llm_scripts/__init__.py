"""
Module to store and retrieve templates for LLM queries.

The below constants are used in the templates, and should be replaced before querying:

    {COMMIT_MESSAGE} .......... string of commit message of the change to move
    {REJECTED_HUNK_CONTENT} ... content of the hunk that should be applied
    {SOURCE_FILE_NAME} ........ path of the file to be changed
    {DESTINATION_FUNCTION} .... function where the patch should be applied
    {SOURCE_FUNCTION} ......... function where the patch applies successfully
    {PROMPT_NONCE} ............ random string to indicate unique query
"""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import logging
import os
from functools import lru_cache

log = logging.getLogger(__name__)

MODULE_PATH = os.path.dirname(os.path.realpath(__file__))

# Sections the templates ask the LLM to have in the output explicitly
ADAPTED_SNIPPET_HEADER = "ADAPTED CODE SNIPPET"
SUMMARY_SECTION_HEADER = "CHANGE SUMMARY"


@lru_cache(maxsize=None)
def get_hunk_patching_template() -> str:
    """Return content of hunk patching template as text."""
    template_path = os.path.join(MODULE_PATH, "hunk_patching.md")
    with open(template_path, "r", encoding="utf-8") as template_file:
        template_text = template_file.read()
    return template_text


@lru_cache(maxsize=None)
def get_section_patching_template() -> str:
    """Return content of section patching template as text."""
    template_path = os.path.join(MODULE_PATH, "section_patching.md")
    with open(template_path, "r", encoding="utf-8") as template_file:
        template_text = template_file.read()
    return template_text
