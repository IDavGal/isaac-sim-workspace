#!/bin/bash
# Run the sim entrypoint (python -m sim) with Isaac Sim's Python. Same
# environment as Isaac Sim's python.sh, but execs Python so SIGTERM reaches the
# entrypoint and its exit status is preserved (python.sh maps every failure to 1).
#
#   sim/run.sh --set run.duration=30 --summary out/run.json
#
# ISAAC_SIM_DIR selects the install; it defaults to the container's.
set -e
ISAAC_SIM_DIR=${ISAAC_SIM_DIR:-/isaac-sim}
WORKSPACE=$(cd "$(dirname "$0")/.." && pwd)
export CARB_APP_PATH=$ISAAC_SIM_DIR/kit
export ISAAC_PATH=$ISAAC_SIM_DIR
export EXP_PATH=$ISAAC_SIM_DIR/apps
source "$ISAAC_SIM_DIR/setup_python_env.sh"
source "$ISAAC_SIM_DIR/setup_ros_env.sh"
export PYTHONPATH=$WORKSPACE:$PYTHONPATH
export RESOURCE_NAME="IsaacSim"
export PYTHONUNBUFFERED=1
export LD_PRELOAD=$ISAAC_SIM_DIR/kit/libcarb.so${LD_PRELOAD:+:$LD_PRELOAD}
exec "$ISAAC_SIM_DIR/kit/python/bin/python3" -m sim "$@"
