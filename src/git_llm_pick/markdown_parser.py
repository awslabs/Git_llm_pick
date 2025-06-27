"""
Simpler parser for markdown input
This parser does not perform full parsing, but just extracts sections independently of indentation.
"""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import logging

log = logging.getLogger(__name__)


class MarkdownFlatParser:
    """Parse Markdown, and extract sections."""

    def __init__(self, markdown_input: str, section_marker_prefix: str = "##"):
        """Setup object to allow parsing markdown lazily on first access."""
        self._markdown_input: str = markdown_input
        self._markdown_sections: dict = None
        self._section_marker_prefix = section_marker_prefix

    def get_all_sections(self):
        """Return all sections in the markdown input."""
        self._parse_markdown_flat()
        return self._markdown_sections

    def get_markdown_section(self, section_header: str, strict_match: bool = True):
        """Return the content of a section that matches/contains the given string, or None if not found."""

        self._parse_markdown_flat()

        search_header = section_header.lower()

        if strict_match:
            return self._markdown_sections.get(search_header)

        for header, section_content in self._markdown_sections.items():
            if search_header in header:
                return section_content

        return None

    def _parse_markdown_flat(self):
        """Parse the given markdown input into sections, ignoring the indentation."""

        if self._markdown_sections is not None:
            return

        markdown_lines = self._markdown_input.splitlines()
        self._markdown_sections = {}

        current_section = None
        current_content = []
        in_code_block = False

        line_index = 0
        for line in markdown_lines:
            line_index += 1
            # Check for code block markers
            if line.strip().startswith("```"):
                log.debug("Detected code block flip at line %d", line_index)
                in_code_block = not in_code_block
                if current_section is not None:
                    current_content.append(line)
                continue

            # Process section headers (outside of code blocks only)
            if not in_code_block and line.startswith(self._section_marker_prefix):
                log.debug("Detected new section line %s at line  %d", line, line_index)

                # Save previous section
                if current_section is not None:
                    log.debug("Store section '%s' with %d lines", current_section, len(current_content))
                    self._markdown_sections[current_section] = "\n".join(current_content).strip()

                # Start new section
                current_section = line.split(" ", 1)[1].strip().lower()
                current_content = []
            else:
                # Add line to current section content
                if current_section is not None:
                    current_content.append(line)

        # Save the last section
        if current_section is not None:
            self._markdown_sections[current_section] = "\n".join(current_content).strip()
