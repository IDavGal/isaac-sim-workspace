# CLAUDE.md

Context for agents working in this workspace: what it is for, where the project is going, and the gaps it has to close. `README.md` covers how to run it, `docs/asset-pipeline.md` the asset pipeline.

## What this workspace is

A client-agnostic Isaac Sim 6.2 workspace. It holds the simulation platform pieces that do not depend on any client's scene, assets, code or network: the entrypoint, the Kit experiences, the container, the DDS profiles and the asset pipeline. Client-specific content is added in a separate layer and never committed here.

- Keep client names, repository names, hosts, addresses and people out of everything in this repo, including this file.
- `sim/main.py` is the single simulation entrypoint. No configuration language, no component framework.
- ROS 2 bridge graphs live in the USD, not in code or configuration.
- Scenario logic (spawners, grippers, joining) goes in Python modules loaded at startup with a per-frame callback and an `on_shutdown()` teardown. Do not use OmniGraph ScriptNodes.
- Isaac Sim 6.2 APIs only. `isaacsim.core.api`, `core.prims` and `core.utils` are deprecated and unused.
- Physics settings live in the USD scene or in the asset recipe, where they are versioned with the assets. Do not set them from `.kit` or carb.
- Do not commit unless asked.

## End goal of the project

A robotic cell builds timber wall panels: an industrial 6-axis arm with a multi-tool end effector (mechanical gripper, vacuum pads, nail gun), an automated saw, and an assembly table with dozens of prismatic axes. A ROS 2 Jazzy stack plans motion with a cloud path-planning server, executes joint trajectories through ros2_control and runs panel programmes as behaviour trees.

The project turns the client's Isaac Sim environment into a **stable, repeatable test platform** for that cell:

- The client's unmodified ROS 2 stack drives the whole simulated cell: arm, end effector, table axes, devices and the saw's material.
- Two reference panels (one open frame, one sheathed) are built end to end in simulation.
- A headless suite, started by one documented command, checks each build for **clashes** (contact with any surface not tagged as allowed), **placement** (final element poses against the panel specification), **stability** (dropped or thrown parts, interpenetration, abnormal velocities) and **repeatability** across runs.
- The platform is delivered into the client's repositories as pull requests, with a containerised deployment verified on the client's simulation machine, an asset pipeline that regenerates the assets with one command, documentation and a recorded handover workshop.

Window: 22 working days, about 1.5 FTE. Real-time factor 1 on the client's machine is the performance target for the simulation side.

Out of scope: changes to the stack's architecture, PLC or virtual-controller emulation, safety systems, cameras and other sensor streams, physical simulation of cutting, nailing and routing, deformable timber, cycle-time matching and comparison with real-cell data.

## How the simulation connects to the stack

- Transport is CycloneDDS over unicast peers (no multicast), one ROS domain per seat. The sim only creates its DDS participant once the stage is loaded and playing.
- The sim publishes `/clock`, and every stack node runs on simulation time.
- Arm and end-effector joints cross as `sensor_msgs/JointState` commands and states. Vacuum is an absolute `Bool` command.
- Material appears through spawn topics (an id, a box size, an optional position, a rising-edge trigger). Nailing is an id pair plus a rising-edge trigger that creates a joint between two prims.
- The stack implements the hardware side with ros2_control plugins. The client keeps the arm's interface; we implement the table axes and devices behind the interfaces the stack already uses.
- **The ROS-facing contract does not move.** Topics, names and message types stay as they are, so the stack needs no architectural change.

## The gaps

What the client's starting point lacks, and what this workspace has to be able to build or prove.

| Gap | Today | Needed |
|---|---|---|
| Platform | Isaac Sim 5.1, launched by hand through a GUI streaming client, scene opened and played manually | 6.2, headless, automatic load and play, clean exit codes |
| Assets | Cell asset is a generation behind the stack's current model. End effector and robot have manual post-import edits. About 1,300 path-based overrides. | Scripted conversion from CAD exports to layered USD, physics as data, one command to regenerate |
| Physics | Masses derived from collision geometry at water density (steel about 8× too light), first-pass drive gains, no physics materials, a history of NaNs from cross-articulation welds | Tuned mass, inertia, drives, collision, friction. No back-driven stiff joints, no solver blow-ups. |
| Table | The stack drives it through a mock ros2_control component. Nothing reaches Isaac. | An Isaac-backed hardware component behind the same controllers |
| Material | Spawn positions copied by hand for an old table. Spawned parts rest on invisible supports. A cut piece is spawned twice (at the outfeed and in the gripper under a different id), so nailing can join the wrong prims. | One owner per piece keyed by the panel element id, spawn positions from calibrated frames, saw and infeed as a black box |
| Gripping | Surface gripper driven directly works; not validated from ROS. Jaw mimic done by a script. | Surface grippers with calibrated force limits and drop behaviour |
| Joining | One fixed joint per nail at the current relative pose; flagged as needing rework | Stable assemblies as elements are joined |
| Timing | Controller manager at 20 Hz, physics at 240 Hz, joint states per rendered frame, wall-clock timeouts in the stack | One rate plan, joint states at the physics rate, wall-clock dependencies on the panel path adapted or documented |
| Contract | Two repositories edited independently, with names and topics drifting. Scene docs describe graphs that no longer exist. | One versioned interface file read by both sides, with a consistency test |
| Tests | CI integration runs exclude the simulator. Isaac checks are manual. A job reported `completed` does not mean the panel was built, because failures are absorbed by fallback branches. | Sim-side ground truth: contact reports, poses against the specification, a structured report and an exit code |
| Table nail gun | Not reachable from ROS in simulation | Until it is, sheet-to-stud nailing is represented as joining on command |

## Milestones

| Phase | ID | Milestone | What this workspace contributes |
|---|---|---|---|
| 1 | M1 | Onboarding and environment | The client's stack runs against our platform |
| 1 | M2 | Scoping and assessment | Baseline measurements through the runner, wall-clock audit, interface map and contract file, reproduction of the double spawn |
| 2 | M3 | Port to Isaac Sim 6.x | Container, runner, importer, bridge rewiring, scripts as modules, comparison with the 5.1 baseline, upgrade notes |
| 2 | M4 | Simulation-time integration | Advisory: wall-clock review and a rate plan for the stack |
| 3 | M5 | CAD-to-USD pipeline | `pipeline/`: recipe in, layered USD out, one command, regeneration test |
| 3 | M6 | Stabilised physics baseline | Mass, inertia, drives, collision, solver settings, RTF measurement |
| 3 | M7 | Material handling physics | Timber bodies, surface-gripper calibration, joining, friction and contact tuning |
| 4 | M8 | ros2_control integration | Isaac-backed table hardware component, raised rates, grippers and devices connected |
| 4 | M9 | Process abstractions | Saw and infeed spawner with seeded variation, nailing as rigid attachment |
| 5 | M10 | Test framework | Runner output and exit contract, clash, placement, stability and repeatability checks, two happy-path tests |
| 6 | M11 | Deployment and verification | Containerised run on the client's machine, RTF and repeatability |
| 6 | M12 | Documentation and handover | Guides, limitations statement, recorded workshop |

Dependencies: M3 needs the client's agreement to upgrade the machine; M5 needs the client's CAD exports and pipeline code; M7 needs material and holding-force data; M9 and M10 need the panel specification. Missing data is replaced by documented approximations.

Never drop: the second panel, physics stability, joining, the ros2_control integration, the single test entry point, deployment and handover. Drop list in order: parameterised spawner variation, visual comparison against a recorded run, RTF optimisation beyond the main findings, repeatability runs from 3 to 2.

## Approach

1. **The runner is the spine.** `sim/main.py` is the entry for porting, tuning and testing. Each milestone adds to it; M10 extends it rather than building a harness.
2. **Physics is data.** Overrides are keyed by joint and link name, never by prim path, because the 6.x importer lays prims out differently from 5.1. `pipeline/extract_overrides.py` turns a hand-tuned stage into a recipe fragment.
3. **Test risks in isolation first.** The surface gripper, joining and articulation structure are checked on generic scenes before the client's scene is involved.
4. **Every milestone ends with a headless check that can be re-run.**
5. **Interface drift is a test failure.** A versioned contract file both sides read, with a consistency test.
6. **Free-running at real-time factor near 1**, not lockstep, unless measurements say otherwise.
7. **Advise directly.** The client treats us as the experts, so give concrete best-practice recommendations where we find issues.

## Open decisions

- One articulation or two for cell plus arm. A weld between articulations has produced NaNs; one large articulation may cost solver time.
- Joining: fixed joints per nail against merged bodies. Spike on a seven-member frame.
- Physics on GPU or CPU, decided on RTF measurements.
- Reuse the scene's existing cell-axis graph or build the new hardware component.
- How the sim reports state to tests: contact reports in-process, or ROS topics.
- The runner's output contract: JSON summary, exit codes, fixed physics step, N steps or stop-on-condition.

## 6.x notes

- A stage with an empty time range makes OmniGraph playback ticks fire more than once per update. Set `endTimeCode` on stages.
- Joint-state publishing is `IsaacReadJointState` → `ROS2PublishJointState`.
- SimulationApp runs Kit in portable mode, so the shader cache must be a persisted volume. Otherwise every run recompiles shaders for about 4 minutes.
- Surface grippers are PhysX-only. Check the 6.x bindings migration guide before relying on them.
- The URDF importer ships as a separate wheel. `URDFParseAndImportFile` is gone; use `URDFImporter` and `URDFImporterConfig`.
- A `ROS_DOMAIN_ID` exported in the shell overrides `.env` in Compose. Peers need CycloneDDS and the matching profile, and `ros2 daemon stop` clears a stale daemon.
