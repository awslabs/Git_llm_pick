"""Tests for the linux-commit-backporter CLI subcommand structure."""

from unittest.mock import MagicMock, patch

import pytest

from linux_kernel_commit_relations.cli.linux_commit_backporter import (
    _collect_fix_summaries,
    backport_commits,
    main,
    missing_fixups_handler,
)
from linux_kernel_commit_relations.commit_context import CommitRel
from linux_kernel_commit_relations.summary_context import SummaryRel


def test_main_requires_subcommand():
    with pytest.raises(SystemExit):
        with patch("sys.argv", ["linux-commit-backporter"]):
            main()


def test_main_backport_requires_commit_and_target(monkeypatch):
    monkeypatch.setattr("sys.argv", ["prog", "backport"])
    with pytest.raises(SystemExit):
        main()


def test_main_missing_fixups_defaults_branch_b(tmp_path):
    """missing-fixups should accept a single positional arg, defaulting branch_b to HEAD."""
    fake_repo = str(tmp_path / "no_such_repo")
    with patch("sys.argv", ["prog", "missing-fixups", "v6.12.73", "--repo", fake_repo]):
        with pytest.raises(RuntimeError, match="does not exist"):
            main()


def test_main_missing_fixups_repo_not_found(tmp_path):
    fake_repo = str(tmp_path / "no_such_repo")
    with patch("sys.argv", ["prog", "missing-fixups", "v6.12.73", "v6.12.74", "--repo", fake_repo]):
        with pytest.raises(RuntimeError, match="does not exist"):
            main()


def test_main_backport_repo_not_found(tmp_path):
    fake_repo = str(tmp_path / "no_such_repo")
    with patch("sys.argv", ["prog", "backport", "abc123", "--target-kernel-version", "6.12", "--repo", fake_repo]):
        with pytest.raises(RuntimeError, match="does not exist"):
            main()


def test_collect_fix_summaries_single():
    fix = SummaryRel(summary="fix1", stable_depends=[], fixed_by=[], commit_hashes={"aaa"})
    assert _collect_fix_summaries(fix) == [fix]


def test_collect_fix_summaries_nested():
    nested = SummaryRel(summary="nested", stable_depends=[], fixed_by=[], commit_hashes={"bbb"})
    fix = SummaryRel(summary="fix1", stable_depends=[], fixed_by=[nested], commit_hashes={"aaa"})
    result = _collect_fix_summaries(fix)
    assert result == [fix, nested]


def test_collect_fix_summaries_deep():
    deep = SummaryRel(summary="deep", stable_depends=[], fixed_by=[], commit_hashes={"ccc"})
    mid = SummaryRel(summary="mid", stable_depends=[], fixed_by=[deep], commit_hashes={"bbb"})
    top = SummaryRel(summary="top", stable_depends=[], fixed_by=[mid], commit_hashes={"aaa"})
    result = _collect_fix_summaries(top)
    assert [r.summary for r in result] == ["top", "mid", "deep"]


def test_backport_commits_success(tmp_path):
    commit = CommitRel(
        summary="test",
        nearest_commit_hash="abc123",
        mainline_commit_hash="def456",
        stable_depends=[],
        fixed_by=[],
    )
    with patch("linux_kernel_commit_relations.cli.linux_commit_backporter.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = backport_commits([commit], tmp_path, "git cherry-pick {commit}")
    assert result == 0
    mock_run.assert_called_once_with("git cherry-pick abc123", shell=True, cwd=tmp_path, check=False)


def test_backport_commits_failure_stops(tmp_path):
    commits = [
        CommitRel(summary="c1", nearest_commit_hash="aaa", mainline_commit_hash="bbb", stable_depends=[], fixed_by=[]),
        CommitRel(summary="c2", nearest_commit_hash="ccc", mainline_commit_hash="ddd", stable_depends=[], fixed_by=[]),
    ]
    with patch("linux_kernel_commit_relations.cli.linux_commit_backporter.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        result = backport_commits(commits, tmp_path, "git cherry-pick {commit}")
    assert result == 1
    # Should stop after first failure
    assert mock_run.call_count == 1


def test_backport_commits_empty(tmp_path):
    result = backport_commits([], tmp_path, "git cherry-pick {commit}")
    assert result == 0


def test_missing_fixups_no_missing(tmp_path):
    args = MagicMock()
    args.repo = str(tmp_path)
    args.branch_a = "v1"
    args.branch_b = "v2"
    args.dry_run = True

    with patch("linux_kernel_commit_relations.cli.linux_commit_backporter.get_missing_fixes", return_value=[]):
        result = missing_fixups_handler(args)
    assert result == 0


def test_missing_fixups_requires_target_version(tmp_path):
    fix = SummaryRel(summary="fix", stable_depends=[], fixed_by=[], commit_hashes={"fff"})
    mf = SummaryRel(summary="buggy", stable_depends=[], fixed_by=[fix], commit_hashes={"aaa"})

    args = MagicMock()
    args.repo = str(tmp_path)
    args.branch_a = "v1"
    args.branch_b = "v2"
    args.dry_run = False
    args.target_kernel_version = None

    with patch("linux_kernel_commit_relations.cli.linux_commit_backporter.get_missing_fixes", return_value=[mf]):
        result = missing_fixups_handler(args)
    assert result == 1
