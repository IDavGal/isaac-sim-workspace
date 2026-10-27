"""Entrypoint: load the scenario configuration, start SimulationApp and run the scenario.

    python -m sim                                   # config/sim.toml
    python -m sim --config my.toml --set run.duration=30 --summary out/run.json

In play mode the stage runs for run.duration sim seconds (or until SIGINT or
SIGTERM when it is 0), is checked, and the process exits 0 when every check
passes, 1 when one fails and 2 when the stage did not load or the run aborted.
In interactive mode the stage opens in the editor and Play is left to the user.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from sim import config

EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_ABORTED = 2

# SimulationApp renderer per display.render, plus the Kit args that turn rendering off.
RENDER_MODES = {
    "none": ("MinimalRendering", ["--/app/renderer/enabled=false", "--/renderer/enabled=false"]),
    "minimal": ("MinimalRendering", []),
    "rtx": ("RaytracedLighting", []),
}

# Experience per display.mode when kit.experience is empty, in Isaac Sim's apps
# folder; None keeps SimulationApp's default python experience.
EXPERIENCES = {
    "headless": None,
    "window": "isaacsim.exp.full.kit",
    "livestream": "isaacsim.exp.full.streaming.kit",
}

# livestream.log_level mapped to Kit log levels.
LOG_LEVELS = {
    "silence": "fatal",
    "error": "error",
    "warning": "warn",
    "info": "info",
    "debug": "verbose",
    "verbose": "verbose",
}


def parse_args() -> argparse.Namespace:
    """Parse the entrypoint's arguments, leaving Kit's own to SimulationApp."""
    p = argparse.ArgumentParser(
        prog="python -m sim",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--config", type=Path, help=f"scenario file (default: {config.DEFAULT_CONFIG})")
    p.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="SECTION.KEY=VALUE",
        help="override one configuration value; repeatable",
    )
    p.add_argument("--summary", help="shorthand for --set output.summary=PATH")
    args, _ = p.parse_known_args()
    if args.summary:
        args.set.append(f"output.summary={args.summary}")
    return args


def log_path(cfg: dict) -> Path:
    """Where Kit writes its log for this run."""
    out = cfg["output"]
    if out["log_file"]:
        return config.resolve(out["log_file"])
    if out["summary"]:
        return config.resolve(out["summary"]).with_suffix(".kit.log")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return Path.home() / ".nvidia-omniverse" / "logs" / "sim" / f"{stamp}.kit.log"


def render_mode(cfg: dict) -> str:
    """The configured render mode, defaulting on whether anything is displayed."""
    render = cfg["display"]["render"]
    if render:
        return render
    return "none" if cfg["display"]["mode"] == "headless" else "rtx"


def kit_args(cfg: dict, log_file: Path) -> list[str]:
    """Kit arguments for logging, display, livestream and remote execution."""
    args = [
        *RENDER_MODES[render_mode(cfg)][1],
        f"--/log/file={log_file}",
        "--/log/fileLogLevel=warn",
        # Flush every written line so the log can be parsed before shutdown.
        "--/log/fileFlushLevel=warn",
    ]
    if cfg["display"]["mode"] == "livestream":
        stream = cfg["livestream"]
        prefix = "--/exts/omni.kit.livestream.app/primaryStream"
        args += [
            f"{prefix}/signalPort={stream['signal_port']}",
            f"{prefix}/streamPort={stream['stream_port']}",
            f"--/log/channels/omni.kit.livestream.*={LOG_LEVELS[stream['log_level']]}",
        ]
        if stream["public_ip"]:
            args.append(f"{prefix}/publicIp={stream['public_ip']}")
    port = cfg["remote_exec"]["vscode_port"]
    if port:
        args += [
            "--enable",
            "isaacsim.code_editor.vscode",
            "--/exts/isaacsim.code_editor.vscode/host=0.0.0.0",
            f"--/exts/isaacsim.code_editor.vscode/port={port}",
        ]
    return args + cfg["kit"]["args"]


def experience(cfg: dict) -> str | None:
    """Experience file for the run; None keeps SimulationApp's default."""
    if cfg["kit"]["experience"]:
        return str(config.resolve(cfg["kit"]["experience"]))
    name = EXPERIENCES[cfg["display"]["mode"]]
    return str(Path(os.environ["EXP_PATH"]) / name) if name else None


def main() -> None:
    """Start Isaac Sim for the configured scenario and run it."""
    started = time.monotonic()
    args = parse_args()
    try:
        cfg = config.load(args.config, args.set)
    except (ValueError, OSError) as e:  # ConfigError and TOML syntax errors are ValueErrors
        print(f"sim: configuration error: {e}", file=sys.stderr)
        sys.exit(EXIT_ABORTED)
    log_file = log_path(cfg)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    from isaacsim import SimulationApp

    mode = cfg["display"]["mode"]
    launch_config = {
        "headless": mode != "window",
        # The livestream shows the editor UI even though no local window opens.
        "hide_ui": False if mode == "livestream" else None,
        "renderer": RENDER_MODES[render_mode(cfg)][0],
        "extra_args": kit_args(cfg, log_file),
    }
    if exp := experience(cfg):
        launch_config["experience"] = exp
    kit = SimulationApp(launch_config)

    # Kit modules only import once the app is running.
    from sim.runtime import Runtime

    code = Runtime(kit, cfg, log_file, started).run()
    kit.close(exit_code=code)
