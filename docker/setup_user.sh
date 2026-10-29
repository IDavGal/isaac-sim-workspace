#!/bin/bash
# Make the runtime user `sim` with the host user's ids, so files it writes to the
# mounted checkout belong to the host user.
#
#   setup_user.sh UID GID
#
# The image's own user is isaac-sim (1234, HOME /isaac-sim) and UID 1000 is the
# unused `ubuntu` account: an account that already has UID is renamed to `sim`.
# HOME stays /isaac-sim, where Isaac Sim keeps its caches and logs and where the
# base image's health check reads them. Only directories are re-owned, never the
# install: a recursive chown would copy the whole install into a new layer.
set -euo pipefail

uid=$1
gid=$2
home=/isaac-sim

if [[ $uid == 0 ]]; then
    echo "setup_user.sh: refusing to run the sim as root" >&2
    exit 2
fi

# /isaac-sim is 0750: its group lets sim read files that are not world-readable.
isaac_gid=$(stat -c %g "$home")

group=$(getent group "$gid" | cut -d: -f1 || true)
if [[ -z $group ]]; then
    groupadd --gid "$gid" sim
elif [[ $gid != "$isaac_gid" ]]; then
    groupmod --new-name sim "$group"
fi
existing=$(getent passwd "$uid" | cut -d: -f1 || true)
if [[ -n $existing ]]; then
    usermod --login sim --home "$home" --shell /bin/bash "$existing"
else
    useradd --uid "$uid" --gid "$gid" --home-dir "$home" --no-create-home \
        --shell /bin/bash sim
fi
# Replaces the renamed account's groups (ubuntu is in adm, sudo, ...).
usermod --gid "$gid" --groups "$isaac_gid" sim

# HOME itself, so tools can create their own folders in it (~/.ros for ROS 2 logs).
chown "$uid:$gid" "$home"
chmod 0755 "$home"

# Folders Isaac Sim writes; docker-compose.yml mounts volumes on most of them, and a
# fresh volume takes the ownership it has here. SimulationApp runs Kit in portable
# mode, so its shader cache, data and logs are under kit/, not in HOME.
writable=(
    "$home/kit/cache"
    "$home/kit/data"
    "$home/kit/logs"
    "$home/.cache"
    "$home/.nv/ComputeCache"
    "$home/.nvidia-omniverse/logs"
    "$home/.local/share/ov/data"
    /workspace
)
mkdir -p "${writable[@]}"
chown -R "$uid:$gid" "${writable[@]}" "$home/.nv" "$home/.nvidia-omniverse" "$home/.local"
