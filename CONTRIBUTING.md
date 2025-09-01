# Contributing Guidelines

Thank you for your interest in contributing to our project. Whether it's a bug report, new feature, correction, or additional
documentation, we greatly value feedback and contributions from our community.

Please read through this document before submitting any issues or pull requests to ensure we have all the necessary
information to effectively respond to your bug report or contribution.


## Reporting Bugs/Feature Requests

We welcome you to use the GitHub issue tracker to report bugs or suggest features.

When filing an issue, please check existing open, or recently closed, issues to make sure somebody else hasn't already
reported the issue. Please try to include as much information as you can. Details like these are incredibly useful:

* A reproducible test case or series of steps
* The version of our code being used
* Any modifications you've made relevant to the bug
* Anything unusual about your environment or deployment


## Contributing via Pull Requests
Contributions via pull requests are much appreciated. Before sending us a pull request, please ensure that:

1. You are working against the latest source on the *main* branch.
2. You check existing open, and recently merged, pull requests to make sure someone else hasn't addressed the problem already.
3. You open an issue to discuss any significant work - we would hate for your time to be wasted.

To send us a pull request, please:

1. Fork the repository.
2. Modify the source; please focus on the specific change you are contributing. If you also reformat all the code, it will be hard for us to focus on your change.
3. Ensure local tests pass.
4. Commit to your fork using clear commit messages.
5. Send us a pull request, answering any default questions in the pull request interface.
6. Pay attention to any automated CI failures reported in the pull request, and stay involved in the conversation.
7. The main branch uses branch-protection that requires at least one project maintainer to review your changes

GitHub provides additional document on [forking a repository](https://help.github.com/articles/fork-a-repo/) and
[creating a pull request](https://help.github.com/articles/creating-a-pull-request/).


## Finding contributions to work on
Looking at the existing issues is a great way to find something to contribute on. As our projects, by default, use the default GitHub issue labels (enhancement/bug/duplicate/help wanted/invalid/question/wontfix), looking at any 'help wanted' issues is a great place to start.


## Code of Conduct
This project has adopted the [Amazon Open Source Code of Conduct](https://aws.github.io/code-of-conduct).
For more information see the [Code of Conduct FAQ](https://aws.github.io/code-of-conduct-faq) or contact
opensource-codeofconduct@amazon.com with any additional questions or comments.


## Security issue notifications
If you discover a potential security issue in this project we ask that you notify AWS/Amazon Security via our [vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/). Please do **not** create a public github issue.


## Licensing

See the [LICENSE](LICENSE) file for our project's licensing. We will ask you to confirm the licensing of your contribution.

## Development

To develop and test local changes, we recommend to use a virtual python environment. The script
test/test-in-venv.sh is capable of setting up such an environment. After installing all dependencies,
this script by default runs the test suite, and a simple git-llm-pick command. Afterwards, the parameters
from the command line are forwarded and executed in the virtual environment.

### Coding Style

The project uses coding style that can be changed and achieved automatically.

To lint your code, run

```
SKIP_VENV_GLP_TESTING=1 test/test-in-venv.sh make lint
```

Formatting the code can be done with

```
SKIP_VENV_GLP_TESTING=1 test/test-in-venv.sh make format
```

### Testing

To test local changes, without running the default tests, you can set the  environment variable
SKIP_VENV_GLP_TESTING. Then, the command is executed directly.

Example call:

```
SKIP_VENV_GLP_TESTING=1 test/test-in-venv.sh make test
```

If you want to run a test with more logging, you can also use pytest to trigger the respective testing
and capture logs.

Example call:

```
SKIP_VENV_GLP_TESTING=1 test/test-in-venv.sh \
    pytest -vv --capture=no --log-cli-level=NOTSET -s \
        test/test_llm_cli_patching.py::test_llm_pick_on_git
```

#### Updating cached LLM results

To pass test suites, without access to remote services, the locally cached LLM input needs to match the queries.
Hence, in case LLM input is changed, the test artifacts need to be updated as well, and added to the respective commit.
The below instructions show the relevant steps:

Remote cached artifacts:

```
find test/patch_artifacts -name "*.json" -exec rm {} \;
```

Re-run test suite. In case of failure, fixup the code, and remove the artifacts before re-running.

```
SKIP_VENV_GLP_TESTING=1 test/test-in-venv.sh make test
```

Adding the changed test artifacts to your lats commit

```
git commit --amend test/patch_artifacts
```
