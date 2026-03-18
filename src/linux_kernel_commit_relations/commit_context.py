#!/usr/bin/env python3

"""
Commit context analysis for Linux kernel repositories.

Provides tools to analyze commit relationships with version tag awareness,
tracking stable dependencies and fixes across different kernel versions.

This module builds on summary-level relationships (from summary_context.py) and
adds version awareness by selecting appropriate commits based on kernel version tags.
"""

__authors__ = "Ömer Erdinç Yağmurlu <oeygmrl@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import functools
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Union

import pydantic
from tqdm import tqdm

from linux_kernel_commit_relations.relations import HASH_LEN, LinuxRelations
from linux_kernel_commit_relations.summary_context import SummaryRel, get_summary_context

TAG_PATTERN = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?(?:-rc(\d+))?")
MAINLINE_TAG_PATTERN = re.compile(r"v?\d+\.\d+(?:\.\d+)?(?:-rc\d+)?$")


@functools.total_ordering
@pydantic.dataclasses.dataclass
class LinuxTag:
    """Represents a Linux kernel version tag with semantic version parsing."""

    tag: str
    major: int = 0
    minor: int = 0
    patch: int = 0
    rc: int = 0

    def __post_init__(self):
        match = TAG_PATTERN.match(self.tag)
        if match:
            self.major = int(match.group(1))
            self.minor = int(match.group(2)) if match.group(2) else 0
            self.patch = int(match.group(3)) if match.group(3) else 0
            self.rc = int(match.group(4)) if match.group(4) else 0

    def __str__(self):
        return self.tag

    def __repr__(self):
        return f"LinuxTag('{self.tag}')"

    def __lt__(self, other):
        return (self.major, self.minor, self.rc, self.patch) < (
            other.major,
            other.minor,
            other.rc,
            other.patch,
        )

    def __eq__(self, other):
        return (self.major, self.minor, self.rc, self.patch) == (
            other.major,
            other.minor,
            other.rc,
            other.patch,
        )

    @staticmethod
    def is_mainline(tag: str) -> bool:
        """Check if tag is a mainline release (including RC tags)."""
        return bool(MAINLINE_TAG_PATTERN.match(tag))


class CommitRel(pydantic.BaseModel):
    """Represents commit relationships including stable dependencies and fixes.

    Attributes:
        stable_depends: List of commits this commit depends on (marked with `Stable-dep-of:` tag)
        summary: The commit message summary (first line)
        nearest_commit_hash: Hash of the commit closest to the target kernel version
        mainline_commit_hash: Hash of the commit in the mainline kernel tree
        fixed_by: List of commits that fix bugs in this commit (marked with `Fixes:` tag)

    Example:
        A commit C that fixes bug in commit B, which depends on commit A:
        CommitRel(
            summary="Fix memory leak in driver",
            nearest_commit_hash="abc123",
            mainline_commit_hash="def456",
            stable_depends=[CommitRel(summary="Add driver support", ...)],
            fixed_by=[]
        )
    """

    stable_depends: list["CommitRel"]
    summary: str
    nearest_commit_hash: str
    mainline_commit_hash: str
    fixed_by: list["CommitRel"]

    def flatten(self) -> list["CommitRel"]:
        """Flatten the tree structure into a list of commits."""
        return (
            [item for s in self.stable_depends for item in s.flatten()]
            + [
                CommitRel(
                    stable_depends=[],
                    summary=self.summary,
                    nearest_commit_hash=self.nearest_commit_hash,
                    mainline_commit_hash=self.mainline_commit_hash,
                    fixed_by=[],
                )
            ]
            + [item for s in self.fixed_by for item in s.flatten()]
        )

    def __str__(self):
        return self._tostring(0)

    def __repr__(self):
        return "CommitRel:\n" + self._tostring(1)

    def _tostring(self, level: int) -> str:
        # pylint: disable=protected-access

        out = []
        space = "  " * level
        out.append(
            f'{space}[nearest:{self.nearest_commit_hash}] [mainline:{self.mainline_commit_hash}] ("{self.summary}")'
        )

        if self.stable_depends:
            out.append(f"{space}stable depends:")
            for s in self.stable_depends:
                out.append(s._tostring(level + 1))

        if self.fixed_by:
            out.append(f"{space}fixed by:")
            for s in self.fixed_by:
                out.append(s._tostring(level + 1))

        return "\n".join(out)


def get_mainline_tags(commit: str, repo_path: Path) -> list[LinuxTag]:
    """Get all mainline tags that contain the given commit."""
    result = subprocess.run(
        ["git", "tag", "--contains", commit], capture_output=True, text=True, cwd=repo_path, check=True
    )
    tags = result.stdout.split("\n")
    return [LinuxTag(tag) for tag in tags if LinuxTag.is_mainline(tag)]


def get_commit_context(
    commit_hash: str,
    relations: LinuxRelations,
    repo_path: Path,
    target: Union[LinuxTag, None] = None,
    pbar: bool = False,
    max_depth: int = 10,
) -> CommitRel:
    """Get commit context with stable dependencies and fixes.

    Analyzes a commit and recursively finds all related commits through `Stable-dep-of:`
    and `Fixes:` tags. For each related commit, selects the most appropriate version
    based on the target kernel version.

    Args:
        commit_hash: The commit hash to analyze
        relations: LinuxRelations object containing parsed commit relationships
        repo_path: Path to the Linux kernel git repository
        target: Target kernel version (e.g., LinuxTag("4.14")). Used to select the
                oldest commit version that is >= target. If None, uses the oldest available version.
        pbar: Whether to show a progress bar
        max_depth: Maximum recursion depth for dependency analysis (default: 10)

    Returns:
        CommitRel object with the commit and all its dependencies and fixes

    Raises:
        ValueError: If the commit is not found in the repository
    """

    commit_hash = commit_hash[:HASH_LEN]

    if commit_hash not in relations.summary_by_hash:
        raise ValueError(f"Commit {commit_hash} not found in linux.git")

    summary_context = get_summary_context(relations.summary_by_hash[commit_hash], relations, max_depth=max_depth)
    pbar_obj = (
        tqdm(total=1, desc="Converting summary relations to commit relations", disable=not pbar) if pbar else None
    )
    result = _summary_to_commit_rel(summary_context, relations, repo_path, target, pbar_obj)
    if pbar_obj:
        pbar_obj.close()
    return result


def _summary_to_commit_rel(
    summary_rel: SummaryRel,
    relations: LinuxRelations,
    repo_path: Path,
    target: Union[LinuxTag, None] = None,
    pbar_obj: Union[tqdm, None] = None,
) -> CommitRel:
    """Convert a SummaryRel to CommitRel with version-aware commit selection.

    For commits with the same summary across different kernel versions, selects:
    - mainline_commit_hash: The latest mainline version
    - nearest_commit_hash: The oldest version >= target (or oldest if no target)

    This ensures backporting uses commits appropriate for the target kernel version.

    Args:
        summary_rel: Summary-level relationship to convert
        relations: LinuxRelations object for lookups
        repo_path: Path to git repository for tag queries
        target: Target kernel version for commit selection
        pbar_obj: Optional tqdm progress bar object

    Returns:
        CommitRel with selected commit hashes and recursively converted dependencies

    Raises:
        ValueError: If no tagged commits are found for the summary
    """
    if pbar_obj:
        pbar_obj.update(1)

    commits = list(relations.summaries[summary_rel.summary])
    _max_workers = min(int(os.environ.get("LBT_MAX_JOBS", 2)), len(commits))
    with ThreadPoolExecutor(max_workers=_max_workers) as pool:
        tag_results = list(pool.map(lambda c: get_mainline_tags(c, repo_path), commits))
    tagged_commits: list[tuple[LinuxTag, str]] = []
    for commit, mainline_tags in zip(commits, tag_results):
        if mainline_tags:
            tagged_commits.append((min(mainline_tags), commit))
    tagged_commits.sort()

    if not tagged_commits:
        raise ValueError(
            f"No tagged commits found for summary: {summary_rel.summary}. Tagged commits: {tagged_commits}"
        )

    mainline = tagged_commits[-1][1]
    if not target:
        nearest = tagged_commits[0][1]
    else:
        nearest = tagged_commits[-1][1]
        for tag, commit in tagged_commits:
            if tag >= target:  # type: ignore[operator]
                nearest = commit
                break

    if pbar_obj:
        pbar_obj.total = (pbar_obj.total or 0) + len(summary_rel.stable_depends) + len(summary_rel.fixed_by)
        pbar_obj.refresh()

    return CommitRel(
        stable_depends=[
            _summary_to_commit_rel(dep, relations, repo_path, target, pbar_obj) for dep in summary_rel.stable_depends
        ],
        summary=summary_rel.summary,
        nearest_commit_hash=nearest,
        mainline_commit_hash=mainline,
        fixed_by=[_summary_to_commit_rel(fix, relations, repo_path, target, pbar_obj) for fix in summary_rel.fixed_by],
    )
