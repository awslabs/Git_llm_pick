"""Git_llm_pick module."""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0


LLM_ADJUST_EXTRA_CONTEXT_LINES = 10  # When presenting hunks to the LLM, add this amount of lines
MAX_ADJUST_SECTION_LENGTH_DIFFERENCE = 50  # Only allow new functions if their length is not more than 50 lines
NO_SECTION_HUNK_EXTRA_CONTEXT = 5  # When patching hunk without section, use this amount of context lines
SUPPORTED_GIT_ARGS = set(["-x", "-n", "--no-commit"])  # Cherry-pick parameters the script handles
