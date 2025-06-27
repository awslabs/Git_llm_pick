#!/bin/bash
#
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This script is part of the git-llm-pick.
#
# This script checks whether modified source files in the linux kernel still
# compile correctly. The script uses the allyesconfig, in case no .config file
# is detected.
#
# The relative path to modified header and source files is expected as command
# line parameters to this script. Header files are tested by finding a source
# file that includes a header file with the same name.
#
# Note: Needs to be executed in the root directory of the linux kernel.
# Note: This script does not perform cleanup.

declare -r DEFAULT_KERNEL_CONFIG="allyesconfig"

# Fail on error
set -e -E

# Tell the user summary, independently of error
exit_handler()
{
    local status="$1"
    echo "From provided ${#CHANGED_FILES[@]} files, skipped ${#SKIPPED_FILES[@]}" 1>&2
    if [ "$status" -ne 0 ]; then
        echo "error: Failed to validate all files!" 1>&2
    fi
}

trap 'exit_handler $?' EXIT

declare -ar CHANGED_FILES=("$@")
echo "Received ${#CHANGED_FILES[@]} files to test compilation for: ${CHANGED_FILES[*]}" 1>&2
declare -a SKIPPED_FILES=()

# No date string in the kernel to improve caching effectiveness
export KBUILD_BUILD_TIMESTAMP=''

# Use ccache, if it's available
declare -a compile_flags=()
if command -v ccache &>/dev/null; then
    compile_flags+=(CC="ccache gcc" HOSTCC="ccache gcc")
fi

# Use parallel compilation with all cores, and fall back to 4 cores
declare -i NUMCPUS="$(nproc)"
[ -z "$NUMCPUS" ] && NUMCPUS=4

# Create a config if required
[ -r ".config" ] || make -j "$NUMCPUS" "$DEFAULT_KERNEL_CONFIG" "${compile_flags[@]}"

for file in "${CHANGED_FILES[@]}"; do
    # If file ends with '.c', run "make" on related object file with ".o"
    if [[ $file == *.c ]]; then
        echo "Compile file $file" 1>&2
        make -j "$NUMCPUS" "${compile_flags[@]}" "${file%.c}.o"
    elif [[ $file == *.h ]]; then
        basefile=$(basename "$file")

        # Recursively check whether we find a file that includes the modified header
        dir="$(dirname "$file")"
        cfile=""
        while [ -n "$dir" ]; do
            # We are only interested in .c files
            cfile=$(git -C "$dir" grep '#include ' | grep '[<"/]'"$basefile"'[">]' | awk -F: '{print $1}' | grep '\.c$' | head -n 1)
            if [ -n "$cfile" ]; then
                cfile="${dir}/${cfile}"
                break
            fi
            dir="$(dirname "$dir")"
        done

        if [ -n "$cfile" ]; then
            echo "Compile file $cfile that includes $file" 1>&2
            make -j "$NUMCPUS" "${compile_flags[@]}" "${cfile%.c}.o"
        else
            echo "Failed to detect a compilation target for file $file" 1>&2
            SKIPPED_FILES+=("$file")
        fi
    else
        echo "Currently no support for type of changed file $file, skipping" 1>&2
        SKIPPED_FILES+=("$file")
    fi
done

exit 0
