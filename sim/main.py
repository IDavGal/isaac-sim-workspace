"""Simulation entrypoint: start Isaac Sim, open the stage and play it until stopped.

    sim/run.sh [--stage PATH] [--gui] [--livestream]

Without --gui or --livestream nothing is rendered. --gui opens the editor in a
local window, --livestream streams the editor over WebRTC; both together stream
the local window. The stage plays in real time from startup and runs until SIGINT
or SIGTERM, or until the window is closed. The Kit experience in config/kit loads
the ROS 2 bridge extension; the bridge graphs are part of the stage. The process
exits 0 when stopped and 1 when the stage could not be opened or the run failed.

Environment:
    SIM_GUI                 1: --gui by default
    SIM_LIVESTREAM          1: --livestream by default
    LIVESTREAM_SIGNAL_PORT  TCP port the WebRTC client dials (livestream, default 49100)
    LIVESTREAM_STREAM_PORT  UDP media port, also the one advertised (livestream, default 47998)
    LIVESTREAM_PUBLIC_IP    address advertised for the media stream; empty: the host's
    VSCODE_PORT             VS Code / MCP Python executor on all interfaces; 0 disables
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import traceback
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_STAGE = WORKSPACE / "scenes" / "demo_arm.usda"

# Experiences: the editor for a window or a livestream, otherwise no UI at all. Both
# enable the ROS 2 bridge and limit the main loop to real time.
EDITOR_KIT = WORKSPACE / "config" / "kit" / "sim.gui.kit"
HEADLESS_KIT = WORKSPACE / "config" / "kit" / "sim.headless.kit"

# App updates per second, as limited by the experiences. Physics substeps at the
# rate of the stage's PhysicsScene.
UPDATE_HZ = 60.0


def env_flag(name: str) -> bool:
    """Whether the environment variable is set to a true value (1, true, yes, on)."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def parse_args() -> argparse.Namespace:
    """Parse the entrypoint's arguments, leaving Kit's own to SimulationApp."""
    p = argparse.ArgumentParser(
        prog="sim/run.sh",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--stage",
        type=Path,
        default=DEFAULT_STAGE,
        help="USD stage to open, relative to the workspace (default: %(default)s)",
    )
    p.add_argument(
        "--gui",
        action=argparse.BooleanOptionalAction,
        default=env_flag("SIM_GUI"),
        help="open the editor in a local window (default: $SIM_GUI)",
    )
    p.add_argument(
        "--livestream",
        action=argparse.BooleanOptionalAction,
        default=env_flag("SIM_LIVESTREAM"),
        help="stream the editor over WebRTC (default: $SIM_LIVESTREAM)",
    )
    args, _ = p.parse_known_args()
    args.stage = WORKSPACE / args.stage
    return args


def launch_config(gui: bool, livestream: bool) -> dict:
    """SimulationApp configuration for a local window, a livestream, both or neither."""
    if gui or livestream:
        # The livestream shows the editor UI even when no local window opens.
        config = {
            "headless": not gui,
            "hide_ui": False,
            "renderer": "RaytracedLighting",
            "experience": str(EDITOR_KIT),
            "extra_args": [],
        }
    else:
        # Nothing is displayed, so the experience disables rendering.
        config = {
            "headless": True,
            "renderer": "MinimalRendering",
            "experience": str(HEADLESS_KIT),
            "extra_args": [],
        }

    if livestream:
        prefix = "--/exts/omni.kit.livestream.app/primaryStream"
        config["extra_args"] += [
            "--enable",
            "omni.kit.livestream.app",
            f"{prefix}/signalPort={os.environ.get('LIVESTREAM_SIGNAL_PORT', '49100')}",
            f"{prefix}/streamPort={os.environ.get('LIVESTREAM_STREAM_PORT', '47998')}",
            "--/log/channels/omni.kit.livestream.*=error",
        ]
        if public_ip := os.environ.get("LIVESTREAM_PUBLIC_IP"):
            config["extra_args"].append(f"{prefix}/publicIp={public_ip}")

    vscode_port = int(os.environ.get("VSCODE_PORT") or 0)
    if vscode_port:
        config["extra_args"] += [
            "--enable",
            "isaacsim.code_editor.vscode",
            "--/exts/isaacsim.code_editor.vscode/host=0.0.0.0",
            f"--/exts/isaacsim.code_editor.vscode/port={vscode_port}",
        ]
    return config


def run(kit, stage_path: Path) -> int:
    """Open the stage and play it until stopped; returns the exit status."""
    # Kit modules only import once the app is running.
    import omni.usd
    from isaacsim.core.experimental.utils import app as app_utils
    from isaacsim.core.experimental.utils.stage import is_stage_loading
    from isaacsim.core.rendering_manager import RenderingManager
    from isaacsim.core.simulation_manager import SimulationManager

    ctx = omni.usd.get_context()
    if not stage_path.is_file() or not ctx.open_stage(str(stage_path)):
        print(f"[sim] could not open {stage_path}", file=sys.stderr)
        return 1
    # The stage only reports loading after the first updates.
    kit.update()
    kit.update()
    while is_stage_loading():
        kit.update()

    # The experience enables the rate limit; RenderingManager sets its frequency.
    RenderingManager.set_dt(1.0 / UPDATE_HZ)
    # Keeps the physics rate and device authored on the stage's PhysicsScene.
    SimulationManager.setup_simulation()

    stopping = False

    def request_stop(signum, _frame) -> None:
        nonlocal stopping
        print(f"[sim] received signal {signum}, stopping")
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    app_utils.play()
    print(f"[sim] playing {stage_path}")
    while kit.is_running() and not stopping:
        kit.update()
    app_utils.stop()
    kit.update()
    return 0


def main() -> None:
    """Start Isaac Sim for the requested display and run the stage."""
    args = parse_args()

    from isaacsim import SimulationApp

    kit = SimulationApp(launch_config(args.gui, args.livestream))
    try:
        code = run(kit, args.stage)
    except Exception:  # noqa: BLE001 -- the app must still close with a failure status
        traceback.print_exc()
        code = 1
    kit.close(exit_code=code)


if __name__ == "__main__":
    main()
