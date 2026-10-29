"""Physics overrides: recipe data written into a USD layer, and read back out of a stage.

Overrides are keyed by joint and link name, never by prim path, because the
importer's prim layout is not stable across versions. Values use USD units:
degrees for revolute joints, metres for prismatic joints, kilograms for mass.

Import only after SimulationApp has started.
"""

from __future__ import annotations

from pxr import Sdf, Usd, UsdPhysics

# Joint types that carry a drive, with the drive's instance name.
DRIVE_AXIS = {"PhysicsRevoluteJoint": "angular", "PhysicsPrismaticJoint": "linear"}

# Recipe key -> attribute name; drive attributes are prefixed `drive:<axis>:physics:`.
DRIVE_KEYS = {
    "stiffness": "stiffness",
    "damping": "damping",
    "max_force": "maxForce",
    "target": "targetPosition",
}
LIMIT_KEYS = {"lower": "physics:lowerLimit", "upper": "physics:upperLimit"}
JOINT_KEYS = [*DRIVE_KEYS, *LIMIT_KEYS, "drive_type"]
LINK_KEYS = ["mass"]

# Value-wise equal for extraction purposes.
TOLERANCE = 1e-6


def index(stage: Usd.Stage) -> tuple[dict[str, Usd.Prim], dict[str, Usd.Prim]]:
    """Joints and rigid-body links of a composed stage by name; names must be unique."""
    joints: dict[str, Usd.Prim] = {}
    links: dict[str, Usd.Prim] = {}
    for prim in stage.Traverse():
        if prim.IsA(UsdPhysics.Joint):
            found = joints
        elif prim.HasAPI(UsdPhysics.RigidBodyAPI):
            found = links
        else:
            continue
        if prim.GetName() in found:
            raise ValueError(f"duplicate name {prim.GetName()!r}: overrides are keyed by name")
        found[prim.GetName()] = prim
    return joints, links


def has_gains(joint: Usd.Prim) -> bool:
    """Whether a driven joint has a non-zero stiffness or damping."""
    axis = DRIVE_AXIS[joint.GetTypeName()]
    return any((read(joint, _drive_attr(axis, k)) or 0) > 0 for k in ("stiffness", "damping"))


def _drive_attr(axis: str, key: str) -> str:
    return f"drive:{axis}:physics:{key}"


def author(stage: Usd.Stage, recipe: dict, path: str) -> list[str]:
    """Write the recipe's overrides for the composed stage into a layer; returns problems."""
    problems: list[str] = []
    joints, links = index(stage)
    out = Usd.Stage.CreateNew(path)
    float_t = Sdf.ValueTypeNames.Float

    def over(prim: Usd.Prim) -> Usd.Prim:
        return out.OverridePrim(prim.GetPath())

    table = recipe.get("joints", {})
    for name in table:
        if name != "*" and name not in joints:
            problems.append(f"joints.{name}: no such joint")
    for name, joint in joints.items():
        axis = DRIVE_AXIS.get(joint.GetTypeName())
        defaults = table.get("*", {}) if axis else {}
        values = {**defaults, **table.get(name, {})}
        for key, value in values.items():
            if key not in JOINT_KEYS:
                problems.append(f"joints.{name}.{key}: unknown key")
            elif key in LIMIT_KEYS:
                over(joint).CreateAttribute(LIMIT_KEYS[key], float_t).Set(value)
            elif axis is None:
                problems.append(f"joints.{name}: {joint.GetTypeName()} has no drive")
            else:
                drive = UsdPhysics.DriveAPI.Apply(over(joint), axis)
                if key == "drive_type":
                    drive.CreateTypeAttr(value)
                else:
                    getattr(drive, f"Create{DRIVE_KEYS[key][0].upper()}{DRIVE_KEYS[key][1:]}Attr")(
                        value
                    )

    for name, values in recipe.get("links", {}).items():
        if name not in links:
            problems.append(f"links.{name}: no such rigid body")
            continue
        mass = UsdPhysics.MassAPI.Apply(over(links[name]))
        for key, value in values.items():
            if key == "mass":
                mass.CreateMassAttr(value)
            else:
                problems.append(f"links.{name}.{key}: unknown key")

    out.GetRootLayer().Save()
    return problems


def read(prim: Usd.Prim, name: str):
    """The attribute's authored or composed value, or None when it has none."""
    attribute = prim.GetAttribute(name)
    return attribute.Get() if attribute and attribute.HasValue() else None


def extract(stage: Usd.Stage, baseline: Usd.Stage) -> dict:
    """Recipe data for everything in `stage` that differs from `baseline`, by name."""
    recipe: dict = {"joints": {}, "links": {}}
    joints, links = index(stage)
    base_joints, base_links = index(baseline)

    def differs(a, b) -> bool:
        if a is None:
            return False
        if b is None or isinstance(a, str):
            return a != b
        return abs(a - b) > TOLERANCE

    for name, joint in joints.items():
        base = base_joints.get(name)
        axis = DRIVE_AXIS.get(joint.GetTypeName())
        names = {k: LIMIT_KEYS[k] for k in LIMIT_KEYS}
        if axis:
            names |= {k: _drive_attr(axis, v) for k, v in DRIVE_KEYS.items()}
            names["drive_type"] = _drive_attr(axis, "type")
        found = {}
        for key, attr_name in names.items():
            value = read(joint, attr_name)
            if differs(value, read(base, attr_name) if base else None):
                found[key] = str(value) if key == "drive_type" else float(value)
        if found:
            recipe["joints"][name] = found

    for name, link in links.items():
        mass = read(link, "physics:mass")
        base = base_links.get(name)
        if differs(mass, read(base, "physics:mass") if base else None):
            recipe["links"][name] = {"mass": float(mass)}

    return {k: v for k, v in recipe.items() if v}


def dump_toml(recipe: dict) -> str:
    """Minimal TOML writer for recipe tables (two levels of nesting, scalar values)."""
    lines = []
    for section, entries in recipe.items():
        for name, values in entries.items():
            lines.append(f'[{section}."{name}"]')
            for key, value in values.items():
                lines.append(f'{key} = "{value}"' if isinstance(value, str) else f"{key} = {value}")
            lines.append("")
    return "\n".join(lines)
