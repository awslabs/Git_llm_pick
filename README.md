# Git_llm_pick

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
