#!/bin/bash

set -e

declare -a WRITE_MOUNT_PATH=()
declare -a EXTRA_ENVIRONMENT=()

# parse CLI parameters for docker run
while [ $# -gt 0 ]; do
    case "$1" in
    -v)
        shift
        if [ ! -d "$1" ]; then
            echo "error: $1 is not a directory, aborting" 1>&2
            exit 1
        fi
        WRITE_MOUNT_PATH+=("$(cd "$1" && pwd)")
        shift
        ;;
    -e)
        if [ -z "$2" ]; then
            echo "error: -e requires an argument, aborting" 1>&2
            exit 1
        fi
        EXTRA_ENVIRONMENT+=("$2")
        shift 2
        ;;
    -*)
        shift
        echo "error: Unknown parameter $1, aborting" 1>&2
        exit 1
        ;;
    *)
        break
        ;;
    esac
done

CONTAINERID=""
DOCKERIMAGE="$1"
shift

declare -r SCRIPTDIR="$(dirname "${BASH_SOURCE[0]}")"
declare -r GIT_LLM_PICK_DIR="$(cd "$SCRIPTDIR/../.." && pwd)"

# Build image if required
build_docker_container()
{
    docker_file_or_dir_or_image="$1"

    # Check whether the input is a known image we can use
    if [ ! -f "$docker_file_or_dir_or_image" ]; then
        # If the id stars with sha256, assume it's a known image
        if [[ "$docker_file_or_dir_or_image" == sha256:* ]] && docker history "$docker_file_or_dir_or_image" &>/dev/null; then
            CONTAINERID="$docker_file_or_dir_or_image"
            return
        fi
    fi

    echo "Building docker container from $docker_file_or_dir_or_image ..." 1>&2

    # by default, assume we received a directory
    local -a docker_build_target=("$docker_file_or_dir_or_image")

    # is the given parameter a file?
    if [ -f "$docker_file_or_dir_or_image" ]; then
        # tell docker build to use the file, instead of the dir
        docker_file_dir="$(dirname "$docker_file_or_dir_or_image")"
        docker_build_target=("-f" "$docker_file_or_dir_or_image" "$docker_file_dir")
    elif [ ! -d "$docker_file_or_dir_or_image" ]; then
        echo "error: cannot find specified directory $docker_file_or_dir_or_image, abort"
        exit 1
    fi

    # (re) build fresh container, with extra args?
    CONTAINERID=$(docker build --network=host -q "${docker_build_target[@]}")
}

if [ -z "$DOCKERIMAGE" ]; then
    echo "error: no docker image specified, abort"
    exit 1
fi
build_docker_container "$DOCKERIMAGE"

declare -a DOCKER_ARGS=("--network=host")

# Keep runs cache in home directory
DOCKER_RUN_DIR="$HOME/.cache/git-llm-pick-docker-run-dir"
mkdir -p "$DOCKER_RUN_DIR"
mkdir -p "$DOCKER_RUN_DIR"/.cache
mkdir -p "$DOCKER_RUN_DIR"/.local

# Mount cache as writable
DOCKER_ARGS+=("-v" "$DOCKER_RUN_DIR/.cache:$HOME/.cache:rw")

# Mount python user installation directory as writable
DOCKER_ARGS+=("-v" "$DOCKER_RUN_DIR/.local:$HOME/.local:rw")

# Mount directory of this project to be able to write cached virtual environment
DOCKER_ARGS+=("-v" "$GIT_LLM_PICK_DIR:$GIT_LLM_PICK_DIR:rw")

# Mount current directory as writable
DOCKER_ARGS+=("-v" "$PWD:$PWD:rw")

# Make current directory the working directory
DOCKER_ARGS+=("-w" "$PWD")

# Mount user home as read only
DOCKER_ARGS+=("-v" "$HOME:$HOME:ro")

# Mount all write path as writable
for path in "${WRITE_MOUNT_PATH[@]}"; do
    DOCKER_ARGS+=("-v" "$path:$path:rw")
done

# Forward environment
for envparam in "${EXTRA_ENVIRONMENT[@]}"; do
    DOCKER_ARGS+=("-e" "$envparam")
done

echo "Running command in container $CONTAINERID with CWD $PWD: $*" 1>&2
docker run \
    --rm \
    --user $(id -u):$(id -g) $(printf -- "--group-add=%q " $(id -G)) \
    --tmpfs /tmp:exec,mode=1777 --tmpfs /var/tmp \
    -ePATH="$PATH" \
    -eUSER="$USER" \
    -eHOME="$HOME" \
    "${DOCKER_ARGS[@]}" \
    "$CONTAINERID" "$@"
