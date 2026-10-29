# Asset pipeline

URDF and meshes in, layered USD out, in one command. Physics tuning is data, not hand edits.

```
recipe.toml ──┐
URDF + meshes ─┴─► import_asset.py ─► build/assets/<robot>/
                                         raw/            importer output, untouched
                                         overrides.usda  recipe → USD `over` specs
                                         <robot>.usda    references raw/, selects the Physics
                                                         variant, sublayers overrides.usda
                                         report.json     what was found, what the checks say

tuned stage ──► extract_overrides.py ──► recipe fragment (TOML)
```

```bash
pipeline/run.sh import_asset.py pipeline/examples/test_arm/recipe.toml
pipeline/run.sh extract_overrides.py build/assets/test_arm/test_arm.usda \
    --baseline build/assets/test_arm/raw/test_arm/test_arm.usda
```

Both run in the simulation container and take about 30 s. `examples/test_arm/` is a
synthetic arm with a meshed link, a fixed joint and a mimic gripper.

## Recipe

`recipe.toml` has four parts: `[asset]` (URDF, physics variant), `[import]`
(`URDFImporterConfig` fields, checked against the class), `[joints.<name>]` and
`[links.<name>]`. `[joints."*"]` sets defaults for every driven joint; a named entry wins.

| Key | Applies to | USD |
|---|---|---|
| `stiffness`, `damping`, `max_force`, `target`, `drive_type` | revolute, prismatic | `drive:<axis>:physics:*` |
| `lower`, `upper` | any limited joint | `physics:lowerLimit/upperLimit` |
| `mass` | rigid-body link | `physics:mass` |

Keys are joint and link names, never prim paths: the 6.x importer lays prims out
differently from 5.1, which is why path-based overrides stop applying after an upgrade.
Units are USD's: degrees for revolute joints.

## Checks

`import_asset.py` exits 0 when the asset is written and the checks pass, 1 when a check
fails, 2 for an unusable recipe or import. Checks: one articulation root, every drive has
non-zero stiffness or damping, every URDF joint imported. Links without a mass are listed;
the solver derives their mass from collision geometry and `link_density`.

`extract_overrides.py` is a sketch: it compares joint drives, limits and link masses of a
tuned stage against the raw import. Run on an asset built by `import_asset.py` it
reproduces the recipe, which is the round-trip check.

## What the 6.2 importer does

Observed on the test arm:

- **Layered output.** `<robot>.usda` plus `payloads/` (`base`, `robot`, `instances`,
  `geometries.usd`, and `Physics/{physx,physics,mujoco}`).
- **Physics is a variant set with no default selection.** Without selecting `physx` the
  asset has no rigid bodies, joints or articulation. The wrapper selects it.
- **Drives are applied with zero gains.** Joints are free until the recipe sets stiffness
  and damping.
- **Mass only where the URDF has `<inertial>`.** The rest is left to the solver.
- **Meshes are instanceable.** Per-collider overrides cannot be authored on instance
  proxies; the collision approximation is chosen globally by `collision_type`.
- **Articulation root on the base link**, with a `root_joint` (fixed, no rigid body on the
  parent side) anchoring it when `fix_base` is set.
- **A time range is authored** (0 to 1,000,000), which avoids the empty-range problem.
- **URDF `<mimic>` is imported as `NewtonMimicAPI`, and PhysX couples the joints.** With
  the tag the two fingers reach +0.0151 and -0.0147 m (equal drives pulling to opposite
  targets); without it they reach 0.03 and 0. No PhysX-specific mimic API is needed.
- **Re-importing into an existing folder writes `<robot>_1`.** The script clears its own
  output directory first.
- **No GPU is needed** for the import.

## Not covered yet

- Physics materials (friction, restitution): none come from the URDF. Next addition to the
  recipe.
- Per-collider approximation: needs a decision on instancing (disable it for chosen links,
  or import with `collision_from_visuals`).
- Name sanitising: hyphenated URDF names and a map back to ROS names.
- xacro expansion and `package://` resolution (`ros_package_paths`).
- Fixed-joint merging (`merge_fixed_joints`) and its effect on link names in recipes.
- Large cells: 47-axis URDF with hundreds of meshes; timing and file size.
- Gripper attachment points and other non-URDF content: authored by modules or a separate
  layer, not by this pipeline.
