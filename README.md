# Git_llm_pick

This repository contains two packages for Linux kernel backporting:

1. **git_llm_pick**: A drop-in replacement for git cherry-pick with LLM-assisted conflict resolution
2. **linux_kernel_commit_relations**: A library and CLI tool for analyzing Linux kernel commit dependencies

## git_llm_pick

This package provides git-llm-pick, a drop-in replacement for the git cherry-pick command.
Git-llm-pick first tries to use git cherry-pick.
On failure, we next try to use the patch tool to apply the commit.
In case the patch tool fails to apply a commit, an LLM is used to modify and apply the rejected hunks.
On success, the commit message is extended with the used tool, and an explanation in case an LLM was used.

To reduce the risk of breaking the project, git-llm-pick provides the capability to run validation commands after patching.
The user can provide a command that is executed after a commit is applied, where the modified files are passed as parameters.
To port commits across code bases, path rewriting in commits is also supported.

# Licensing and AI Usage Notice

## Project License

This tool is licensed under the Apache 2.0 license. This license applies only to the code of the git-llm-pick project itself.

## AI Integration Notice

This tool uses Large Language Models (LLMs) to assist with code modifications.
By default, it uses AWS Nova Pro on AWS Bedrock, but can be modified to use other LLMs or AI services.
Usage of any LLM or AI service is subject to separate terms and conditions.
Use of AI services may incur usage fees from your service provider.

## User Responsibilities

 * Users must separately agree to the terms and conditions of the applicable LLM or AI service.
 * Users must review and validate any AI-generated modifications before submitting them upstream.
 * Users are responsible for ensuring that any code generated or modified by this tool complies with the licensing requirements of their target project.

## Important Notes for Backporting

This tool is designed to assist experienced developers with backporting; it is not intended to automate the backporting process.
Successful backporting requires expertise and careful manual review.

# Getting Started

You need active AWS credentials, and access to the selected AWS Bedrock model (Nova Pro as default) to be able to use the tool.
If your system has no access to your AWS account, or is missing libraries, the respective phases will be skipped.

Documentation how to access AWS Bedrock models is given in
https://docs.aws.amazon.com/bedrock/latest/userguide/model-access-modify.html

## Picking with LLM Support

The below command attempts to backport a commit. First, we use plain git-cherry-pick.
In case of failure, we use the patch tool to apply the commit.
As last attempt, git-llm-pick tries to use an LLM to adjust all rejected hunks from the patch tool.

### Making git-llm-pick available

The below commands expect git-llm-pick to be available in PATH.
You can prefix the calls in the test/test-in-venv.sh script, to use
git-llm-pick from a testing environment.

### Call for cherry-picking

Cherry-pick a commit with git-llm-pick's defaults:

```
# In case you have (multiple) cherry-pick parameter
git-llm-pick -x $commit

# Do not use the LLM (i.e. just use cherry-pick and patch)
git-llm-pick --no-llm-pick $commit
```

### Cherry-picking with AWS Bedrock customization

Cherry-pick a commit with specific values for the LLM selection:

```
git-llm-pick --llm-pick=us.amazon.nova-pro-v1:0,aws_region=us-west-2 -x $commit
```

# LinuxKernelCommitRelations

The `linux_kernel_commit_relations` package provides a Python library for analyzing commit relationships in Linux kernel repositories and a CLI tool called `linux-commit-backporter` for backporting commits with their dependencies.

When backporting a patch from one Linux kernel version to another (e.g., from Linux 6.12 to Linux 5.4), you need to identify additional commits required for the patch to apply correctly and function properly. For example, if a patch calls a function `do_x()`, you need the commit that introduces this function. This tool analyzes commit relationships using the `Fixes:` and `Stable-dep-of:` tags in Linux kernel commit messages to automatically identify these dependencies.

The CLI tool depends on an external backporter command like `git-llm-pick` or `git cherry-pick` to actually apply the commits.

## How It Works

The tool parses git commit messages looking for specific relationship tags:
- `Fixes: <commit-hash>` - Indicates this commit fixes a bug in the referenced commit
- `Stable-dep-of: <commit-hash>` - Indicates this commit is a stable dependency of the referenced commit
- `commit <hash> upstream` or `[ Upstream commit <hash> ]` - Links stable branch commits to their mainline versions

It builds a dependency graph from these relationships and can identify missing fixes when comparing different kernel branches.

## Command Line Interface

The CLI uses subcommands to organize its functionality. Common options shared by all subcommands:

- `--repo`: Path to the Linux kernel git repository (default: current directory)
- `--backport-command`: Command to run for each commit (use `{commit}` as placeholder, default: `git cherry-pick {commit}`)

### Backport

Analyze a Linux kernel commit and backport it with its full dependency context and git-llm-pick:

```bash
linux-commit-backporter backport <commit-hash> \
    --repo /path/to/linux/repo \
    --target-kernel-version <version> \
    --backport-command "git-llm-pick {commit}"
```

**Options:**

- `--target-kernel-version`: Target kernel version for backporting (required)
- `--output tree|list`: Display format (default: tree)
- `--commit-sort topo|nearest-commit-date|mainline-commit-date`: Sort order (default: topo)
- `--dry-run`: List commits without backporting
- `--max-depth`: Maximum recursion depth for dependency analysis (default: 10)

### Missing-fixups

Find commits in a branch range that have missing fix commits, and backport them along with their dependencies:

```bash
# Find and backport missing fixes (default behavior)
linux-commit-backporter missing-fixups v6.12.73 v6.12.74 \
    --repo /path/to/linux/repo \
    --target-kernel-version 6.12

# Use git-llm-pick for conflict resolution
linux-commit-backporter missing-fixups v6.12.73 v6.12.74 \
    --repo /path/to/linux/repo \
    --target-kernel-version 6.12 \
    --backport-command "git-llm-pick {commit}"

# Only list missing fixes without backporting
linux-commit-backporter missing-fixups v6.12.73 v6.12.74 \
    --repo /path/to/linux/repo \
    --dry-run

# branch_b defaults to HEAD if omitted
linux-commit-backporter missing-fixups v6.12.73 \
    --repo /path/to/linux/repo \
    --dry-run
```

**Options:**

- `branch_a`: Base branch or tag (required)
- `branch_b`: Target branch (default: HEAD)
- `--dry-run`: List missing fixes without backporting
- `--target-kernel-version`: Target kernel version (required unless `--dry-run`)

### Repository Requirements

The tool works best with a **non-shallow** Linux kernel repository. A shallow clone may miss commit relationships and dependencies. To ensure complete analysis:

```bash
# Clone the full repository (recommended)
git clone https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git

# Or if you have a shallow clone, unshallow it
git fetch --unshallow
```

Tags are not required for the tool to function.

### Performance Notes

Building the relationship graph parses all commit messages across all branches in the Linux kernel repository. This takes approximately **30 seconds** and uses a few hundred MB of memory.

**Caching opportunity**: Currently, the relationship graph is rebuilt on each invocation. If faster startup is needed, caching could be implemented by serializing/deserializing the `LinuxRelations` model. See `LinuxRelations.create()` in `src/linux_kernel_commit_relations/relations.py` for where this would be most beneficial.

## Library Usage

### Find Missing Fixes

```python
from linux_kernel_commit_relations import get_missing_fixes, SummaryRel

repo_path = "/path/to/linux/repo"
missing_fixes: list[SummaryRel] = get_missing_fixes(repo_path, "branch_a", "branch_b")

for missing_fix in missing_fixes:
    print(missing_fix)
```

**SummaryRel** represents a commit with its dependency relationships:
- `summary`: The commit message summary line
- `commit_hashes`: Set of commit hashes with this summary
- `stable_depends`: List of SummaryRel objects this commit depends on
- `fixed_by`: List of SummaryRel objects that fix this commit

### Analyze Commit Relations

```python
from linux_kernel_commit_relations import LinuxRelations, get_commit_context

# LinuxRelations parses all commit relationships in the repository
relations = LinuxRelations.create("/path/to/linux/repo")

# Get commit context with dependencies for a specific commit
# target specifies the kernel version to identify the most suitable commit to backport from
commit_context = get_commit_context("abc1234567", relations, "/path/to/linux/repo", target="4.14")

# Analyze commit relationships
print(commit_context)
```

# Release Process

This project follows [Semantic Versioning (SemVer)](https://semver.org/) for all releases.

- **Support Policy**: Only the latest published release receives support and
bug fixes.
- **Release Types**: Standard releases only - no pre-release candidates or
special releases.
- **Security**: All releases are cryptographically signed.
- **Versioning**: Version numbers follow the `MAJOR.MINOR.PATCH` format per
SemVer specification:
    - **MAJOR**: Incremented for incompatible API changes,
    - **MINOR**: Incremented for backwards-compatible functionality additions,
    - **PATCH**: Incremented for backwards-compatible bug fixes.

Users are encouraged to update to the latest release to receive the most recent
features, improvements, and security updates.

# Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.
