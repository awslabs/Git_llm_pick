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
from linux_kernel_commit_relations.missing_fixes import get_missing_fixes
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


def add_common_arguments(parser):
    """Add arguments shared by all subcommands."""
    parser.add_argument("--repo", default=".", help="Path to Linux git repository (default: %(default)s)")
    parser.add_argument(
        "--backport-command",
        default="git cherry-pick {commit}",
        help="Command to backport each commit (use {commit} as placeholder, default: %(default)s)",
    )


def _collect_fix_summaries(fix_rel):
    """Recursively collect all SummaryRel objects from a fix tree."""
    result = [fix_rel]
    for nested in fix_rel.fixed_by:
        result.extend(_collect_fix_summaries(nested))
    return result


def backport_commits(flattened_commits, repo_path, backport_command):
    """Backport a list of CommitRel."""
    total = len(flattened_commits)
    for i, commit in enumerate(tqdm(flattened_commits, desc="Backporting commits")):
        cmd = backport_command.format(commit=commit.nearest_commit_hash)
        result = subprocess.run(cmd, shell=True, cwd=repo_path, check=False)
        if result.returncode != 0:
            logger.error("Failed to backport commit %d/%d: %s", i + 1, total, commit.summary)
            if i + 1 < total:
                print(f"\nRemaining {total - i - 1} commit(s) not applied:")
                for remaining in flattened_commits[i + 1 :]:
                    print(f"  {remaining.nearest_commit_hash[:12]} {remaining.summary}")
            return 1
    return 0


def backport_command_handler(args):
    """Analyze and backport a Linux kernel commit with its dependencies."""
    target_tag = LinuxTag(args.target_kernel_version)
    repo_path = Path(args.repo)
    if not repo_path.exists():
        raise RuntimeError(f"Repository path does not exist: {repo_path}")

    relations = LinuxRelations.create(repo_path, pbar=True)
    context = get_commit_context(
        args.commit, relations, repo_path, target=target_tag, pbar=True, max_depth=args.max_depth
    )

    if args.commit_sort == "topo":
        flattened_commits = context.flatten()
    elif args.commit_sort == "nearest-commit-date":
        flattened_commits = sorted(context.flatten(), key=lambda r: get_rel_date(r, repo_path, mainline=False))
    elif args.commit_sort == "mainline-commit-date":
        flattened_commits = sorted(context.flatten(), key=lambda r: get_rel_date(r, repo_path, mainline=True))
    else:
        raise ValueError(f"Unknown commit_sort order: {args.commit_sort}")

    if args.output == "tree":
        print(context)
    else:
        for commit in flattened_commits:
            print(commit)

    if args.dry_run:
        return 0

    return backport_commits(flattened_commits, repo_path, args.backport_command)


def missing_fixups_handler(args):
    """Find missing fixups between two kernel branches and optionally backport them."""
    repo_path = Path(args.repo)
    if not repo_path.exists():
        raise RuntimeError(f"Repository path does not exist: {repo_path}")

    if not args.dry_run and not args.target_kernel_version:
        logger.error("--target-kernel-version is required unless --dry-run is specified")
        return 1

    refspec_range = f"{args.branch_a}..{args.branch_b}"
    missing = get_missing_fixes(repo_path, refspec_range, args.branch_b)

    if not missing:
        print("No commits with missing fixes found.")
        return 0

    print(f"Found {len(missing)} commit(s) with missing fixes:\n")
    for mf in missing:
        print(mf)

    if args.dry_run:
        return 0

    # Collect all fix SummaryRels and resolve to upstream commits.
    # For each fix, get_commit_context resolves its dependency tree (stable_depends),
    # so all_flattened_commits will contain both fix commits and their dependencies.
    fix_summaries = []
    for mf in missing:
        for fix_rel in mf.fixed_by:
            fix_summaries.extend(_collect_fix_summaries(fix_rel))

    if not fix_summaries:
        print("No fix commits to backport.")
        return 0

    target_tag = LinuxTag(args.target_kernel_version)
    relations = LinuxRelations.create(repo_path, pbar=True)

    all_flattened_commits = []
    seen_commits = set()
    for summary_rel in fix_summaries:
        for commit_hash in summary_rel.commit_hashes:
            try:
                ctx = get_commit_context(
                    commit_hash,
                    relations,
                    repo_path,
                    target=target_tag,
                    pbar=True,
                )
                for commit in ctx.flatten():
                    if commit.nearest_commit_hash not in seen_commits:
                        seen_commits.add(commit.nearest_commit_hash)
                        all_flattened_commits.append(commit)
                break  # one hash per summary is enough
            except ValueError:
                continue

    print(f"\n=== Backporting {len(all_flattened_commits)} commit(s) ===\n")
    for commit in all_flattened_commits:
        print(f"  {commit.nearest_commit_hash[:12]} {commit.summary}")
    print()
    return backport_commits(all_flattened_commits, repo_path, args.backport_command)


def add_backport_parser(subparsers):
    """Add backport subcommand parser."""
    parser = subparsers.add_parser(
        "backport",
        description="Analyze commit from Linux kernel repository and backport it to a target kernel version with context",
    )
    parser.set_defaults(func=backport_command_handler)
    parser.add_argument("commit", help="Commit hash to analyze and backport")
    add_common_arguments(parser)
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
    parser.add_argument("--target-kernel-version", required=True, help="Target kernel version for backporting")
    parser.add_argument("--dry-run", action="store_true", help="List commits without backporting")
    parser.add_argument(
        "--max-depth",
        type=int,
        default=10,
        help="Maximum recursion depth for dependency analysis (default: %(default)s)",
    )


def add_missing_fixups_parser(subparsers):
    """Add missing-fixups subcommand parser."""
    parser = subparsers.add_parser("missing-fixups", description="Find missing fixups between two kernel branches")
    parser.set_defaults(func=missing_fixups_handler)
    parser.add_argument("branch_a", help="Base branch or tag (e.g. v6.12.73)")
    parser.add_argument("branch_b", nargs="?", default="HEAD", help="Target branch (default: %(default)s)")
    add_common_arguments(parser)
    parser.add_argument("--dry-run", action="store_true", help="List missing fixes without backporting")
    parser.add_argument("--target-kernel-version", help="Target kernel version (required unless --dry-run)")


def main():
    parser = argparse.ArgumentParser(description="Linux kernel commit analysis and backporting tool")
    subparsers = parser.add_subparsers(dest="subcommand")
    subparsers.required = True

    add_backport_parser(subparsers)
    add_missing_fixups_parser(subparsers)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
