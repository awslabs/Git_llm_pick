#!/usr/bin/env python3

"""
Summary-level commit relationship analysis for Linux kernel repositories.

This module groups commits by their summary (first line of commit message) and
analyzes relationships at the summary level.
"""

__authors__ = "Ömer Erdinç Yağmurlu <oeygmrl@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass

from linux_kernel_commit_relations.relations import LinuxRelations


@dataclass(repr=False)
class SummaryRel:
    stable_depends: list["SummaryRel"]
    summary: str
    fixed_by: list["SummaryRel"]
    commit_hashes: set[str]

    def flatten(self) -> list["SummaryRel"]:
        return (
            [item for s in self.stable_depends for item in s.flatten()]
            + [
                SummaryRel(
                    stable_depends=[],
                    summary=self.summary,
                    fixed_by=[],
                    commit_hashes=self.commit_hashes,
                )
            ]
            + [item for s in self.fixed_by for item in s.flatten()]
        )

    def __str__(self):
        return self._tostring(0)

    def __repr__(self):
        return "SummaryRel:\n" + self._tostring(1)

    def serialize(self) -> dict:
        return {
            "stable_depends": [s.serialize() for s in self.stable_depends],
            "summary": self.summary,
            "fixed_by": [s.serialize() for s in self.fixed_by],
            "commit_hashes": list(self.commit_hashes),
        }

    def _tostring(self, level: int) -> str:
        # pylint: disable=protected-access
        out = []
        space = "  " * level

        out.append(f'{space}{",".join(self.commit_hashes)} ("{self.summary}")')

        if self.stable_depends:
            out.append(f"{space}stable depends:")
            for s in self.stable_depends:
                out.append(s._tostring(level + 1))

        if self.fixed_by:
            out.append(f"{space}fixed by:")
            for s in self.fixed_by:
                out.append(s._tostring(level + 1))

        return "\n".join(out)


def get_summary_context(summary: str, relations: LinuxRelations, depth: int = 0, max_depth: int = 10) -> SummaryRel:
    """
    Build a hierarchical view of commit relationships for a given summary.

    Finds all commits that are stable dependencies or fixes for commits with the
    given summary, then recursively builds the same context for those related
    commits, including their upstream commits.

    Returns empty SummaryRel if the max_depth is met to prevent
    infinite loops, e.g. when commits create a circular dependency structure.

    Args:
        summary: The summary to create the SummaryRel for

        relations: The object to use for dependency lookups depth: The current
            recursion depth (default: 0)

        depth: Recursion depth, used to prevent infinite recursion

        max_depth: Maximum recursion depth (default: MAX_RECURSION_DEPTH)

    Returns:
        SummaryRel: An object containing the fixed_by and stable_depends
            relations for the given summary
    """
    if summary not in relations.summaries or depth > max_depth:
        return SummaryRel(
            stable_depends=[],
            summary=summary,
            fixed_by=[],
            commit_hashes=set(),
        )

    sisters = relations.summaries[summary]
    for c_hash in list(sisters):
        sisters |= relations.with_ancestors(c_hash)

    dep_commits = set()
    for c_hash in sisters:
        for c_sd_hash in relations.stable_depends.get(c_hash, set()):
            dep_commits |= relations.with_ancestors(c_sd_hash)
    stable_depends = []
    for dep_s in {relations.summary_by_hash[commit] for commit in dep_commits if commit in relations.summary_by_hash}:
        stable_depends.append(get_summary_context(dep_s, relations, depth + 1, max_depth))

    fix_commits = set()
    for c_hash in sisters:
        for c_fx_hash in relations.fixed_by.get(c_hash, set()):
            fix_commits |= relations.with_ancestors(c_fx_hash)
    fixed_by = []
    for fix_s in {relations.summary_by_hash[commit] for commit in fix_commits if commit in relations.summary_by_hash}:
        fixed_by.append(get_summary_context(fix_s, relations, depth + 1, max_depth))

    commit_hashes = relations.summaries[summary]

    return SummaryRel(
        stable_depends=stable_depends,
        summary=summary,
        fixed_by=fixed_by,
        commit_hashes=commit_hashes,
    )
