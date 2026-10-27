# Isaac Sim workspace

A containerised Isaac Sim 6.2 simulation driven by one SimulationApp entrypoint.
A TOML scenario file says what to load and how to run it; Docker Compose runs it
headless, streamed over WebRTC, or in a local window. ROS 2 Jazzy talks to the
sim over CycloneDDS.

```
config/sim.toml            scenario: stage, run mode, display, ROS bridge, checks, output
config/dds/                CycloneDDS profiles (loopback, network)
docker/Dockerfile          Isaac Sim 6.2 + this workspace; entrypoint sim/run.sh
docker-compose.yml         services: sim (headless), sim-livestream, sim-window
.env.example               per-instance settings: project name, ROS domain, DDS, ports
scenes/demo_arm.usda       demo stage: a fixed-base two-joint arm
sim/
  app.py                   entrypoint: configuration, SimulationApp start
  runtime.py               the run: open stage, components, loop, checks, summary
  checks.py                stage, OmniGraph, articulation, log and ROS topic checks
  config.py                defaults, TOML loading, --set overrides, validation
  components/              scenario logic run alongside the stage
    base.py                Component: setup / update / shutdown
    ros_bridge.py          /clock and per-articulation joint states and commands
  run.sh                   runs `python -m sim` with Isaac Sim's Python
```

## Requirements

- NVIDIA GPU and driver supported by Isaac Sim 6.2 (the image requires 570.169 or later)
- Docker with the NVIDIA Container Toolkit; Docker Compose 2.30 or later
- Access to `nvcr.io/nvidia/isaac-sim:6.2.0`

## Quick start

```bash
cp .env.example .env
mkdir -p out && chmod a+w out          # the container runs as UID 1234
docker compose build

docker compose run --rm sim --summary out/run.json     # play config/sim.toml, exit with the result
docker compose up sim-livestream                       # editor over WebRTC
docker compose up sim-window                           # editor in a local window
```

`sim` plays the stage for `run.duration`, checks it and exits 0 when every check
passes, 1 when one fails and 2 when the stage did not load or the run aborted.
The editor services open the stage and leave Play to the user.

The first run compiles the RTX shaders, which takes a few minutes; later runs
reuse them from the `isaac-sim-kit-cache` volume.

For `sim-window`, allow local X clients first (`xhost +local:`, and
`xhost -local:` afterwards): the container user cannot read the host's X cookie.

## Configuration

`config/sim.toml` documents every key. Override any of them per run:

```bash
docker compose run --rm sim --set run.duration=30 --set stage.path=scenes/other.usda
docker compose run --rm sim --config config/other.toml
```

`SIM_ARGS` in `.env` appends the same arguments to every service.

Highlights:

- `run.mode`: `play` (run and check) or `interactive` (open and wait).
- `run.realtime`: rate-limit to wall clock. Otherwise the sim runs as fast as it can
  at a fixed dt: `run.render_hz` app updates per sim second, with the physics
  substeps set by the stage's PhysicsScene.
- `display.mode`: `headless`, `window` or `livestream`; `display.render` turns
  rendering off for headless runs by default.
- `ros_bridge`: the clock topic and, per articulation, the JointState topics for
  state and commands. The bridge is built at startup, not authored in the stage.
- `checks`: articulations to check, ROS topics to probe and their expected rate,
  and an optional limit on logged errors.

## Checks

Each `play` run records:

- the stage opens with one PhysicsScene and a non-empty time range;
- every OmniGraph node instantiates and no graph is disabled;
- every articulation is found, its joints stay finite and its base stays within
  1 mm after `run.settle`;
- every probed topic publishes at `checks.min_topic_rate` × `run.render_hz` or more
  (in sim time);
- optionally, no more than `checks.max_log_errors` errors in the Kit log.

The JSON summary (`--summary`) adds timings and real-time factor, active prim
count, physics settings, joint names and positions, and the first errors and
warnings from the Kit log, which is written next to it.

## ROS 2

The demo bridge publishes `/clock` and `/joint_states` and applies
`sensor_msgs/JointState` commands from `/joint_command` to the arm's drives:

```bash
ros2 topic pub /joint_command sensor_msgs/msg/JointState "{name: [joint1, joint2], position: [0.5, -0.5]}"
```

Peers must use CycloneDDS (`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`) on the same
`ROS_DOMAIN_ID`. `DDS_PROFILE=loopback` keeps DDS on this host;
`DDS_PROFILE=network` binds `DDS_INTERFACE` and discovers `DDS_PEER`.

## Several instances on one host

Give each instance its own `.env` (one checkout each, or `--env-file`) with a
distinct `COMPOSE_PROJECT_NAME`, `ROS_DOMAIN_ID`, livestream ports and
`VSCODE_PORT`. The shader and asset caches are shared volumes.

## Adding scenario logic

Subclass `sim.components.base.Component` and register it in
`Runtime._setup_components`. `setup()` runs once the stage is open and before
Play, `update()` once per app update on the main thread (it may change the
stage), `shutdown()` before exit. Subscribe to ROS with `rclpy` inside the
component and apply what arrives in `update()`.

## Without Docker

With a local Isaac Sim 6.2 install:

```bash
ISAAC_SIM_DIR=~/isaacsim sim/run.sh --summary out/run.json
```
