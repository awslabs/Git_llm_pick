#!/bin/bash
#
# Script to test backporting performance of git-llm-pick on Linux kernel.
#
# The script expects to be executed in the Linux kernel git repository root.
#
# Note: the script will modify the content of the directory. It uses hard-coded
# benchmark values like the commit tag to start from, as well as the location
# to the file storing the list of commits to attempt to pick.
#
# Example invocation (test 10 commits without validation):
#
# glp-test-6.1.125-stable-backporting.sh 10 novalidate

error_handler()
{
    local _PROG="$0"
    local LINE="$1"
    local ERR="$2"
    if [ $ERR != 0 ]; then
        echo "$_PROG: error_handler() invoked, line $LINE, exit status $ERR" 1>&2
    fi
    exit "$ERR"
}
set -e
trap 'error_handler $LINENO $?' ERR

SOURCE_DIR=$(dirname ${BASH_SOURCE[0]})
SOURCE_DIR=$(readlink -f "$SOURCE_DIR")
START_TIMSTAMP="$(date)"

# Allow 4 minutes for each call, including compilation
CALL_TIMEOUT_S=240

# Select benchmark suite based on script name. Uses softlinks to name benchmarks differently
SCRIPT_LINK_NAME=$(basename "$0")
if [ "$SCRIPT_LINK_NAME" == "glp-test-6.1.142-fixes-backporting.sh" ]; then
    START_TAG="v6.1.142"
    PICK_COMMIT_CANDIDATES="$SOURCE_DIR/upstream-commits-with-fixes-range-v6.1.142..kernel-6.1.147-172.266.amzn2023.txt"
elif [ "$SCRIPT_LINK_NAME" == "glp-test-6.1.125-stable-backporting.sh" ]; then
    START_TAG="v6.1.125"
    PICK_COMMIT_CANDIDATES="$SOURCE_DIR/$START_TAG-commits-to-apply.txt"
else
    echo "error: script link name $SCRIPT_LINK_NAME not known, aborting"
    exit 1
fi

# Test each change with the kernel compilation script
TEST_COMMAND="$SOURCE_DIR/../../bin/glp-compile-test-changed-kernel-file.sh"
if ! command -v $TEST_COMMAND &>/dev/null; then
    echo "error: Command $TEST_COMMAND not found, cannot validate picked commits" 1>&2
    exit 1
fi
if [ ! -r "$PICK_COMMIT_CANDIDATES" ]; then
    echo "error: File $PICK_COMMIT_CANDIDATES not found, cannot pick commits" 1>&2
    exit 1
fi

# Process CLI parameters for script, hidden expert options
FIRSTN="$1"
NO_VALIDATE="$2"
LOGDIR="$3"

# Set variables
LIMIT_COMMAND="cat"
if [ -n "$FIRSTN" ]; then
    LIMIT_COMMAND="head -n $FIRSTN"
fi
if [ -n "$LOGDIR" ]; then
    mkdir -p "$LOGDIR"
else
    LOGDIR=".."
fi
echo "Logging files per call and summary to directory $LOGDIR" 1>&2

# Do not count comment lines for total commits
TOTAL_COMMITS=$(awk '!/^#/ {print $1}' "$PICK_COMMIT_CANDIDATES" | $LIMIT_COMMAND | wc -l)
if [ "$TOTAL_COMMITS" -eq 0 ]; then
    echo "error: no commits to pick, aborting" 1>&2
    exit 1
fi

echo "Setting up repository ..." 1>&2
git cherry-pick --abort &>/dev/null || true
git reset --hard "$START_TAG"
git clean -fxd &>/dev/null

declare -a validate_cmd=("--validation-command" "$TEST_COMMAND" "--run-validation-after=ALL")
if [ "$NO_VALIDATE" == "novalidate" ]; then
    validate_cmd=()
fi

declare -a llm_pick=()
if git-llm-pick --help |& grep -q -- "--llm-pick"; then
    llm_pick=("--llm-pick=cache_file=$HOME/.cache/git_fuzzy_pick_llm_cache.json")
fi

echo "From $TOTAL_COMMITS, picking $FIRSTN commits, with validation command ${validate_command[*]} and LLM parameter ${llm_pick[*]} ..." 1>&2

one_line_summary()
{
    echo "Backport: success: $SUCCESSFUL_PICKS -- failed: ${#failed_commits[@]} total commits: $(git log --oneline "$START_TAG"..HEAD | wc -l) -- with context: $(git log --grep "Cherry-picked as dependency for " "$START_TAG"..HEAD | grep "Cherry-picked as dependency for " | sort | uniq -c | wc -l)"
}

declare -A failed_commits
declare -i count=1
declare -i SUCCESSFUL_PICKS=0
declare -a LOG_FILES=()
# From each line, that does not start with #, use the first item as commit to pick
for commit in $(awk '!/^#/ {print $1}' "$PICK_COMMIT_CANDIDATES" | $LIMIT_COMMAND); do
    echo ""
    date
    echo "Attempting backporting commit $count / $TOTAL_COMMITS (after ${SECONDS}s): $commit ..."
    count+=1

    # Between git cleanup operations, leave a small pause to avoid repo locking issues
    echo "Cleaning repository ..." 1>&2
    sleep .5
    git cherry-pick --abort &>/dev/null || true
    sleep .5
    git reset --hard HEAD &>/dev/null
    sleep .5
    git clean -fxd &>/dev/null
    pick_status=0

    set -x
    timeout "$CALL_TIMEOUT_S" \
        git-llm-pick --log-level=DEBUG \
        "${llm_pick[@]}" \
        "${validate_cmd[@]}" \
        -s -x $commit &>"$LOGDIR/pick-$commit.txt" || pick_status=$?
    LOG_FILES+=("$LOGDIR/pick-$commit.txt")
    set +x
    if [ "$pick_status" -eq 0 ]; then
        SUCCESSFUL_PICKS=$((SUCCESSFUL_PICKS + 1))
        git show |& grep "Applied with " || true
    else
        # Initialize array to store failed commits and their status
        echo "Picking commit $commit failed with status $pick_status"
        failed_commits[$commit]=$pick_status
    fi
    one_line_summary
done

# Summary generation
summarize()
{
    echo "Backport with validation summary:"
    echo "Timestamp: From $START_TIMSTAMP to $(date)"
    echo "Patches attempted to backport: $TOTAL_COMMITS"
    echo "Patches backported successfully: $SUCCESSFUL_PICKS"
    echo "Backported total: $(git log --oneline "$START_TAG"..HEAD | wc -l)"

    echo "Applied with patch tool:"
    git log --grep "Applied with " "$START_TAG"..HEAD | grep "Applied with " | sort | uniq -c
    git log --grep "Applied with " "$START_TAG"..HEAD | grep "Cherry-picked with " | sort | uniq -c
    echo "Picked with help of context commits: $(git log --grep "Cherry-picked as dependency for " "$START_TAG"..HEAD | grep "Cherry-picked as dependency for " | sort | uniq -c | wc -l)"

    echo ""
    echo "LLM Stats"
    echo "LLM Query Attempts"
    grep "Query to LLM:" "${LOG_FILES[@]}" | wc -l
    echo "LLM received no answers"
    grep "ailed to receive an answer from the LL" "${LOG_FILES[@]}" | wc -l
    echo "LLM File Writes"
    grep "Writing modified version" "${LOG_FILES[@]}" | wc -l
    echo "LLM Failures"
    grep "Failed to query bedrock " "${LOG_FILES[@]}" || true

    echo "Context commits to prepare picking commit:"
    git log --grep "context commits to prepare picking commit" "$START_TAG"..HEAD | grep "context commits to prepare picking commit"

    echo "==== Start Run Errors ===="
    grep "\[ERROR " "${LOG_FILES[@]}" | grep -v "error: Failed to fuzzy-pick commit" | grep -v "Failed to apply " || true
    echo "==== End Run Errors ===="

    # After the loop ends, print failed commits summary
    echo ""
    echo "Failed commits summary (sorted by exit code):"
    for commit in $(
        for k in "${!failed_commits[@]}"; do
            echo "${failed_commits[$k]} $k"
        done | sort -n | cut -d' ' -f2
    ); do
        echo "Commit $commit failed with status ${failed_commits[$commit]}"
    done
}

SUMMARY_FILE="summary-llm-pick-$(git -C "$SOURCE_DIR" describe --tags --always)-from-$START_TAG".txt
echo "Writing summary to $LOGDIR/$SUMMARY_FILE ..." 1>&2
summarize | tee "$LOGDIR"/"$SUMMARY_FILE"
