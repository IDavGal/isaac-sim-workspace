#!/bin/bash
# Run one of the docker-compose.yml services and exit with its status.
#
#   docker/run.sh [--service NAME] [--build] [-- ENTRYPOINT_ARGS...]
#
#   --service NAME  sim-window (default), sim-livestream or sim
#   --build         rebuild the image before running
#   -- ARGS         extra entrypoint arguments, e.g. -- --stage scenes/other.usda
#
# Creates .env from .env.example on first use. For sim-window it hands the
# container a copy of the X cookie it can read, since the container user is
# not the host user that owns the display.
set -euo pipefail

WORKSPACE=$(cd "$(dirname "$0")/.." && pwd)
SERVICES=(sim-window sim-livestream sim)
service=sim-window
build=()
extra=()

usage() {
    sed -n '2,13s/^# \{0,1\}//p' "$0"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --service)
            [[ $# -ge 2 ]] || { echo "run.sh: --service needs a value" >&2; exit 2; }
            service=$2
            shift 2
            ;;
        --service=*)
            service=${1#*=}
            shift
            ;;
        --build)
            build=(--build)
            shift
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        --)
            shift
            extra=("$@")
            break
            ;;
        *)
            echo "run.sh: unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ ! " ${SERVICES[*]} " =~ " $service " ]]; then
    echo "run.sh: unknown service '$service'; choose one of: ${SERVICES[*]}" >&2
    exit 2
fi

cd "$WORKSPACE"
if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "run.sh: created .env from .env.example"
fi

xauth_file=""
cleanup() {
    if [[ -n $xauth_file ]]; then
        rm -f "$xauth_file"
    fi
}
trap cleanup EXIT

if [[ $service == sim-window ]]; then
    if [[ -z ${DISPLAY:-} ]]; then
        echo "run.sh: DISPLAY is not set; sim-window needs an X display" >&2
        exit 2
    fi
    if ! command -v xauth >/dev/null; then
        echo "run.sh: xauth not found (apt install xauth)" >&2
        exit 2
    fi
    # The cookie goes in the per-user runtime directory, which other host users
    # cannot enter; it is world-readable only so the container user can read
    # it through the bind mount. ffff (FamilyWild) makes it match whatever
    # hostname the container reports.
    runtime_dir=${XDG_RUNTIME_DIR:-$(mktemp -d)}
    xauth_file=$(mktemp "$runtime_dir/sim-xauth.XXXXXX")
    xauth nlist "$DISPLAY" | sed -e 's/^..../ffff/' | xauth -f "$xauth_file" nmerge -
    chmod 644 "$xauth_file"
    export XAUTH_FILE=$xauth_file
fi

if [[ ${#extra[@]} -gt 0 ]]; then
    # Appended to the service's command by docker-compose.yml.
    SIM_ARGS=$(printf '%q ' "${extra[@]}")
    export SIM_ARGS
fi

# Not exec: the trap removes the X cookie copy when the container exits.
status=0
docker compose run --rm "${build[@]}" "$service" || status=$?
exit "$status"
