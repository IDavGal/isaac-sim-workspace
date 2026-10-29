# Isaac Sim workspace

A containerised Isaac Sim 6.2 simulation driven by one SimulationApp entrypoint.
It opens a USD stage and plays it in real time until stopped: headless, in a local
window, streamed over WebRTC, or in a local window that is also streamed. ROS 2
Jazzy talks to the sim over CycloneDDS.

```
sim/main.py                entrypoint: start SimulationApp, open the stage, play until stopped
sim/run.sh                 runs sim/main.py with Isaac Sim's Python (the image entrypoint)
scenes/demo_arm.usda       demo stage: a fixed-base two-joint arm and its ROS 2 bridge graph
config/kit/sim.gui.kit     experience for a window or a livestream: a lighter Isaac Sim editor
config/kit/sim.headless.kit  experience without UI: only what the sim and its stage use, nothing rendered
config/dds/                CycloneDDS profiles (loopback, network)
setup.sh                   host shell setup for ROS 2 nodes that talk to the sim
docker/Dockerfile          Isaac Sim 6.2 + this workspace, running as your user id
docker/sim.sh              build, run, shell: the way to drive the container
docker-compose.yml         the sim service
.env.example               optional per-instance settings: project name, ROS domain, DDS, ports
```

## Requirements

- NVIDIA GPU and driver supported by Isaac Sim 6.2 (the image requires 570.169 or later)
- Docker with the NVIDIA Container Toolkit; Docker Compose 2.30 or later
- Access to `nvcr.io/nvidia/isaac-sim:6.2.0`
- `xauth` on the host for the local window

## Quick start

Running the image accepts the [NVIDIA Isaac Sim license](https://www.nvidia.com/en-us/agreements/enterprise-software/isaac-sim-additional-software-and-materials-license/)
(`docker-compose.yml` sets `ACCEPT_EULA=Y`); read it first. Then:

```bash
docker/sim.sh build         # build the image for your user id
docker/sim.sh run --gui     # open the sim in a local window
```

## Running

```
docker/sim.sh [--env-file FILE] build [COMPOSE_BUILD_OPTIONS...]
docker/sim.sh [--env-file FILE] run [--gui] [--livestream] [--build] [-- ARGS...]
docker/sim.sh [--env-file FILE] shell [-- COMMAND...]
```

| Command | |
|---|---|
| `build` | build the image; Compose build options pass through, e.g. `build --pull --no-cache` |
| `run` | run the sim, headless and with nothing rendered unless asked otherwise |
| `run --gui` | the editor in a local X11 window |
| `run --livestream` | the editor streamed over WebRTC; with `--gui`, the local window is streamed |
| `run --build` | build the image first; only needed after `docker/Dockerfile` changes, since the checkout is mounted into the container. `run` never rebuilds on its own |
| `run -- ARGS` | arguments for `sim/main.py`, e.g. `-- --stage scenes/other.usda` |
| `shell` | a shell in the running sim container, or in a new container when the sim is not running; `shell -- COMMAND` runs a command instead |
| `--env-file FILE` | instance settings instead of `.env` (see below) |

`--gui` and `--livestream` reach `sim/main.py` as `SIM_GUI` and `SIM_LIVESTREAM`.
A window or a livestream boots the editor experience, `config/kit/sim.gui.kit`;
with neither, `config/kit/sim.headless.kit` runs without UI. The livestream is enabled at
runtime on top of the editor, so it works with or without the local window. In
every mode the stage starts playing as soon as it has loaded, in real time at 60
app updates per second, and runs until Ctrl+C, `docker stop` or, in the window,
closing it. `run` exits with the sim's status: 0 when it was stopped, 1 when the
stage could not be opened or the run failed.

The headless experience loads only the extensions `sim/main.py` and the demo
stage's OmniGraph nodes need, not Isaac Sim's full base experience, so it boots
in seconds. A stage with other nodes or sensors needs their extensions added to
its `[dependencies]`; a missing one shows up as an unknown node type in the Kit
log.

The container is named `<COMPOSE_PROJECT_NAME>-sim` (`isaac-sim-sim` by default),
so one sim runs per project; `run` refuses to start a second one. `sim.sh`
removes the container when the run ends, and stops it first if Compose exited
without stopping it. That works with the output piped too (`run | tee sim.log`).
The container reports healthy once Isaac Sim has loaded.

The image runs as `sim`, with your user and group ids (the build arguments
`USER_ID` and `GROUP_ID`, which `sim.sh` sets), so files written to the checkout
belong to you. Rebuild when another user runs it. For `--gui`, `sim.sh` gives the
container a copy of your X cookie and deletes it on exit.

The first run compiles the RTX shaders, which takes a few minutes; later runs
reuse them from the `isaac-sim-kit-cache-<uid>` volume. Kit logs are in the
`isaac-sim-logs-<uid>` volume (`/isaac-sim/kit/logs` in the container).

Plain Compose works too. Build with your ids, and for a window add the X11
access yourself (or allow local X clients with `xhost +local:`):

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose build
docker compose run --rm sim                          # headless
docker compose run --rm -e SIM_LIVESTREAM=1 sim      # livestream
```

## ROS 2

The demo stage carries its ROS 2 bridge as an OmniGraph (`/World/ROSBridge`).
It publishes `/clock` and `/joint_states`, and applies `sensor_msgs/JointState`
commands from `/joint_command` to the arm's drives:

```bash
ros2 topic pub /joint_command sensor_msgs/msg/JointState "{name: [joint1, joint2], position: [0.5, -0.5]}"
```

From a host with ROS 2 Jazzy, `source setup.sh` selects CycloneDDS with the
loopback profile and stops the `ros2` daemon, which otherwise keeps the
middleware it started with. `ROS_DOMAIN_ID` must match the sim's.

Peers must use CycloneDDS (`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`) on the same
`ROS_DOMAIN_ID`. Discovery runs over unicast to known peers, without multicast:
`DDS_PROFILE=loopback` keeps DDS on this host; `DDS_PROFILE=network` binds
`DDS_INTERFACE` and discovers `DDS_PEER`.

## Several instances on one host

Give each instance its own `.env` (one checkout each, or `docker/sim.sh
--env-file FILE`) with a distinct `COMPOSE_PROJECT_NAME`, `ROS_DOMAIN_ID`,
livestream ports and `VSCODE_PORT`. Instances of the same user share the shader
and asset cache volumes.

## Without Docker

With a local Isaac Sim 6.2 install:

```bash
ACCEPT_EULA=Y ISAAC_SIM_DIR=~/isaacsim sim/run.sh --gui
```

## Development

```bash
pre-commit install          # once; the hooks then run on every commit
pre-commit run --all-files  # ruff, shellcheck, hadolint, yamllint, XML/TOML/kit checks,
                            # docker compose config
```

CI runs the same hooks on every push to `main` and every pull request.
