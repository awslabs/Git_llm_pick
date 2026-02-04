from linux_kernel_commit_relations.missing_fixes import (
    filter_missing_fixes,
    has_missing_fixes,
)
from linux_kernel_commit_relations.summary_context import SummaryRel


def test_empty_fixes_list_returns_false():
    rel = SummaryRel(stable_depends=[], summary="test_summary", fixed_by=[], commit_hashes={"abc123"})
    carried_summaries = {"carried_fix"}

    result = has_missing_fixes(rel, carried_summaries)
    assert result is False


def test_single_missing_fix_returns_true():
    missing_fix = SummaryRel(stable_depends=[], summary="missing_fix", fixed_by=[], commit_hashes={"def456"})
    rel = SummaryRel(stable_depends=[], summary="test_summary", fixed_by=[missing_fix], commit_hashes={"abc123"})
    carried_summaries = {"carried_fix"}

    result = has_missing_fixes(rel, carried_summaries)
    assert result is True


def test_single_carried_fix_returns_false():
    carried_fix = SummaryRel(stable_depends=[], summary="carried_fix", fixed_by=[], commit_hashes={"def456"})
    rel = SummaryRel(stable_depends=[], summary="test_summary", fixed_by=[carried_fix], commit_hashes={"abc123"})
    carried_summaries = {"carried_fix"}

    result = has_missing_fixes(rel, carried_summaries)
    assert result is False


def test_nested_missing_fix_returns_true():
    nested_missing = SummaryRel(stable_depends=[], summary="nested_missing", fixed_by=[], commit_hashes={"ghi789"})
    carried_fix = SummaryRel(
        stable_depends=[],
        summary="carried_fix",
        fixed_by=[nested_missing],
        commit_hashes={"def456"},
    )
    rel = SummaryRel(stable_depends=[], summary="test_summary", fixed_by=[carried_fix], commit_hashes={"abc123"})
    carried_summaries = {"carried_fix"}

    result = has_missing_fixes(rel, carried_summaries)
    assert result is True


def test_nested_carried_fix_returns_false():
    nested_carried = SummaryRel(stable_depends=[], summary="nested_carried", fixed_by=[], commit_hashes={"ghi789"})
    carried_fix = SummaryRel(
        stable_depends=[],
        summary="carried_fix",
        fixed_by=[nested_carried],
        commit_hashes={"def456"},
    )
    rel = SummaryRel(stable_depends=[], summary="test_summary", fixed_by=[carried_fix], commit_hashes={"abc123"})
    carried_summaries = {"carried_fix", "nested_carried"}

    result = has_missing_fixes(rel, carried_summaries)
    assert result is False


def test_no_fixes_to_drop_returns_original():
    rel = SummaryRel(stable_depends=[], summary="test_summary", fixed_by=[], commit_hashes={"abc123"})
    carried_summaries = {"carried_fix"}

    result = filter_missing_fixes(rel, carried_summaries)
    assert result.summary == "test_summary"
    assert result.fixed_by == []


def test_drop_single_missing_fix():
    carried_fix = SummaryRel(stable_depends=[], summary="carried_fix", fixed_by=[], commit_hashes={"def456"})
    rel = SummaryRel(stable_depends=[], summary="test_summary", fixed_by=[carried_fix], commit_hashes={"abc123"})
    carried_summaries = {"carried_fix"}

    result = filter_missing_fixes(rel, carried_summaries)
    assert len(result.fixed_by) == 0


def test_keep_single_carried_fix():
    missing_fix = SummaryRel(stable_depends=[], summary="missing_fix", fixed_by=[], commit_hashes={"def456"})
    rel = SummaryRel(stable_depends=[], summary="test_summary", fixed_by=[missing_fix], commit_hashes={"abc123"})
    carried_summaries = {"carried_fix"}

    result = filter_missing_fixes(rel, carried_summaries)
    assert len(result.fixed_by) == 1
    assert result.fixed_by[0].summary == "missing_fix"


def test_drop_nested_missing_fixes():
    nested_carried = SummaryRel(stable_depends=[], summary="nested_carried", fixed_by=[], commit_hashes={"ghi789"})
    carried_fix = SummaryRel(
        stable_depends=[],
        summary="carried_fix",
        fixed_by=[nested_carried],
        commit_hashes={"def456"},
    )
    rel = SummaryRel(stable_depends=[], summary="test_summary", fixed_by=[carried_fix], commit_hashes={"abc123"})
    carried_summaries = {"carried_fix", "nested_carried"}

    result = filter_missing_fixes(rel, carried_summaries)
    assert len(result.fixed_by) == 0


def test_mixed_carried_missing_fixes():
    carried_fix = SummaryRel(stable_depends=[], summary="carried_fix", fixed_by=[], commit_hashes={"ghi789"})
    missing_fix = SummaryRel(stable_depends=[], summary="missing_fix", fixed_by=[], commit_hashes={"def456"})
    rel = SummaryRel(
        stable_depends=[],
        summary="test_summary",
        fixed_by=[carried_fix, missing_fix],
        commit_hashes={"abc123"},
    )
    carried_summaries = {"carried_fix"}

    result = filter_missing_fixes(rel, carried_summaries)
    assert len(result.fixed_by) == 1
    assert result.fixed_by[0].summary == "missing_fix"
