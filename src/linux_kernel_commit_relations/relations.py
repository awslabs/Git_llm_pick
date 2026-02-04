#!/usr/bin/env python3

"""
Parse and analyze commit relationships in Linux kernel git repositories.

This module provides functionality to extract and track various commit relationships
including Fixes tags, Stable-dep-of tags, and upstream commit references from Linux
kernel git history.
"""

__authors__ = "Ömer Erdinç Yağmurlu <oeygmrl@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import logging
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Union

import pydantic
from tqdm import tqdm

logger = logging.getLogger(__name__)

HASH_LEN = 12

BODY_SEP = "-=1=- ^^ -=1=-" * 20

STABLE_DEP_OF = "Stable-dep-of: "
FIXES = "Fixes: "

# matches str like SomeTag: 6d19c44b5c6d whatever
TAG_REGEX = re.compile(rf"\S+:\s+([a-f0-9]{{{HASH_LEN},}}).*")

UPSTREAM_1_PRE = "commit "
UPSTREAM_1_REGEX = re.compile(rf"commit ([a-f0-9]{{{HASH_LEN},}}) upstream")
UPSTREAM_2_PRE = "[ Upstream commit "
UPSTREAM_2_REGEX = re.compile(rf"\[ Upstream commit ([a-f0-9]{{{HASH_LEN},}}) \]")

"""Cache of lines that have already been warned about to avoid duplicate warnings."""
warned_set: set[str] = set()


@dataclass
class Summaries:
    """Container for commit summary mappings."""

    summaries: dict[str, set[str]]
    """dict[summary, set[hash]]"""
    summary_by_hash: dict[str, str]
    """dict[hash, summary]"""


@dataclass
class Relations:
    """Container for commit relationship mappings."""

    stable_depends: dict[str, set[str]]
    """dict[hash_a, set[hash_b]] for all commits a, b where b is stable-dep-of a"""
    fixed_by: dict[str, set[str]]
    """dict[hash_a, set[hash_b]] for all commits a, b where buggy commit a is fixed by b"""
    fixes: dict[str, set[str]]
    """dict[hash_a, set[hash_b]] for all commits a, b where a fixes buggy commit b"""
    upstream: dict[str, str]
    """dict[hash, upstream_hash]"""


def warn_line(line: str, commit_hash: str, summary: str) -> None:
    """Log a debug warning for an unparseable line, once per unique line.

    Args:
        line (str): The line that failed to parse
        commit_hash (str): Hash of the commit containing the line
        summary (str): Summary of the commit
    """
    line = line.strip()
    if line in warned_set:
        return
    warned_set.add(line)
    # there are MANY invalid tags, don't spam warn or info
    logger.debug(
        "Failed parse line: %s ||| for %s '%s'",
        line,
        commit_hash,
        summary,
    )


class LinuxRelations(pydantic.BaseModel):
    """Container for Linux kernel commit relationships and metadata.

    Stores mappings between commits including fixes relationships, stable dependencies,
    upstream references, and commit summaries extracted from git log.

    Performance: Parsing a full Linux kernel repository takes approximately 30 seconds
    and uses moderate memory (a few hundred MB for the full history).
    """

    summaries: dict[str, set[str]]
    "dict[summary, set[hash]]"
    summary_by_hash: dict[str, str]
    "dict[hash, summary]"
    upstream: dict[str, str]
    "dict[hash, upstream_hash]"
    stable_depends: dict[str, set[str]]
    "dict[hash_a, set[hash_b]] for all commits a, b where b is stable-dep-of a"
    fixed_by: dict[str, set[str]]
    "dict[hash_a, set[hash_b]] for all commits a, b where a buggy commit (a) is fixed by b"
    fixes: dict[str, set[str]]
    "dict[hash_a, set[hash_b]] for all commits a, b where a fixes buggy commit b"

    @staticmethod
    def create(repo_path: Path, refspec: str = "--all", pbar: bool = False) -> "LinuxRelations":
        """Create LinuxRelations by parsing commit relationships from a git repository.

        Args:
            repo_path: Path to the Linux kernel git repository
            refspec: Git refspec to parse (default: "--all" for all branches)
            pbar: Whether to show progress bars during parsing

        Returns:
            LinuxRelations object with all parsed relationships
        """
        with ThreadPoolExecutor() as executor:
            summaries_future = executor.submit(LinuxRelations.get_summaries, repo_path, refspec, pbar, 0)
            relations_future = executor.submit(LinuxRelations.get_relations, repo_path, refspec, pbar, 1)

            summaries_result = summaries_future.result()
            relations_result = relations_future.result()

        return LinuxRelations(
            summaries=summaries_result.summaries,
            summary_by_hash=summaries_result.summary_by_hash,
            upstream=relations_result.upstream,
            stable_depends=relations_result.stable_depends,
            fixed_by=relations_result.fixed_by,
            fixes=relations_result.fixes,
        )

    @staticmethod
    def get_summaries(repo_path: Path, refspec: str = "--all", pbar: bool = False, pbar_position: int = 0) -> Summaries:
        """Get commit summaries from git log.

        Args:
            repo_path (Path): Path to the git repository
            refspec (str): Git refspec to query (default: "--all")
            pbar (bool): Whether to show progress bar
            pbar_position (int): Position of progress bar in tqdm)

        Returns:
            Summaries: Object containing summary mappings
        """
        cmd = ["git", "-C", str(repo_path), "log", "--format=%H:%s", refspec]

        with subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, errors="replace") as process:
            if not process.stdout:
                raise RuntimeError("Failed to read log summaries")

            summaries: dict[str, set[str]] = {}
            summary_by_hash: dict[str, str] = {}
            for line in tqdm(process.stdout, desc="Loading summaries", disable=not pbar, position=pbar_position):
                hash_str, summary = line.strip().split(":", 1)
                if summary not in summaries:
                    summaries[summary] = set()
                summaries[summary].add(hash_str[:HASH_LEN])

                summary_by_hash[hash_str[:HASH_LEN]] = summary

        return Summaries(summaries=summaries, summary_by_hash=summary_by_hash)

    @staticmethod
    def get_relations(repo_path: Path, refspec: str = "--all", pbar: bool = False, pbar_position: int = 0) -> Relations:
        """Get Stable-dep-of, Fixes and Upstream relations across all commits.

        Args:
            repo_path (Path): Path to the git repository
            refspec (str): Git refspec to query (default: "--all")
            pbar (bool): Whether to show progress bar
            pbar_position (int): Position of progress bar in tqdm)

        Returns:
            Relations: Object containing all commit relationship mappings
        """

        # For every commit in linux.git, across all trees, that has the text "Stable-dep-of: " or "Fixes: ":
        # > %H -> hash
        # > %s -> summary (we don't need the summary here, it's only used for logging when parsing errors happen)
        # > %b -> commit message / body (since this is multiline we have the seperator)
        cmd = [
            "git",
            "-C",
            str(repo_path),
            "log",
            f"--format=%H:%s%n%b%n{BODY_SEP}",
            refspec,
            f"--grep={STABLE_DEP_OF}",
            f"--grep={FIXES}",
        ]

        with subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, errors="replace") as process:
            if not process.stdout:
                raise RuntimeError("Failed to read log relations")

            stable_depends: dict[str, set[str]] = {}
            fixed_by: dict[str, set[str]] = {}
            fixes: dict[str, set[str]] = {}
            upstream: dict[str, str] = {}

            commit_hash_a: Union[str, None] = None
            summary: Union[str, None] = None
            for line in tqdm(process.stdout, desc="Loading relations", disable=not pbar, position=pbar_position):
                if not commit_hash_a or not summary:
                    commit_hash_a, summary = line.strip().split(":", 1)
                    # mypy fails to see commit_hash_a: str, not str | None
                    commit_hash_a = commit_hash_a[:HASH_LEN]  # type: ignore
                    continue
                if line.startswith(BODY_SEP):
                    commit_hash_a = None
                    summary = None
                    continue

                if line.startswith(STABLE_DEP_OF) or line.startswith(FIXES):
                    # only use regex if we have an interesting tag
                    match = TAG_REGEX.match(line.strip())
                    if not match:
                        warn_line(line, commit_hash_a, summary)
                        continue

                    commit_hash_b = match.group(1)
                    commit_hash_b = commit_hash_b[:HASH_LEN]

                    if line.startswith(STABLE_DEP_OF):
                        if commit_hash_b not in stable_depends:
                            stable_depends[commit_hash_b] = set()
                        stable_depends[commit_hash_b].add(commit_hash_a)
                    elif line.startswith(FIXES):
                        if commit_hash_a not in fixes:
                            fixes[commit_hash_a] = set()
                        fixes[commit_hash_a].add(commit_hash_b)

                        if commit_hash_b not in fixed_by:
                            fixed_by[commit_hash_b] = set()
                        fixed_by[commit_hash_b].add(commit_hash_a)
                elif line.startswith(UPSTREAM_1_PRE) or line.startswith(UPSTREAM_2_PRE):
                    if line.startswith(UPSTREAM_1_PRE):
                        match = UPSTREAM_1_REGEX.match(line.strip())
                        if not match:
                            # we don't log here, as the prefix "commit " can also easily show up some other place
                            continue
                    else:
                        match = UPSTREAM_2_REGEX.match(line.strip())
                        if not match:
                            warn_line(line, commit_hash_a, summary)
                            continue
                    commit_hash_b = match.group(1)
                    commit_hash_b = commit_hash_b[:HASH_LEN]
                    upstream[commit_hash_a] = commit_hash_b

        return Relations(stable_depends=stable_depends, fixed_by=fixed_by, fixes=fixes, upstream=upstream)

    def with_ancestors(self, commit_hash: str) -> set[str]:
        """Get all commits that are in the same upstream chain for a given commit hash.

        Args:
            commit_hash (str): The starting commit hash

        Returns:
            set[str]: Set of all commit hashes in the upstream chain, including the starting commit
        """
        res_set = set()
        current = commit_hash
        res_set.add(current)
        while current in self.upstream:
            current = self.upstream[current]
            res_set.add(current)
        return res_set
