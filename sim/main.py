"""Simulation entrypoint: start Isaac Sim, open the stage and play it until stopped.

    sim/run.sh [--stage PATH] [--display headless|window|livestream]

The stage plays in real time from startup and runs until SIGINT or SIGTERM, or
until the window is closed. The Kit experience in config/kit loads the ROS 2
bridge extension; the bridge graphs are part of the stage. The process exits 0
when stopped and 1 when the stage could not be opened or the run failed.

Environment:
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

# App updates per second. Physics substeps at the rate of the stage's PhysicsScene.
UPDATE_HZ = 60.0

EXPERIENCES = {
    "headless": WORKSPACE / "config" / "kit" / "sim.headless.kit",
    "window": WORKSPACE / "config" / "kit" / "sim.gui.kit",
    "livestream": WORKSPACE / "config" / "kit" / "sim.gui.kit",
}


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
    p.add_argument("--display", choices=EXPERIENCES, default="headless")
    args, _ = p.parse_known_args()
    args.stage = WORKSPACE / args.stage
    return args


def launch_config(display: str) -> dict:
    """SimulationApp configuration for the display mode."""
    config = {
        "headless": display != "window",
        "experience": str(EXPERIENCES[display]),
        "extra_args": [],
    }
    if display == "livestream":
        # The livestream shows the editor UI even though no local window opens.
        config["hide_ui"] = False

    vscode_port = int(os.environ.get("VSCODE_PORT") or 0)
    if vscode_port:
        config["extra_args"] += [
            "--enable",
            "isaacsim.code_editor.vscode",
            "--/exts/isaacsim.code_editor.vscode/host=0.0.0.0",
            f"--/exts/isaacsim.code_editor.vscode/port={vscode_port}",
        ]
    return config


def enable_livestream() -> bool:
    """Start the WebRTC stream on the ports from the environment."""
    import carb
    from isaacsim.core.experimental.utils import app as app_utils

    settings = carb.settings.get_settings()
    prefix = "/exts/omni.kit.livestream.app/primaryStream"
    settings.set(f"{prefix}/signalPort", int(os.environ.get("LIVESTREAM_SIGNAL_PORT", "49100")))
    settings.set(f"{prefix}/streamPort", int(os.environ.get("LIVESTREAM_STREAM_PORT", "47998")))
    if public_ip := os.environ.get("LIVESTREAM_PUBLIC_IP"):
        settings.set(f"{prefix}/publicIp", public_ip)
    settings.set("/log/channels/omni.kit.livestream.*", "error")
    return app_utils.enable_extension("omni.kit.livestream.app")


def run(kit, stage_path: Path, display: str) -> int:
    """Open the stage and play it until stopped; returns the exit status."""
    # Kit modules only import once the app is running.
    import carb
    import omni.usd
    from isaacsim.core.experimental.utils import app as app_utils
    from isaacsim.core.experimental.utils.stage import is_stage_loading
    from isaacsim.core.rendering_manager import RenderingManager
    from isaacsim.core.simulation_manager import SimulationManager

    if display == "livestream" and not enable_livestream():
        print("[sim] could not enable the livestream", file=sys.stderr)
        return 1

    ctx = omni.usd.get_context()
    if not stage_path.is_file() or not ctx.open_stage(str(stage_path)):
        print(f"[sim] could not open {stage_path}", file=sys.stderr)
        return 1
    # The stage only reports loading after the first updates.
    kit.update()
    kit.update()
    while is_stage_loading():
        kit.update()

    # RenderingManager only applies the rate limit when it is already enabled.
    carb.settings.get_settings().set("/app/runLoops/main/rateLimitEnabled", True)
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

    kit = SimulationApp(launch_config(args.display))
    try:
        code = run(kit, args.stage, args.display)
    except Exception:  # noqa: BLE001 -- the app must still close with a failure status
        traceback.print_exc()
        code = 1
    kit.close(exit_code=code)


if __name__ == "__main__":
    main()
