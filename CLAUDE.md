# CLAUDE.md

Guidance for working in this repository. README.md is the user documentation (how to
run things); this file is the maintainer's view: what the pieces are, why they are
the way they are, and how to check a change.

## What this is

A containerised Isaac Sim 6.2 simulation with one entrypoint. `sim/main.py` starts
SimulationApp, opens a USD stage, plays it in real time and runs until stopped. It
runs headless (nothing rendered), in a local X11 window, streamed over WebRTC, or in
a local window that is also streamed. ROS 2 Jazzy (Isaac Sim's internal libraries)
talks to the outside over CycloneDDS. The demo stage (`scenes/demo_arm.usda`) is a
fixed-base two-joint arm whose ROS 2 bridge is an OmniGraph inside the stage:
`/clock`, `/joint_states` out, `/joint_command` (sensor_msgs/JointState) in.

The scope is deliberately small. An earlier version had a component framework
(`sim/app.py`, `sim/components/`, `sim/config.py`, `sim/checks.py`, `config/sim.toml`);
it was removed (commit f6c4cfb) in favour of one script plus Kit experience files.
Keep it that way unless a real need appears: behaviour belongs in the stage (USD,
OmniGraph) or in the Kit experience, not in Python glue.

## Layout

```
sim/main.py                 entrypoint: SimulationApp, open stage, play until SIGINT/SIGTERM/window close
sim/run.sh                  image entrypoint: Isaac Sim's Python environment, then exec python main.py
config/kit/sim.gui.kit      editor experience (window and/or livestream): trimmed isaacsim.exp.full
config/kit/sim.headless.kit headless experience: only the extensions main.py and the stage need
config/dds/{loopback,network}.xml   CycloneDDS profiles, unicast discovery, no multicast
scenes/demo_arm.usda        demo stage with its ROS 2 bridge graph (/World/ROSBridge)
docker/Dockerfile           Isaac Sim image + workspace, runtime user `sim` with the host uid/gid
docker/setup_user.sh        creates `sim` at build time (see "User remapping")
docker/sim.sh               the CLI: build | run [--gui] [--livestream] [--build] [-- ARGS] | shell
docker-compose.yml          the `sim` service; settings from .env (.env.example documents them)
setup.sh                    source on the host to talk to the sim from a host ROS 2 install
.pre-commit-config.yaml     all linters; CI (.github/workflows/lint.yml) runs the same hooks
```

## Design decisions and why

### Entrypoint (`sim/main.py`, `sim/run.sh`)
- `run.sh` reproduces Isaac Sim's `python.sh` environment but `exec`s Python, so
  SIGTERM from `docker stop` reaches main.py and its exit status survives
  (`python.sh` maps every failure to 1).
- main.py exits 0 when stopped, 1 when the stage cannot be opened or the run fails;
  `docker/sim.sh run` passes that status through.
- Mode is chosen by `--gui`/`--livestream` or `SIM_GUI`/`SIM_LIVESTREAM`. Window or
  livestream boots `sim.gui.kit` with RaytracedLighting; neither boots
  `sim.headless.kit` with rendering disabled. The livestream is enabled at runtime
  (`--enable omni.kit.livestream.app`) on top of the editor, so window + stream works.
- Real time: the experiences enable the main-loop rate limit at 60 Hz with Isaac's
  manual run-loop mode, and main.py sets `RenderingManager.set_dt(1/60)`. Physics
  steps at the stage's PhysicsScene rate (240 Hz in the demo). `/clock` advances at
  wall-clock speed; verify with two `ros2 topic echo /clock --once` a few seconds apart.

### Kit experiences (`config/kit/*.kit`)
- They are loaded from the workspace, not Isaac Sim's `apps/`, so `${app}` is
  `/workspace/config/kit`; Isaac Sim's folders are reached through `${kit}/..`.
- Both replace (not append to) `app.exts.folders` and `app.exts.foldersCore`. Kit's
  defaults name folders this install does not have (`${kit}/exts`,
  `${kit}/extsPhysics`, per-user document folders); for each, Kit also searches an
  empty path, which is the working directory, and logs an "extension.toml doesn't
  exist" warning for every folder in `/workspace`. NVIDIA's stock experiences have
  the same problem.
- The headless experience does not depend on `isaacsim.exp.base`: that pulls the
  editor's menus, windows, content browsers, motion planners and Replicator writers
  (318 extensions, app ready ~23 s). The explicit list (154 extensions, ready ~6 s)
  is SimulationApp + loop-isaac, what main.py imports, and the stage's OmniGraph
  node providers. `isaacsim.ros2.nodes` is used instead of `isaacsim.ros2.bridge`,
  which only adds UI and examples. The few `exp.base` settings that matter (manual
  run-loop mode, fabric frame history, DLSS frame generation off, ...) are copied in.
  **A new stage with other nodes or sensors needs their extensions added here**; a
  missing one appears as an unknown node type in the Kit log and its topics never appear.
  Some viewport extensions still load because `isaacsim.core.nodes` and
  `isaacsim.core.rendering_manager` depend on them.
- The GUI experience is `isaacsim.exp.full` minus examples, content browsers, asset
  converters and authoring tools, for faster startup. Settings are not persistent
  (`app.settings.persistent = false`) so every run starts from the files, window
  layout included. A livestream client disconnecting must not stop the sim
  (`quitOnSessionEnded = false`).
- `exts."isaacsim.ros2.bridge".ros_distro = "system_default"` makes Isaac Sim use its
  internal Jazzy libraries when no distro is sourced (the container never sources one).

### Image (`docker/Dockerfile`, `docker/setup_user.sh`)
- User remapping: the container runs as `sim` with the host user's uid/gid (build
  args set by sim.sh) so files written to the mounted checkout belong to the host
  user. The base image's user is `isaac-sim` (1234, HOME `/isaac-sim`) and uid 1000
  is an unused `ubuntu` account, which gets renamed. HOME stays `/isaac-sim` because
  Isaac Sim keeps caches and logs there. Only the directories Isaac Sim writes are
  re-owned; a recursive chown of the install would copy it into a new layer.
  `sim` is in the `isaac-sim` group because `/isaac-sim` is 0750.
  Consequence: rebuild when a different host user runs it; root is refused.
- SimulationApp runs Kit in portable mode, so shader cache, data and logs live under
  `/isaac-sim/kit/`, not HOME. The base image's healthcheck reads HOME; ours greps the
  newest Kit log for `app ready`, which both experiences log.
- OmniHub (`HUB__*` env): the base image sets `HUB__ARGS__DETECT_ONLY=true` and a
  cache dir owned by `isaac-sim`, so Kit's client fails to launch the Hub and logs
  ~40 retry warnings per start (the stock image does too); fixing it took headless
  app-ready from ~16 s to ~6 s. We let the Hub start (dynamic localhost ports, no cleaner, so instances
  on the host network do not collide) with its cache in container-local `/tmp`,
  because instances of one user share the cache volumes and each starts its own Hub.
- The workspace is COPY'd into the image so it runs standalone (CI, deployment);
  compose mounts the checkout over it, so only Dockerfile changes need a rebuild.

### Compose (`docker-compose.yml`)
- `network_mode: host`: DDS and the livestream use the host's interfaces directly.
  CycloneDDS runs over UDP only, so no shared memory/IPC namespace is shared.
- Volumes are named per uid (`isaac-sim-*-<uid>`), so users on a shared host don't
  share caches with wrong ownership; instances of one user share them (shader cache
  compiles once, a few minutes on first run). Volumes from before this naming
  (`isaac-sim-cache`, `-kit-cache`, `-compute-cache`, `-logs`, `-ov-data`) are stale.
- Each instance on a host needs its own `COMPOSE_PROJECT_NAME`, `ROS_DOMAIN_ID`,
  livestream ports and `VSCODE_PORT` (`docker/sim.sh --env-file FILE`).

### CLI (`docker/sim.sh`)
- The container is `<COMPOSE_PROJECT_NAME>-sim`, so one sim per project; `run` refuses
  a second one and `shell` execs into the running one (or starts a fresh container).
- `run` does not `exec` Compose: an EXIT trap stops and removes the container and
  deletes the X cookie copy.
- `run` creates the container without `--rm` and returns the container's exit code:
  after Ctrl+C Compose itself exits 130 or 255 regardless of what the sim did.
- `trap '' PIPE` before Compose: with the output piped (`run | tee log`), Ctrl+C also
  kills the reader; without the trap Compose and the cleanup died of SIGPIPE, the
  status was lost and the X cookie copy leaked.
- `--gui` copies the X cookie into `$XDG_RUNTIME_DIR` (not world-enterable) with the
  family rewritten to FamilyWild (`ffff`) so it matches the container's hostname,
  instead of `xhost +`.

### ROS 2 / DDS
- CycloneDDS with unicast discovery to known peers, no multicast, so discovery does
  not depend on the network forwarding multicast. `loopback` keeps DDS on `lo`; `network`
  binds `DDS_INTERFACE` and discovers `DDS_PEER` (CycloneDDS expands env vars).
- Host side: `source setup.sh` after the ROS 2 setup.bash. It sets
  `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` and the loopback profile, and stops the
  `ros2` daemon, which otherwise keeps the RMW and domain it started with, so CLI
  queries would not see the sim. `ROS_DOMAIN_ID` must match the sim's.
- A host ROS 2 newer than Jazzy (tested with Lyrical) interoperates for these topics.

## Verifying a change

Static (fast, no GPU): `pre-commit run --all-files`.

Runtime (needs an NVIDIA GPU; each boot takes ~10-20 s once shaders are cached):

```bash
docker/sim.sh build                     # after Dockerfile changes
docker/sim.sh run                       # headless; in another terminal:
docker ps --filter name=isaac-sim-sim   # (healthy) once Kit is ready
source /opt/ros/<distro>/setup.bash && source setup.sh
ros2 topic list                         # /clock /joint_command /joint_states
ros2 topic pub --once /joint_command sensor_msgs/msg/JointState "{name: [joint1, joint2], position: [0.5, -0.5]}"
ros2 topic echo /joint_states --once --field position   # converges to the command
docker stop isaac-sim-sim               # run exits 0, no container left
docker/sim.sh run --gui                 # same checks; a human confirms the window
docker/sim.sh run -- --stage scenes/missing.usda; echo $?   # 1
```

Also worth checking when touching sim.sh: Ctrl+C with the output piped
(`docker/sim.sh run | cat`) exits 0, leaves no container and, with `--gui`, no
`$XDG_RUNTIME_DIR/sim-xauth.*` file.

Kit logs: `docker/sim.sh shell -- bash -c 'ls -t /isaac-sim/kit/logs/Kit/*/*/kit_*.log'`
(the `isaac-sim-logs-<uid>` volume; the folder name contains a space, so quote it).
A clean run has 0 `[Error]` lines. Expected warnings: GLFW/windowing and "failed to
open the default display" in headless, IOMMU and CPU powersave notices (host
specific), `pxr.Semantics is deprecated`, muted USD diagnostics, the material
library's missing context-menu integration in headless. `[spin] error in rcl_take:
error not set` on the console after a one-shot `ros2 topic pub` comes from Isaac
Sim's ROS 2 library and is harmless (the command still applies).

## Conventions

- Comments explain why, in plain sentences; files start with a header saying what
  they are and who uses them. Match that density when editing.
- Shell: bash with `set -euo pipefail`, shellcheck-clean. Python: ruff (google
  docstrings, line length 100). YAML: yamllint strict. Dockerfile: hadolint.
- README.md is user-facing (how to run); keep it in sync with sim.sh's usage block
  (`sed -n '2,22p' docker/sim.sh` is printed by `--help`) and with `.env.example`.
- Running the image accepts the NVIDIA Isaac Sim license (`ACCEPT_EULA=Y` in compose).
