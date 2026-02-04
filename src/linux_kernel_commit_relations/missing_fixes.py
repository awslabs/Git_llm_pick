#!/usr/bin/env python3

"""
Identify missing fixes in Linux kernel branches.

This module provides functionality to detect commits that have missing fixes
when comparing different kernel branches or versions. It recursively analyzes
fix relationships to ensure all necessary fixes are carried forward.
"""

__authors__ = "Simon Liebold <simonlie@amazon.de>, Ömer Erdinç Yağmurlu <oeygmrl@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import logging
from pathlib import Path
from typing import Union

from linux_kernel_commit_relations.relations import LinuxRelations
from linux_kernel_commit_relations.summary_context import SummaryRel, get_summary_context

logger = logging.getLogger(__name__)

MAINLINE_MASTER = "origin/master"


def has_missing_fixes(rel: SummaryRel, carried_summaries: set[str]) -> bool:
    """Check if a SummaryRel has any missing fixes recursively."""
    for fix in rel.fixed_by:
        if fix.summary not in carried_summaries:
            return True
        if has_missing_fixes(fix, carried_summaries):
            return True
    return False


def filter_missing_fixes(rel: SummaryRel, carried_summaries: set[str]) -> SummaryRel:
    """Drop carried fixes from a SummaryRel object recursively."""
    filtered_fixed_by: list[SummaryRel] = []
    for fix in rel.fixed_by:
        if fix.summary not in carried_summaries:
            filtered_fixed_by.append(filter_missing_fixes(fix, carried_summaries))

    return SummaryRel(
        stable_depends=rel.stable_depends,
        summary=rel.summary,
        fixed_by=filtered_fixed_by,
        commit_hashes=rel.commit_hashes,
    )


def get_missing_fixes_for_summaryrel(
    summary: str, carried_summaries: set[str], mainline_relations: LinuxRelations
) -> Union[SummaryRel, None]:
    """Filter out all carried fixes for a SummaryRel. If there are no missing
    fixes, return None"""
    rel = get_summary_context(summary, mainline_relations)
    rel = filter_missing_fixes(rel, carried_summaries)

    return rel if rel.fixed_by else None


def get_missing_fixes(
    repo_path: Path,
    refspec_a: str,
    refspec_b: Union[str, None] = None,
    mainline: str = MAINLINE_MASTER,
) -> list[SummaryRel]:
    """
    Recursively get commits in refspec_a that have missing fixes not carried in
    refspec_a or refspec_b and only return missing fixes.

    Args:
        repo_path: Path to Linux git repository

        refspec_a: Source refspec to analyze e.g.
            origin/linux-5.10.y..origin/amazon-5.10.y/master for all 5.10
            downstream patches

        refspec_b: Reference refspec to check for carried fixes
            e.g. origin/amazon-5.10.y/master for the 5.10 amazon branch Default:
            None

        mainline: Refspec of the upstream mainline tree
            Default: "kernel_cve_tool/mainline/master"

    Returns:
        List of SummaryRel objects for commits with missing fixes dropped
    """
    mainline_relations = LinuxRelations.create(repo_path, refspec=mainline)

    summaries_a = LinuxRelations.get_summaries(repo_path, refspec_a)
    carried_summaries = set(summaries_a.summaries.keys())
    if refspec_b:
        summaries_b = LinuxRelations.get_summaries(repo_path, refspec_b)
        carried_summaries.update(summaries_b.summaries.keys())

    result = []
    for summary in summaries_a.summaries:
        rel = get_missing_fixes_for_summaryrel(summary, carried_summaries, mainline_relations)
        if rel:
            result.append(rel)

    return result
