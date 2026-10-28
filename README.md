# Isaac Sim workspace

A containerised Isaac Sim 6.2 simulation driven by one SimulationApp entrypoint.
It opens a USD stage and plays it in real time until stopped, headless, streamed
over WebRTC, or in a local window. ROS 2 Jazzy talks to the sim over CycloneDDS.

```
sim/main.py                entrypoint: start SimulationApp, open the stage, play until stopped
sim/run.sh                 runs sim/main.py with Isaac Sim's Python (the image entrypoint)
scenes/demo_arm.usda       demo stage: a fixed-base two-joint arm and its ROS 2 bridge graph
config/kit/                Kit experiences: sim.headless.kit, sim.gui.kit (both load the ROS 2 bridge)
config/dds/                CycloneDDS profiles (loopback, network)
docker/Dockerfile          Isaac Sim 6.2 + this workspace
docker/run.sh              runs the simulation: --display, --build, X11 access for the window
docker-compose.yml         the sim service
.env.example               per-instance settings: EULA, project name, ROS domain, DDS, ports
```

## Requirements

- NVIDIA GPU and driver supported by Isaac Sim 6.2 (the image requires 570.169 or later)
- Docker with the NVIDIA Container Toolkit; Docker Compose 2.30 or later
- Access to `nvcr.io/nvidia/isaac-sim:6.2.0`
- `xauth` on the host for the local window

## Quick start

Read the [NVIDIA Isaac Sim license](https://www.nvidia.com/en-us/agreements/enterprise-software/isaac-sim-additional-software-and-materials-license/),
then:

```bash
cp .env.example .env        # and set ACCEPT_EULA=Y in it
docker/run.sh --build       # build the image and open the sim in a local window
```

The sim does not start until `ACCEPT_EULA` is set.

## Running

```
docker/run.sh [--display MODE] [--build] [-- ENTRYPOINT_ARGS...]
```

| Option | |
|---|---|
| `--display window` | the editor in a local X11 window (default) |
| `--display livestream` | the editor streamed over WebRTC |
| `--display headless` | no window, nothing rendered |
| `--build` | rebuild the image first; only needed after `docker/Dockerfile` changes, since the checkout is mounted into the container |
| `-- ARGS` | arguments for `sim/main.py`, e.g. `-- --stage scenes/other.usda` |

The display picks the Kit experience: `headless` uses `config/kit/sim.headless.kit`
and the other two use `config/kit/sim.gui.kit`. For `livestream` the entrypoint
also starts the WebRTC extension, on the ports in `.env`. In every mode the stage starts playing as soon as it has loaded, in
real time at 60 app updates per second, and runs until Ctrl+C, `docker stop`
or, in the window, closing it. `run.sh` exits with the sim's status: 0 when it
was stopped, 1 when the stage could not be opened or the run failed.

For `window`, `run.sh` gives the container a copy of your X cookie that the
container user can read, and deletes it on exit.

The first run compiles the RTX shaders, which takes a few minutes; later runs
reuse them from the `isaac-sim-kit-cache` volume.

The same runs with plain Compose, with the display in `SIM_DISPLAY` (default
`headless`). Started that way, `window` gets no X cookie: allow local X clients
first (`xhost +local:`, and `xhost -local:` afterwards).

```bash
docker compose run --rm sim
SIM_DISPLAY=livestream docker compose run --rm sim
```

## ROS 2

The demo stage carries its ROS 2 bridge as an OmniGraph (`/World/ROSBridge`).
It publishes `/clock` and `/joint_states`, and applies `sensor_msgs/JointState`
commands from `/joint_command` to the arm's drives:

```bash
ros2 topic pub /joint_command sensor_msgs/msg/JointState "{name: [joint1, joint2], position: [0.5, -0.5]}"
```

Peers must use CycloneDDS (`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`) on the same
`ROS_DOMAIN_ID`. Discovery runs over unicast to known peers, without multicast:
`DDS_PROFILE=loopback` keeps DDS on this host; `DDS_PROFILE=network` binds
`DDS_INTERFACE` and discovers `DDS_PEER`.

## Several instances on one host

Give each instance its own `.env` (one checkout each, or `--env-file`) with a
distinct `COMPOSE_PROJECT_NAME`, `ROS_DOMAIN_ID`, livestream ports and
`VSCODE_PORT`. The shader and asset caches are shared volumes.

## Without Docker

With a local Isaac Sim 6.2 install:

```bash
ACCEPT_EULA=Y ISAAC_SIM_DIR=~/isaacsim sim/run.sh --display window
```
