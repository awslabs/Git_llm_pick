"""Tests for markdown parser functionality."""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

from git_llm_pick.markdown_parser import MarkdownFlatParser


def test_markdown_parser_basic_sections():
    """Test basic section parsing."""
    markdown_content = """# First Section
This is the first section content.

# Second Section
This is the second section content.
With multiple lines.

## Subsection
This is a subsection.
"""

    parser = MarkdownFlatParser(markdown_content, section_marker_prefix="#")

    assert parser.get_markdown_section("first section") == "This is the first section content."
    assert parser.get_markdown_section("second section") == "This is the second section content.\nWith multiple lines."
    assert parser.get_markdown_section("subsection") == "This is a subsection."


def test_markdown_parser_code_blocks():
    """Test that headers inside code blocks are ignored."""
    markdown_content = """# Main Section
This section has code:

```python
# This is not a header
def function():
    # Another comment that looks like header
    pass
```

More content after code block.

# Real Header
This is a real section.
"""

    parser = MarkdownFlatParser(markdown_content, section_marker_prefix="#")

    main_content = parser.get_markdown_section("main section")
    assert "```python" in main_content
    assert "# This is not a header" in main_content
    assert "More content after code block." in main_content

    assert "main section" in parser.get_all_sections()
    assert parser.get_markdown_section("real header") == "This is a real section."
    assert parser.get_markdown_section("this is not a header") is None


def test_markdown_parser_strict_vs_fuzzy_match():
    """Test strict vs fuzzy matching."""
    markdown_content = """# Configuration Settings
Content here.

# Advanced Configuration
More content.
"""

    parser = MarkdownFlatParser(markdown_content, section_marker_prefix="#")

    # Strict match
    assert parser.get_markdown_section("configuration settings", strict_match=True) == "Content here."
    assert parser.get_markdown_section("configuration", strict_match=True) is None

    # Fuzzy match
    assert parser.get_markdown_section("configuration", strict_match=False) == "Content here."
    assert parser.get_markdown_section("advanced", strict_match=False) == "More content."


def test_markdown_parser_empty_sections():
    """Test handling of empty sections."""
    markdown_content = """# Empty Section

# Section With Content
Some content here.

# Another Empty

# Final Section
Final content.
"""

    parser = MarkdownFlatParser(markdown_content, section_marker_prefix="#")

    assert parser.get_markdown_section("empty section") == ""
    assert parser.get_markdown_section("section with content") == "Some content here."
    assert parser.get_markdown_section("another empty") == ""
    assert parser.get_markdown_section("final section") == "Final content."


def test_parsing_patching_answer():

    answer = """### EXPLANATION

The provided hunk aims to add a check for division by zero in the `divide` function. This is a common safeguard to prevent runtime errors when attempting to divide a number by zero. The hunk introduces a conditional statement that checks if the divisor is zero. If it is, the function prints an error message and returns zero instead of performing the division.

The source code section shows the original `divide` function without the division by zero check. The destination code section is not provided, but we infer that it is similar to the source code section since the hunk is intended to be applied to it.

To apply the hunk, we need to insert the new lines into the `divide` function in the destination code. The line numbers in the hunk suggest that the new lines should be inserted after the function signature.

### CHANGE SUMMARY

- Added a check for division by zero in the `divide` function.
- If the divisor is zero, print an error message and return zero.
- Otherwise, perform the division as usual.

### ADAPTED CODE SNIPPET

```c
   14  }
   15
   16  // Function to multiply two integers
   17  int multiply(int a, int b) {
   18      return a * b;
   19  }
   20
   21  // Function to divide two integers
   22  float divide(int a, int b) {
   23      if (b == 0) {
   24          printf("Error: Division by zero\n");
   25          return 0;
   26      }
   27      return (float)a / b;
   28  }
   29
   30  int main() {
   31      int x = 10;
   32      int y = 5;
   33
   34      printf("Testing basic arithmetic operations:\n");
   35      printf("x = %d, y = %d\n", x, y);
```

In this adapted code snippet, the division by zero check has been successfully integrated into the `divide` function. The function now safely handles the case where the divisor is zero, preventing potential runtime errors.
"""

    parser = MarkdownFlatParser(answer)

    sections = parser.get_all_sections()
    assert "explanation" in sections
    assert "change summary" in sections
    assert "adapted code snippet" in sections


def test_markdown_parser_asterisk_prefix():
    """Test basic section parsing."""
    markdown_content = """* First Section
This is the first section content.

* Second Section
This is the second section content.
With multiple lines.

** Subsection
This is a subsection.
"""

    parser = MarkdownFlatParser(markdown_content, section_marker_prefix="*")

    assert parser.get_markdown_section("first section") == "This is the first section content."
    assert parser.get_markdown_section("second section") == "This is the second section content.\nWith multiple lines."
    assert parser.get_markdown_section("subsection") == "This is a subsection."
