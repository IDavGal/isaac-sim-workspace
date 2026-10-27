"""ROS 2 bridge built from the configuration: sim clock and per-articulation joint I/O.

Builds one OmniGraph action graph at setup, so the bridge is defined by the
scenario configuration rather than authored into the stage. For each configured
articulation it publishes sensor_msgs/JointState and applies the position,
velocity and effort commands received as JointState to the joint drives.
"""

from __future__ import annotations

import omni.graph.core as og
import usdrt

from sim.components.base import Component, Context

GRAPH_PATH = "/SimROSBridge"


class RosBridge(Component):
    """Publishes the sim clock and joint states, and applies joint commands."""

    def setup(self, ctx: Context) -> None:
        """Create the bridge graph for the configured clock topic and articulations."""
        cfg = ctx.cfg["ros_bridge"]
        nodes = [
            ("OnTick", "omni.graph.action.OnPlaybackTick"),
            ("Context", "isaacsim.ros2.bridge.ROS2Context"),
        ]
        connect = []
        values = [("Context.inputs:useDomainIDEnvVar", True)]

        if cfg["clock_topic"]:
            nodes += [
                ("ReadSimTime", "isaacsim.core.nodes.IsaacReadSimulationTime"),
                ("PublishClock", "isaacsim.ros2.bridge.ROS2PublishClock"),
            ]
            connect += [
                ("OnTick.outputs:tick", "PublishClock.inputs:execIn"),
                ("Context.outputs:context", "PublishClock.inputs:context"),
                ("ReadSimTime.outputs:simulationTime", "PublishClock.inputs:timeStamp"),
            ]
            values.append(("PublishClock.inputs:topicName", cfg["clock_topic"]))

        for i, joints in enumerate(cfg["joints"]):
            nodes_i, connect_i, values_i = _joint_io(f"J{i}", joints)
            nodes += nodes_i
            connect += connect_i
            values += values_i

        og.Controller.edit(
            {"graph_path": GRAPH_PATH, "evaluator_name": "execution"},
            {
                og.Controller.Keys.CREATE_NODES: nodes,
                og.Controller.Keys.CONNECT: connect,
                og.Controller.Keys.SET_VALUES: values,
            },
        )


def _joint_io(prefix: str, joints: dict) -> tuple[list, list, list]:
    """Nodes, connections and values for one articulation's state and command topics."""
    read, pub = f"{prefix}Read", f"{prefix}Publish"
    sub, ctrl = f"{prefix}Subscribe", f"{prefix}Controller"
    articulation = joints["articulation"]
    nodes = [
        (read, "isaacsim.sensors.physics.IsaacReadJointState"),
        (pub, "isaacsim.ros2.bridge.ROS2PublishJointState"),
        (sub, "isaacsim.ros2.bridge.ROS2SubscribeJointState"),
        (ctrl, "isaacsim.core.nodes.IsaacArticulationController"),
    ]
    state_fields = [
        "jointNames",
        "jointPositions",
        "jointVelocities",
        "jointEfforts",
        "jointDofTypes",
        "stageMetersPerUnit",
        "sensorTime",
    ]
    command_fields = ["jointNames", "positionCommand", "velocityCommand", "effortCommand"]
    connect = [
        ("OnTick.outputs:tick", f"{read}.inputs:execIn"),
        (f"{read}.outputs:execOut", f"{pub}.inputs:execIn"),
        ("Context.outputs:context", f"{pub}.inputs:context"),
        *[(f"{read}.outputs:{f}", f"{pub}.inputs:{f}") for f in state_fields],
        ("OnTick.outputs:tick", f"{sub}.inputs:execIn"),
        ("Context.outputs:context", f"{sub}.inputs:context"),
        ("OnTick.outputs:tick", f"{ctrl}.inputs:execIn"),
        *[(f"{sub}.outputs:{f}", f"{ctrl}.inputs:{f}") for f in command_fields],
    ]
    values = [
        (f"{read}.inputs:prim", [usdrt.Sdf.Path(articulation)]),
        (f"{ctrl}.inputs:robotPath", articulation),
        (f"{pub}.inputs:topicName", joints["state_topic"]),
        (f"{sub}.inputs:topicName", joints["command_topic"]),
    ]
    return nodes, connect, values
