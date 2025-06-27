"""Tests for path validation functionality."""

__authors__ = "Norbert Manthey <nmanthey@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import os
import tempfile
from unittest.mock import patch

import pytest

from git_llm_pick.utils import (
    extract_paths_from_patch,
    get_git_repository_root,
    get_invalid_patch_paths,
    get_invalid_repository_paths,
    normalize_path,
    validate_path_within_repository,
)


class TestPathExtraction:
    """Test path extraction from patch content."""

    def test_extract_paths_from_simple_patch(self):
        """Test extracting paths from a simple git patch."""
        patch_content = """diff --git a/src/file1.c b/src/file1.c
index 1234567..abcdefg 100644
--- a/src/file1.c
+++ b/src/file1.c
@@ -1,3 +1,4 @@
 #include <stdio.h>
+#include <stdlib.h>

 int main() {
"""
        paths = extract_paths_from_patch(patch_content)
        assert paths == {"src/file1.c"}

    def test_extract_paths_from_multi_file_patch(self):
        """Test extracting paths from a patch with multiple files."""
        patch_content = """diff --git a/src/file1.c b/src/file1.c
index 1234567..abcdefg 100644
--- a/src/file1.c
+++ b/src/file1.c
@@ -1,3 +1,4 @@
 #include <stdio.h>
+#include <stdlib.h>
diff --git a/include/header.h b/include/header.h
index 9876543..fedcba9 100644
--- a/include/header.h
+++ b/include/header.h
@@ -1,2 +1,3 @@
 #ifndef HEADER_H
 #define HEADER_H
+void new_function();
"""
        paths = extract_paths_from_patch(patch_content)
        assert paths == {"src/file1.c", "include/header.h"}

    def test_extract_paths_with_rename(self):
        """Test extracting paths from a patch with file renames."""
        patch_content = """diff --git a/old_file.c b/new_file.c
similarity index 95%
rename from old_file.c
rename to new_file.c
index 1234567..abcdefg 100644
--- a/old_file.c
+++ b/new_file.c
@@ -1,3 +1,4 @@
 #include <stdio.h>
+#include <stdlib.h>
"""
        paths = extract_paths_from_patch(patch_content)
        assert "old_file.c" in paths
        assert "new_file.c" in paths

    def test_extract_paths_ignores_dev_null(self):
        """Test that /dev/null paths are ignored."""
        patch_content = """diff --git a/new_file.c b/new_file.c
new file mode 100644
index 0000000..1234567
--- /dev/null
+++ b/new_file.c
@@ -0,0 +1,3 @@
+#include <stdio.h>
+
+int main() {
"""
        paths = extract_paths_from_patch(patch_content)
        assert paths == {"new_file.c"}
        assert "/dev/null" not in paths


class TestPathNormalization:
    """Test path normalization functionality."""

    def test_normalize_relative_path(self):
        """Test normalizing a relative path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            normalized = normalize_path("src/file.c", tmpdir)
            expected = os.path.join(tmpdir, "src", "file.c")
            assert normalized == os.path.normpath(expected)

    def test_normalize_absolute_path(self):
        """Test normalizing an absolute path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            abs_path = os.path.join(tmpdir, "src", "file.c")
            normalized = normalize_path(abs_path, tmpdir)
            assert normalized == os.path.normpath(abs_path)

    def test_normalize_path_with_git_prefix(self):
        """Test normalizing paths with git prefixes (a/, b/, etc.)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            normalized = normalize_path("a/src/file.c", tmpdir)
            expected = os.path.join(tmpdir, "src", "file.c")
            assert normalized == os.path.normpath(expected)

    def test_normalize_path_with_traversal_attempt(self):
        """Test that path traversal attempts are normalized but detected by validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # The normalize_path function doesn't raise an error - it just normalizes
            # The validation happens in validate_path_within_repository
            normalized = normalize_path("../../../etc/passwd", tmpdir)

            # The normalized path should exist but point outside the temp directory
            assert not validate_path_within_repository(normalized, tmpdir)


class TestPathValidation:
    """Test path validation within repository boundaries."""

    def test_validate_path_within_repository(self):
        """Test validating a path within the repository."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            test_file = os.path.join(tmpdir, "test.c")
            with open(test_file, "w") as f:
                f.write("// test file\n")

            assert validate_path_within_repository("test.c", tmpdir)
            assert validate_path_within_repository("./test.c", tmpdir)

    def test_validate_path_outside_repository(self):
        """Test that paths outside repository are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Try to access a path outside the temp directory
            assert not validate_path_within_repository("/etc/passwd", tmpdir)
            assert not validate_path_within_repository("../outside.c", tmpdir)

    def test_validate_path_with_symlink_escape(self):
        """Test that symlink escape attempts are detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a symlink that points outside the directory
            outside_dir = tempfile.mkdtemp()
            try:
                symlink_path = os.path.join(tmpdir, "escape_link")
                os.symlink(outside_dir, symlink_path)

                # The symlink itself should be considered invalid if it points outside
                assert not validate_path_within_repository("escape_link/file.c", tmpdir)
            finally:
                os.rmdir(outside_dir)


class TestFileListValidation:
    """Test validation of file lists."""

    def test_validate_empty_file_list(self):
        """Test validating an empty file list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            invalid_paths = get_invalid_repository_paths([], tmpdir)
            assert invalid_paths == []

    def test_validate_valid_file_list(self):
        """Test validating a list of valid files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            test_files = ["file1.c", "src/file2.c", "include/header.h"]
            for file_path in test_files:
                full_path = os.path.join(tmpdir, file_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w") as f:
                    f.write("// test\n")

            invalid_paths = get_invalid_repository_paths(test_files, tmpdir)
            assert invalid_paths == []

    def test_validate_mixed_file_list(self):
        """Test validating a list with both valid and invalid files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create one valid file
            valid_file = "valid.c"
            with open(os.path.join(tmpdir, valid_file), "w") as f:
                f.write("// valid\n")

            file_list = [valid_file, "../invalid.c", "/etc/passwd"]
            invalid_paths = get_invalid_repository_paths(file_list, tmpdir)

            assert len(invalid_paths) == 2
            assert "../invalid.c" in invalid_paths
            assert "/etc/passwd" in invalid_paths


class TestPatchValidation:
    """Test validation of entire patches."""

    def test_validate_safe_patch(self):
        """Test validating a patch with safe file paths."""
        patch_content = """diff --git a/src/file1.c b/src/file1.c
index 1234567..abcdefg 100644
--- a/src/file1.c
+++ b/src/file1.c
@@ -1,3 +1,4 @@
 #include <stdio.h>
+#include <stdlib.h>
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create the file referenced in the patch
            os.makedirs(os.path.join(tmpdir, "src"))
            with open(os.path.join(tmpdir, "src", "file1.c"), "w") as f:
                f.write("#include <stdio.h>\n")

            invalid_paths = get_invalid_patch_paths(patch_content, tmpdir)
            assert invalid_paths == []

    def test_validate_malicious_patch(self):
        """Test validating a patch with malicious file paths."""
        malicious_patch = """diff --git a/../../../etc/passwd b/../../../etc/passwd
index 1234567..abcdefg 100644
--- a/../../../etc/passwd
+++ b/../../../etc/passwd
@@ -1,3 +1,4 @@
 root:x:0:0:root:/root:/bin/bash
+malicious:x:0:0:hacker:/root:/bin/bash
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            invalid_paths = get_invalid_patch_paths(malicious_patch, tmpdir)
            assert len(invalid_paths) > 0
            assert any("etc/passwd" in path for path in invalid_paths)

    @patch("git_llm_pick.utils.get_git_repository_root")
    def test_validate_patch_without_repo_root(self, mock_get_repo_root):
        """Test patch validation when not in a git repository."""
        mock_get_repo_root.return_value = None

        patch_content = """diff --git a/file.c b/file.c
--- a/file.c
+++ b/file.c
"""
        with pytest.raises(RuntimeError, match="Not in a git repository"):
            get_invalid_patch_paths(patch_content)


class TestGitRepositoryRoot:
    """Test git repository root detection."""

    @patch("git_llm_pick.utils.run_command")
    def test_get_git_repository_root_success(self, mock_run_command):
        """Test successful git repository root detection."""
        mock_run_command.return_value = (True, "/path/to/repo", "")

        root = get_git_repository_root()
        assert root == "/path/to/repo"
        mock_run_command.assert_called_once_with(["git", "rev-parse", "--show-toplevel"])

    @patch("git_llm_pick.utils.run_command")
    def test_get_git_repository_root_failure(self, mock_run_command):
        """Test git repository root detection failure."""
        mock_run_command.return_value = (False, "", "not a git repository")

        root = get_git_repository_root()
        assert root is None
