#!/bin/bash

# Script to test the module in a Python virtual environment
# This script:
# 1. Creates a virtual environment if it doesn't exist
# 2. Activates the virtual environment
# 3. Installs dependencies
# 4. Installs the module from the current directory
# 5. Runs a basic test by calling "git-llm-pick --help"

set -e

# Configuration
VENV_DIR=".venv-testing"
MODULE_DIR="$(dirname "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)")"
STATUS_CACHE="$MODULE_DIR/$VENV_DIR/.git_status_cache"

# Function to create and setup virtual environment
setup_virtual_environment() {
    echo "Setting up virtual environment..."
    python3 -m venv "${VENV_DIR}"

    # Activate virtual environment
    source "${VENV_DIR}/bin/activate"

    # Upgrade pip
    pip install --upgrade pip

    # Install dev requirements as well
    pip install -e ".[dev,test]"
}

# Function to activate virtual environment
activate_virtual_environment() {
    echo "Activating virtual environment..." 1>&2
    source "${VENV_DIR}/bin/activate"
}

# Function to install the module
install_module() {
    echo "Installing module..." 1>&2
    status=0
    output=$(pip install -e "${MODULE_DIR}" 2>&1) || status=$?
    if [ $status -ne 0 ]; then
        echo "Installation failed, with output:" 1>&2
        echo "$output" 1>&2
        return 1
    fi
}

# Function to run tests
run_tests() {
    echo "Running basic test..." 1>&2
    status=0

    echo "Testing git-llm-pick --help..." 1>&2
    output=$(git-llm-pick --help 2>&1) || status=$?

    if [ $status -eq 0 ]; then
        echo "Test passed: git-llm-pick --help executed successfully" 1>&2
    else
        echo "Test failed: git-llm-pick --help returned an error" 1>&2
        echo "Test output:" 1>&2
        echo "$output" 1>&2
        return 1
    fi

    test_status=0
    echo "Testing make test..." 1>&2
    test_output=$(unset GIT_LLM_PICK_ENABLE_CACHE; make test 2>&1) || test_status=$?
    if [ $test_status -eq 0 ]; then
        echo "Test passed: make test executed successfully" 1>&2
    else
        echo "Test failed: make test returned an error" 1>&2
        echo "Test output:" 1>&2
        echo "$test_output" 1>&2
        return 1
    fi
}

# In case we setup the module installed as last time, we do not need to re-install or re-test
check_cache_matches_repo() {

    # if there is no cache file, we have to rebuild
    [ ! -r "$STATUS_CACHE" ] && return 1

    local cache_tag="$(git -C "$MODULE_DIR" describe --tags --always)"
    local -i repo_is_dirty=0
    unclean_state=$(git status --porcelain 2> /dev/null) || repo_is_dirty=1
     [ -n "$unclean_state" ] && repo_is_dirty=1

    # if there are local git changes, we have to rebuild
    [ "$repo_is_dirty" -ne 0 ] && return 1

    cached_content="$(cat "$STATUS_CACHE")"

    # if cache content differs from expected value, we have to rebuild
    [ "$cached_content" != "$cache_tag" ] && return 1

    # we can re-use
    return 0
}

# Write current repository description into cache file
update_cache_tag () {
    mkdir -p "$(dirname "$STATUS_CACHE")"
    local cache_tag="$(git -C "$MODULE_DIR" describe --tags --always)"
    echo "$cache_tag" > "$STATUS_CACHE"
}

# Main execution
main() {
    # Work from module base directory
    pushd "${MODULE_DIR}" >/dev/null

    # Check if virtual environment exists
    if [ ! -d "${VENV_DIR}" ]; then
        setup_virtual_environment
    else
        activate_virtual_environment
    fi

    # Skip installation and tests, if repo matches last state
    if ! check_cache_matches_repo; then

        # Always install the module
        install_module

        # Run tests
        if [ -z "${SKIP_VENV_GLP_TESTING}" ]; then
            run_tests
        fi

        echo "All built-in tests completed successfully!" 1>&2
    else
        echo "Skipping installation and testing, using previous environment state" 1>&2
    fi

    # If we reach this point, we could reuse the environment next time
    update_cache_tag
    popd >/dev/null

    # After running built-in tests, execute any command provided as arguments
    if [ $# -gt 0 ]; then
        echo "Running provided command: $*" 1>&2
        "$@" || { echo "Command failed with exit code $?" 1>&2; exit 1; }
    fi
}

# Execute main function
main "$@"
