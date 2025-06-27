"""Tests for hunk matching functionality."""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

from git_llm_pick.patch_matching import parse_commit_hunks


def test_parse_commit_hunks(monkeypatch):
    # Mock the run_command function
    # pylint: disable=W0613
    def mock_run_command(cmd):
        return (True, git_show_output, "")

    monkeypatch.setattr("git_llm_pick.patch_matching.run_command", mock_run_command)

    # Sample git show output with multiple files and hunks
    git_show_output = """
diff --git a/dir1/file1.txt b/dir1/file1.txt
index abc123..def456 100644
--- a/dir1/file1.txt
+++ b/dir1/file1.txt
@@ -1,3 +1,4 @@
+New line
 Line 1
 Line 2
 Line 3
diff --git a/path/to/file2.py b/path/to/file2.py
index 789abc..def123 100644
--- a/path/to/file2.py
+++ b/path/to/file2.py
@@ -8,4 +8,5 @@ def return_true_function():
      # Nothing
      # Else

+     # Nothing else
      return True
 """

    # Test successful parsing
    commit_id = "abc123"
    result = parse_commit_hunks(commit_id)

    # Verify the results
    assert result is not None
    assert len(result) == 2
    assert "dir1/file1.txt" in result
    assert "path/to/file2.py" in result
    assert len(result["dir1/file1.txt"]) == 1  # One hunk
    assert len(result["path/to/file2.py"]) == 1  # One hunk

    # Test failure case
    # pylint: disable=W0613
    def mock_run_command_fail(cmd):
        return (False, "", "error")

    monkeypatch.setattr("git_llm_pick.patch_matching.run_command", mock_run_command_fail)
    result = parse_commit_hunks(commit_id)
    assert result is None
