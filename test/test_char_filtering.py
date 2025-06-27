"""Test filtering input to LLMs."""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0


from git_llm_pick.llm_patching import validate_extracted_llm_content


def test_validate_extracted_llm_content():
    # Test empty string input
    assert validate_extracted_llm_content("", "code")

    # Test None input
    assert validate_extracted_llm_content(None, "code")

    # Test valid code content
    assert validate_extracted_llm_content("def test(): pass", "code")

    # Test code with special characters
    assert validate_extracted_llm_content("def test():\n    print('Hello!')", "code")

    # Test code with comments
    assert validate_extracted_llm_content("# This is a comment\ndef test(): pass", "code")

    # Test code with multiple lines
    assert validate_extracted_llm_content(
        """
        def test():
            x = 1
            y = 2
            return x + y
    """,
        "code",
    )

    # Test code with leading/trailing whitespace
    assert validate_extracted_llm_content("   def test(): pass   ", "code")

    # Test empty code block
    assert validate_extracted_llm_content("```\n```", "code")


def test_validate_extracted_llm_content_excluded_chars():
    # Test content with control characters that should be excluded
    assert not validate_extracted_llm_content("\x00def test(): pass", "code")
    assert not validate_extracted_llm_content("\x1bdef test(): pass", "code")
    assert not validate_extracted_llm_content("\x7fdef test(): pass", "code")

    # Test content with unicode control characters
    assert not validate_extracted_llm_content("\u2028def test(): pass", "code")
    assert not validate_extracted_llm_content("\u2029def test(): pass", "code")

    # Test content with null bytes
    assert not validate_extracted_llm_content("def test()\x00: pass", "code")

    # Test content with escape sequences
    assert not validate_extracted_llm_content("\033[31mdef test(): pass", "code")
    assert not validate_extracted_llm_content("\033[0mdef test(): pass", "code")
