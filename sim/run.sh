#!/bin/bash
# Run sim/main.py with Isaac Sim's Python.
#
#   sim/run.sh --display window --stage scenes/demo_arm.usda
#
# ISAAC_SIM_DIR selects the install; it defaults to the container's.
HERE=$(cd "$(dirname "$0")" && pwd)
exec "$HERE/python.sh" "$HERE/main.py" "$@"
