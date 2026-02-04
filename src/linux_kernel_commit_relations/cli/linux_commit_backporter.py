#!/usr/bin/env python3

"""
CLI tool for analyzing and backporting Linux kernel commits with dependencies.

This tool identifies all dependencies for a given commit and optionally backports
them in the correct order using an external backporter command.
"""

__authors__ = "Ömer Erdinç Yağmurlu <oeygmrl@amazon.de>"
__copyright__ = "Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved."
# SPDX-License-Identifier: Apache-2.0

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from tqdm import tqdm

from linux_kernel_commit_relations.commit_context import CommitRel, LinuxTag, get_commit_context
from linux_kernel_commit_relations.relations import LinuxRelations

logger = logging.getLogger(__name__)


def get_commit_date(commit_hash: str, repo_path: Path) -> int:
    """Get commit date as timestamp."""
    try:
        result = subprocess.run(
            ["git", "show", "-s", "--format=%ct", commit_hash],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return int(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        return 0


def get_rel_date(rel: CommitRel, repo_path: Path, mainline: bool = True) -> int:
    return (
        get_commit_date(rel.mainline_commit_hash, repo_path)
        if mainline
        else get_commit_date(rel.nearest_commit_hash, repo_path)
    )


def main():
    parser = argparse.ArgumentParser(
        description="Analyze commit from Linux kernel repository and backport it to a target kernel version with context"
    )
    parser.add_argument("commit", help="Commit hash to analyze and backport")
    parser.add_argument("--repo", help="Path to Linux git repository (default: %(default)s)", default=".")
    parser.add_argument(
        "--output",
        choices=["tree", "list"],
        default="tree",
        help="Output format for commit context listing (default: %(default)s)",
    )
    parser.add_argument(
        "--commit-sort",
        choices=["topo", "nearest-commit-date", "mainline-commit-date"],
        default="topo",
        help="Sort order for commit context. %(default)s is default and flattens the tree inorder with stable dependencies coming first and fixing commits last. Date sort options sort this afterwards by the respective date. Most of the time `topo` is enough.",
    )
    parser.add_argument(
        "--target-kernel-version",
        required=True,
        help="Target kernel version for backporting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List commits without backporting",
    )
    parser.add_argument(
        "--backport-command",
        default="git cherry-pick {commit}",
        help="Command to backport each commit (use {commit} as placeholder, default: %(default)s)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=10,
        help="Maximum recursion depth for dependency analysis (default: %(default)s)",
    )

    args = parser.parse_args()

    target_tag = LinuxTag(args.target_kernel_version)
    repo_path = Path(args.repo)
    if not repo_path.exists():
        raise RuntimeError(f"Repository path does not exist: {repo_path}")

    relations = LinuxRelations.create(repo_path, pbar=True)
    context = get_commit_context(
        args.commit, relations, repo_path, target=target_tag, pbar=True, max_depth=args.max_depth
    )

    if args.commit_sort == "topo":
        flattened = context.flatten()
    elif args.commit_sort == "nearest-commit-date":
        flattened = sorted(context.flatten(), key=lambda r: get_rel_date(r, repo_path, mainline=False))
    elif args.commit_sort == "mainline-commit-date":
        flattened = sorted(context.flatten(), key=lambda r: get_rel_date(r, repo_path, mainline=True))
    else:
        raise ValueError(f"Unknown commit_sort order: {args.commit_sort}")

    if args.output == "tree":
        print(context)
    else:
        for rel in flattened:
            print(rel)

    if args.dry_run:
        return 0

    if args.backport_command:
        for rel in tqdm(flattened, desc="Backporting commits"):
            cmd = args.backport_command.format(commit=rel.nearest_commit_hash)
            subprocess.run(cmd, shell=True, cwd=repo_path, check=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
