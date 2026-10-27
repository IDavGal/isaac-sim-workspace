"""Checks and measurements on a running stage. Import only after SimulationApp has started."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import numpy as np
import omni.graph.core as og
import omni.physics.tensors
import omni.usd
from pxr import PhysxSchema, Usd, UsdPhysics

LOG_LINE = re.compile(r"\[(Error|Warning|Fatal)\] \[([^\]]+)\] (.*)")
MAX_LOGGED_MESSAGES = 50
# Callbacks drained per app update; above the number of probed topics so none backs up.
PROBE_SPINS_PER_UPDATE = 10


class Report:
    """Run summary and pass/fail checks."""

    def __init__(self) -> None:
        self.data: dict = {"checks": []}

    def check(self, name: str, passed: bool, detail: str) -> None:
        """Record and print one check."""
        self.data["checks"].append({"name": name, "passed": bool(passed), "detail": detail})
        print(f"[sim] {'PASS' if passed else 'FAIL'} {name}: {detail}")

    @property
    def passed(self) -> bool:
        """Whether every recorded check passed."""
        return all(c["passed"] for c in self.data["checks"])


def active_prim_count(stage: Usd.Stage) -> int:
    """Active, defined, non-abstract prims outside instance prototypes."""
    pred = Usd.PrimIsActive & Usd.PrimIsDefined & ~Usd.PrimIsAbstract
    prims = Usd.PrimRange(stage.GetPseudoRoot(), pred)
    return sum(1 for prim in prims if not prim.IsInPrototype())


def physics_scenes(stage: Usd.Stage) -> list[dict]:
    """Solver settings of each PhysicsScene on the stage."""
    scenes = []
    for prim in stage.Traverse():
        if not prim.IsA(UsdPhysics.Scene):
            continue
        physx = PhysxSchema.PhysxSceneAPI(prim)
        scenes.append(
            {
                "path": str(prim.GetPath()),
                "time_steps_per_second": physx.GetTimeStepsPerSecondAttr().Get(),
                "solver": physx.GetSolverTypeAttr().Get(),
                "broadphase": physx.GetBroadphaseTypeAttr().Get(),
                "gpu_dynamics": physx.GetEnableGPUDynamicsAttr().Get(),
            }
        )
    return scenes


def articulation_roots(stage: Usd.Stage) -> list[str]:
    """Paths of the active prims carrying ArticulationRootAPI."""
    return [str(p.GetPath()) for p in stage.Traverse() if p.HasAPI(UsdPhysics.ArticulationRootAPI)]


def omnigraph_status(stage: Usd.Stage) -> dict:
    """Authored nodes that did not instantiate, runtime node types and disabled graphs."""
    graphs = og.get_all_graphs() or []
    unresolved, counts = [], {}
    for prim in stage.Traverse():
        if prim.GetTypeName() != "OmniGraphNode":
            continue
        node = og.get_node_by_path(str(prim.GetPath()))
        if not node or not node.is_valid():
            unresolved.append(
                {"path": str(prim.GetPath()), "type": prim.GetAttribute("node:type").Get()}
            )
            continue
        runtime_type = node.get_type_name()
        counts[runtime_type] = counts.get(runtime_type, 0) + 1
    return {
        "graphs": len(graphs),
        "disabled": [g.get_path_to_graph() for g in graphs if g.is_disabled()],
        "node_types": counts,
        "unresolved": unresolved,
    }


def read_log(path: Path) -> dict:
    """Errors and warnings in the Kit log."""
    errors, warnings = [], []
    if path.is_file():
        for line in path.read_text(errors="replace").splitlines():
            m = LOG_LINE.search(line)
            if not m:
                continue
            level, channel, msg = m.groups()
            (warnings if level == "Warning" else errors).append(f"[{channel}] {msg}")
    return {
        "file": str(path),
        "errors": len(errors),
        "warnings": len(warnings),
        "first_errors": errors[:MAX_LOGGED_MESSAGES],
        "first_warnings": warnings[:MAX_LOGGED_MESSAGES],
    }


class Articulations:
    """Joint and root state of each articulation, read through the physics tensor API."""

    def __init__(self, roots: list[str]) -> None:
        stage_id = omni.usd.get_context().get_stage_id()
        self._sim_view = omni.physics.tensors.create_simulation_view("numpy", stage_id=stage_id)
        self.views, self.missing = {}, []
        for root in roots:
            view = self._sim_view.create_articulation_view(root)
            try:
                found = view is not None and view.count > 0
            except AttributeError:  # no match: the view comes back without a backend
                found = False
            if found:
                self.views[root] = view
            else:
                self.missing.append(root)

    def root_positions(self) -> dict[str, np.ndarray]:
        """World position of each articulation's root link."""
        return {r: v.get_root_transforms()[0, :3].copy() for r, v in self.views.items()}

    def describe(self) -> list[dict]:
        """DOF names and positions of each articulation."""
        out = []
        for root, view in self.views.items():
            q = view.get_dof_positions()[0]
            out.append(
                {
                    "root": root,
                    "dofs": int(view.max_dofs),
                    "dof_names": list(view.shared_metatype.dof_names),
                    "positions": [float(x) for x in q],
                    "finite": bool(np.isfinite(q).all()),
                }
            )
        return out


class TopicProbe:
    """Counts messages on ROS topics from inside the sim process."""

    def __init__(self, topics: list[dict]) -> None:
        import rclpy
        from rclpy.executors import SingleThreadedExecutor

        self._rclpy = rclpy
        # Components may already run rclpy in this process.
        self._owns_context = not rclpy.ok()
        if self._owns_context:
            rclpy.init()
        self._node = rclpy.create_node("sim_topic_probe")
        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self._node)
        self.counts = {t["name"]: 0 for t in topics}
        self.joint_names: dict[str, list[str]] = {}
        for t in topics:
            self._node.create_subscription(
                _message_type(t["type"]), t["name"], self._callback(t["name"]), 10
            )

    def _callback(self, topic: str):
        def on_msg(msg) -> None:
            self.counts[topic] += 1
            if topic not in self.joint_names and hasattr(msg, "name"):
                self.joint_names[topic] = list(msg.name)

        return on_msg

    def spin(self) -> None:
        """Handle the messages received since the last update."""
        for _ in range(PROBE_SPINS_PER_UPDATE):
            self._executor.spin_once(timeout_sec=0)

    def results(self, sim_s: float) -> dict:
        """Message count, sim-time rate and joint names per topic."""
        return {
            topic: {
                "messages": n,
                "hz_sim": n / sim_s if sim_s > 0 else 0.0,
                "joint_names": self.joint_names.get(topic),
            }
            for topic, n in self.counts.items()
        }

    def close(self) -> None:
        """Shut down the probe's ROS node."""
        self._node.destroy_node()
        if self._owns_context:
            self._rclpy.shutdown()


def _message_type(name: str):
    """The message class for a `package/msg/Type` name."""
    package, _, type_name = name.split("/")
    return getattr(importlib.import_module(f"{package}.msg"), type_name)
