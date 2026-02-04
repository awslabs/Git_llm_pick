#!/usr/bin/env python3

"""
LinuxKernelCommitRelations module.

This module provides tools for analyzing Linux kernel commit relationships,
tracking fixes, stable dependencies, and upstream relationships across kernel versions.

Key concepts:
- Summary: The first line of a git commit message
- Commit context: Hierarchical view of commit relationships with version awareness
- Summary context: Relationships between commits grouped by their summary text
"""

__authors__ = "Ömer Erdinç Yağmurlu <oeygmrl@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

from linux_kernel_commit_relations.commit_context import (
    CommitRel,
    LinuxTag,
    get_commit_context,
    get_mainline_tags,
)
from linux_kernel_commit_relations.missing_fixes import get_missing_fixes, has_missing_fixes
from linux_kernel_commit_relations.relations import HASH_LEN, LinuxRelations
from linux_kernel_commit_relations.summary_context import SummaryRel, get_summary_context

__all__ = [
    "LinuxRelations",
    "LinuxTag",
    "SummaryRel",
    "CommitRel",
    "get_commit_context",
    "get_summary_context",
    "get_missing_fixes",
    "has_missing_fixes",
    "HASH_LEN",
    "get_mainline_tags",
]
