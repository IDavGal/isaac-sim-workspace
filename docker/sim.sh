#!/bin/bash
# Build the image, run the sim, or open a shell in its container (docker-compose.yml).
#
#   docker/sim.sh [--env-file FILE] build [COMPOSE_BUILD_OPTIONS...]
#   docker/sim.sh [--env-file FILE] run [--gui] [--livestream] [--build] [-- ARGS...]
#   docker/sim.sh [--env-file FILE] shell [-- COMMAND...]
#
#   build          build the image for your user id, e.g. build --pull --no-cache
#   run            run the sim, headless unless asked otherwise:
#     --gui          the editor in a local X11 window
#     --livestream   the editor streamed over WebRTC (with --gui: the window, streamed)
#     --build        build the image first; only needed after docker/Dockerfile
#                    changes, since the checkout is mounted into the container
#     -- ARGS        arguments for sim/main.py, e.g. -- --stage scenes/other.usda
#   shell          a shell (or COMMAND) in the running sim container, or in a new
#                  container when the sim is not running
#
#   --env-file FILE  instance settings instead of .env (several instances on a host)
#
# The sim container is named <project>-sim after COMPOSE_PROJECT_NAME, so only one
# runs per project. `run` exits with the sim's status.
set -euo pipefail

WORKSPACE=$(cd "$(dirname "$0")/.." && pwd)
compose=(docker compose --project-directory "$WORKSPACE" -f "$WORKSPACE/docker-compose.yml")

usage() {
    sed -n '2,22s/^# \{0,1\}//p' "$0"
}

die() {
    echo "sim.sh: $*" >&2
    exit 2
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --env-file)
            [[ $# -ge 2 ]] || die "--env-file needs a value"
            [[ -f $2 ]] || die "no such env file: $2"
            compose+=(--env-file "$2")
            shift 2
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            break
            ;;
    esac
done
[[ $# -gt 0 ]] || { usage >&2; exit 2; }
subcommand=$1
shift

# The image is built for, and the cache volumes are named after, the host user.
HOST_UID=$(id -u)
HOST_GID=$(id -g)
export HOST_UID HOST_GID

# The resolved configuration: the project name, which names the container, and the
# sim's environment.
config=$("${compose[@]}" config)
project=$(sed -n 's/^name: //p' <<<"$config")
container=$project-sim

# Value of a variable in the sim service's environment.
setting() {
    sed -n "s/^ *$1: \"\{0,1\}\([^\"]*\)\"\{0,1\}$/\1/p" <<<"$config" | head -1
}

running() {
    [[ $(docker container inspect -f '{{.State.Running}}' "$1" 2>/dev/null) == true ]]
}

cmd_build() {
    "${compose[@]}" build "$@" sim
}

cmd_run() {
    local gui=0 livestream=0 build=() extra=()
    while [[ $# -gt 0 ]]; do
        case $1 in
            --gui) gui=1 ;;
            --livestream) livestream=1 ;;
            --build) build=(--build) ;;
            --)
                shift
                extra=("$@")
                break
                ;;
            *) die "run: unknown argument: $1" ;;
        esac
        shift
    done

    if running "$container"; then
        die "$container is already running; docker/sim.sh shell opens a shell in it"
    fi
    # Left over from a run that was killed before its cleanup.
    docker container rm "$container" >/dev/null 2>&1 || true

    # Without --rm: the container's exit code is the sim's status, read once it has
    # stopped; the cleanup removes it.
    local args=(run --name "$container" "${build[@]}"
        -e "SIM_GUI=$gui" -e "SIM_LIVESTREAM=$livestream")

    if [[ $gui == 1 ]]; then
        [[ -n ${DISPLAY:-} ]] || die "--gui needs an X display, and DISPLAY is not set"
        command -v xauth >/dev/null || die "--gui needs xauth (apt install xauth)"
        # The container user may not be the host user that owns the display, so the
        # container gets its own copy of the X cookie, in the per-user runtime
        # directory that other host users cannot enter. ffff (FamilyWild) makes it
        # match whatever hostname the container reports.
        local runtime_dir=${XDG_RUNTIME_DIR:-$(mktemp -d)}
        xauth_file=$(mktemp "$runtime_dir/sim-xauth.XXXXXX")
        xauth nlist "$DISPLAY" | sed -e 's/^..../ffff/' | xauth -f "$xauth_file" nmerge -
        chmod 644 "$xauth_file"
        args+=(-e "DISPLAY=$DISPLAY" -e XAUTHORITY=/tmp/.sim.xauth
            -v /tmp/.X11-unix:/tmp/.X11-unix -v "$xauth_file:/tmp/.sim.xauth:ro")
    fi

    if [[ $livestream == 1 ]]; then
        local address
        address=$(setting LIVESTREAM_PUBLIC_IP)
        address=${address:-$(hostname -I 2>/dev/null | awk '{print $1}')}
        echo "sim.sh: livestream on ${address:-this host}: signaling on TCP" \
            "$(setting LIVESTREAM_SIGNAL_PORT), media on UDP $(setting LIVESTREAM_STREAM_PORT);" \
            "connect with the Isaac Sim WebRTC Streaming Client once the stage plays"
    fi

    # Not exec: the trap removes the container and the X cookie copy, and stops the
    # container if Compose exits without stopping it (Ctrl+C without a terminal).
    trap cleanup EXIT
    # With the output piped (`run | tee sim.log`), Ctrl+C stops the reader too. Compose
    # (which inherits this) and the cleanup then get EPIPE writing to it instead of
    # dying of SIGPIPE, which would cut the cleanup short.
    trap '' PIPE
    created=1
    local status=0
    "${compose[@]}" "${args[@]}" sim "${extra[@]}" || status=$?
    # After Ctrl+C, Compose exits 130 or 255 whatever the sim did, so the status is
    # the container's; Compose's only when it failed before the container ran.
    stop_container
    local code
    if code=$(docker container inspect -f '{{.State.ExitCode}}' "$container" 2>/dev/null); then
        status=$code
    fi
    return "$status"
}

cmd_shell() {
    local cmd=()
    if [[ $# -gt 0 ]]; then
        [[ $1 == -- ]] || die "shell: unknown argument: $1"
        shift
        cmd=("$@")
    fi
    local tty=()
    [[ -t 0 && -t 1 ]] && tty=(-t)

    if running "$container"; then
        exec docker exec -i "${tty[@]}" "$container" "${cmd[@]:-bash}"
    fi
    if [[ ${#cmd[@]} -eq 0 ]]; then
        exec "${compose[@]}" run --rm --name "$project-shell-$$" --entrypoint bash sim
    fi
    exec "${compose[@]}" run --rm --name "$project-shell-$$" --entrypoint env sim "${cmd[@]}"
}

stop_container() {
    if running "$container"; then
        # The reader of a piped output may be gone.
        echo "sim.sh: stopping $container" >&2 2>/dev/null || true
        docker stop "$container" >/dev/null || true
    fi
}

created=0
xauth_file=""
cleanup() {
    if [[ $created == 1 ]]; then
        stop_container
        docker container rm "$container" >/dev/null 2>&1 || true
    fi
    if [[ -n $xauth_file ]]; then
        rm -f "$xauth_file"
    fi
}

case $subcommand in
    build) cmd_build "$@" ;;
    run) cmd_run "$@" ;;
    shell) cmd_shell "$@" ;;
    *) die "unknown command '$subcommand'; choose one of: build, run, shell" ;;
esac
