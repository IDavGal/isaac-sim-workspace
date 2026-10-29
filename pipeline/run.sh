#!/bin/bash
# Run a pipeline script in the simulation container.
#
#   pipeline/run.sh import_asset.py pipeline/examples/test_arm/recipe.toml
#   pipeline/run.sh extract_overrides.py build/assets/test_arm/test_arm.usda --baseline ...
#
# The script name is relative to pipeline/; paths in the arguments are relative
# to the workspace root. Outputs land under build/, writable by any user.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $# -ge 1 ]] || { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
script=$1
shift
[[ -f .env ]] || cp .env.example .env
mkdir -p build
chmod a+rwx build
docker compose run --rm --no-deps --entrypoint /bin/bash sim -c \
    'umask 000; exec "$@"' _ /workspace/sim/python.sh "/workspace/pipeline/$script" "$@"
