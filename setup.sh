# shellcheck shell=bash
# Source this to talk to the simulation from the host's ROS 2 install:
#
#   source setup.sh
#
# Selects CycloneDDS with the loopback profile the sim container uses, and stops
# the ros2 daemon, which otherwise keeps the middleware and domain it started with.
# ROS_DOMAIN_ID must match the sim's; it is not set here.
_ros_env_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file://$_ros_env_dir/config/dds/loopback.xml
unset _ros_env_dir
if command -v ros2 >/dev/null; then
    ros2 daemon stop
else
    echo "setup.sh: ros2 not found; source your ROS 2 setup.bash first" >&2
fi
