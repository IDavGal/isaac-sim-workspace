"""The scenario run: open the stage, run components, step, check and summarise.

Import only after SimulationApp has started.
"""

from __future__ import annotations

import json
import math
import os
import signal
import time
import traceback
from pathlib import Path

import carb
import numpy as np
import omni.usd
from isaacsim.core.experimental.utils import app as app_utils
from isaacsim.core.experimental.utils.stage import is_stage_loading
from isaacsim.core.rendering_manager import RenderingManager
from isaacsim.core.simulation_manager import SimulationManager
from pxr import Usd

from sim import checks, config
from sim.app import EXIT_ABORTED, EXIT_CHECK_FAILED, EXIT_OK
from sim.components.base import Component, Context
from sim.components.ros_bridge import RosBridge

# Fixed-base articulation roots must not move once running.
MAX_BASE_DRIFT_M = 1e-3


class StopFlag:
    """Set by SIGINT or SIGTERM so the run loop exits cleanly."""

    def __init__(self) -> None:
        self.set = False
        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)

    def _on_signal(self, signum, _frame) -> None:
        print(f"[sim] received signal {signum}, stopping")
        self.set = True


class Runtime:
    """One run of the configured scenario."""

    def __init__(self, kit, cfg: dict, log_file: Path, started: float) -> None:
        self.kit = kit
        self.cfg = cfg
        self.log_file = log_file
        self.started = started
        self.report = checks.Report()
        self.components: list[Component] = []

    def run(self) -> int:
        """Run the scenario and write the summary; returns the exit status."""
        try:
            code = self._run()
        except Exception as e:  # noqa: BLE001 -- a failed run must still leave a summary
            traceback.print_exc()
            self.report.data["exception"] = repr(e)
            code = EXIT_ABORTED
        for component in self.components:
            component.shutdown()
        self.report.data["log"] = checks.read_log(self.log_file)
        self.report.data["exit_code"] = code
        self._write_summary()
        return code

    def _run(self) -> int:
        cfg, data = self.cfg, self.report.data
        data.update(
            {
                "isaac_sim": _isaac_version(),
                "config": cfg,
                "timing": {"startup_s": time.monotonic() - self.started},
            }
        )

        for ext in cfg["kit"]["extensions"]:
            if not app_utils.enable_extension(ext):
                self.report.check(f"extension:{ext}", False, "could not be enabled")

        stage_path = config.resolve(cfg["stage"]["path"])
        t0 = time.monotonic()
        stage = self._open_stage(stage_path)
        data["timing"]["load_s"] = time.monotonic() - t0
        self.report.check("stage_opened", stage is not None, str(stage_path))
        if stage is None:
            return EXIT_ABORTED

        data["active_prims"] = checks.active_prim_count(stage)
        data["physics_scenes"] = scenes = checks.physics_scenes(stage)
        self.report.check("physics_scene", len(scenes) == 1, f"{len(scenes)} PhysicsScene prim(s)")
        # An empty time range makes the playing timeline wrap every frame, and
        # OnPlaybackTick graphs then fire more than once per update.
        start, end = stage.GetStartTimeCode(), stage.GetEndTimeCode()
        self.report.check(
            "timeline_range", end > start, f"start/endTimeCode {start:g}/{end:g}; end must be later"
        )

        self._setup_components(Context(stage=stage, cfg=cfg))

        if cfg["run"]["mode"] == "interactive":
            return self._run_interactive()
        return self._run_play(stage)

    def _open_stage(self, path: Path) -> Usd.Stage | None:
        ctx = omni.usd.get_context()
        if not path.is_file() or not ctx.open_stage(str(path)):
            return None
        # The stage only reports loading after the first updates.
        self.kit.update()
        self.kit.update()
        while is_stage_loading():
            self.kit.update()
        return ctx.get_stage()

    def _setup_components(self, ctx: Context) -> None:
        bridge = ctx.cfg["ros_bridge"]
        if bridge["clock_topic"] or bridge["joints"]:
            self.components.append(RosBridge())
        for component in self.components:
            component.setup(ctx)
        self.kit.update()

    def _update(self, dt: float) -> None:
        for component in self.components:
            component.update(dt)
        self.kit.update()

    def _run_interactive(self) -> int:
        """Keep the editor running with the stage open until it closes or is signalled."""
        stop = StopFlag()
        dt = 1.0 / self.cfg["run"]["render_hz"]
        print("[sim] stage open; press Play to start the simulation")
        while self.kit.is_running() and not stop.set:
            self._update(dt)
        return EXIT_OK if self.report.passed else EXIT_CHECK_FAILED

    def _run_play(self, stage: Usd.Stage) -> int:
        """Play for the configured duration, then check the result."""
        cfg, data, report = self.cfg, self.report.data, self.report
        run, chk = cfg["run"], cfg["checks"]
        render_dt = 1.0 / run["render_hz"]
        # RenderingManager only applies the rate limit when it is already enabled.
        carb.settings.get_settings().set("/app/runLoops/main/rateLimitEnabled", run["realtime"])
        RenderingManager.set_dt(render_dt)
        # Keep the dt and device authored on the stage's PhysicsScene.
        SimulationManager.setup_simulation()

        probe = checks.TopicProbe(chk["topics"]) if chk["topics"] else None
        stop = StopFlag()
        app_utils.play()
        self._update(render_dt)

        data["omnigraph"] = og_status = checks.omnigraph_status(stage)
        report.check(
            "omnigraph_nodes",
            not og_status["unresolved"],
            f"{len(og_status['unresolved'])} authored node(s) did not instantiate",
        )
        report.check(
            "omnigraph_enabled",
            not og_status["disabled"],
            f"disabled graphs: {og_status['disabled']}",
        )

        arts = checks.Articulations(chk["articulations"] or checks.articulation_roots(stage))
        report.check(
            "articulations",
            not arts.missing,
            f"{len(arts.views)} found, missing: {arts.missing}",
        )

        settle_steps = math.ceil(run["settle"] / render_dt)
        total_steps = None
        if run["duration"] > 0:
            total_steps = max(math.ceil(run["duration"] / render_dt), settle_steps)
        reference = None
        steps = 0
        t0 = time.monotonic()
        sim_t0 = SimulationManager.get_simulation_time()
        while self.kit.is_running() and not stop.set:
            if total_steps is not None and steps >= total_steps:
                break
            self._update(render_dt)
            steps += 1
            if probe:
                probe.spin()
            if steps == settle_steps:
                reference = arts.root_positions()
        wall_s = time.monotonic() - t0
        sim_s = SimulationManager.get_simulation_time() - sim_t0
        data["timing"].update(
            {
                "run_wall_s": wall_s,
                "sim_s": sim_s,
                "app_updates": steps,
                "physics_steps": SimulationManager.get_num_physics_steps(),
                "rtf": sim_s / wall_s if wall_s > 0 else 0.0,
            }
        )

        data["articulations"] = arts.describe()
        for art in data["articulations"]:
            report.check(f"finite:{art['root']}", art["finite"], f"{art['dofs']} dofs")
        if reference is not None:
            final = arts.root_positions()
            for root, p0 in reference.items():
                drift = float(np.linalg.norm(final[root] - p0))
                report.check(
                    f"anchored:{root}",
                    drift < MAX_BASE_DRIFT_M,
                    f"base moved {drift * 1000:.3f} mm after the settle",
                )

        if probe:
            probe.close()
            data["ros_topics"] = probe.results(sim_s)
            min_hz = chk["min_topic_rate"] * run["render_hz"]
            for topic, info in data["ros_topics"].items():
                report.check(
                    f"ros:{topic}",
                    info["hz_sim"] >= min_hz,
                    f"{info['messages']} messages, {info['hz_sim']:.1f} Hz sim time",
                )

        app_utils.stop()
        self.kit.update()

        log = checks.read_log(self.log_file)
        if chk["max_log_errors"] >= 0:
            report.check(
                "log_errors",
                log["errors"] <= chk["max_log_errors"],
                f"{log['errors']} error(s), limit {chk['max_log_errors']}",
            )
        print(f"[sim] {log['errors']} error(s), {log['warnings']} warning(s) in {self.log_file}")
        print(
            f"[sim] sim {sim_s:.2f} s in {wall_s:.2f} s wall "
            f"(RTF {data['timing']['rtf']:.2f}), {data['active_prims']} active prims"
        )
        return EXIT_OK if report.passed else EXIT_CHECK_FAILED

    def _write_summary(self) -> None:
        if not self.cfg["output"]["summary"]:
            return
        path = config.resolve(self.cfg["output"]["summary"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.report.data, indent=2, default=str))
        print(f"[sim] summary written to {path}")


def _isaac_version() -> str:
    """Version string of the running Isaac Sim install."""
    version_file = Path(os.environ.get("ISAAC_PATH", "")) / "VERSION"
    return version_file.read_text().strip() if version_file.is_file() else "unknown"
