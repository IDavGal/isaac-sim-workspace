"""Import a URDF into a layered USD asset and apply the recipe's physics overrides.

    pipeline/run.sh import_asset.py pipeline/examples/test_arm/recipe.toml [--out build/assets]

Writes <out>/<robot>/:
    raw/            the importer's output, untouched
    overrides.usda  the recipe's overrides as USD `over` specs
    <robot>.usda    the asset: references raw/, selects the Physics variant,
                    sublayers overrides.usda
    report.json     importer settings, what was found and what the checks say

Exit status: 0 when the asset is written and every check passes, 1 when a check
fails, 2 when the recipe or the import is unusable.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    """Parse the command line."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("recipe", type=Path)
    p.add_argument("--out", type=Path, default=Path("build/assets"))
    args = p.parse_args()
    args.recipe = WORKSPACE / args.recipe
    args.out = WORKSPACE / args.out
    return args


def fail(message: str) -> None:
    """Report an unusable recipe or import and exit."""
    print(f"[import] {message}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    """Run the import for the recipe."""
    args = parse_args()
    recipe = tomllib.loads(args.recipe.read_text())
    urdf = args.recipe.parent / recipe["asset"]["urdf"]
    robot = ET.parse(urdf).getroot().get("name") or fail(f"{urdf} has no robot name")
    out_dir = args.out / robot
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)

    from isaacsim import SimulationApp

    kit = SimulationApp(
        {
            "headless": True,
            "extra_args": ["--/app/renderer/enabled=false", "--/renderer/enabled=false"],
        }
    )
    try:
        code = build(kit, recipe, urdf, robot, out_dir)
    except Exception as e:  # noqa: BLE001 -- the app must still close with a failure status
        print(f"[import] failed: {e!r}", file=sys.stderr)
        code = 2
    kit.close(exit_code=code)


def build(kit, recipe: dict, urdf: Path, robot: str, out_dir: Path) -> int:
    """Import, write the layers and check the result; returns the exit status."""
    import overrides
    from isaacsim.core.experimental.utils import app as app_utils
    from pxr import Sdf, Usd, UsdPhysics

    app_utils.enable_extension("isaacsim.asset.importer.urdf")
    kit.update()
    from isaacsim.asset.importer.urdf import URDFImporter, URDFImporterConfig

    fields = {f.name for f in dataclasses.fields(URDFImporterConfig)}
    options = recipe.get("import", {})
    if unknown := set(options) - fields:
        fail(f"[import] has unknown keys: {sorted(unknown)}")
    config = URDFImporterConfig(urdf_path=str(urdf), usd_path=str(out_dir / "raw"), **options)
    raw = Path(URDFImporter(config).import_urdf())
    print(f"[import] importer wrote {raw.relative_to(out_dir)}")

    # The asset: the raw import with a physics variant selected and the overrides on top.
    asset_path = out_dir / f"{robot}.usda"
    asset = Usd.Stage.CreateNew(str(asset_path))
    raw_stage = Usd.Stage.Open(str(raw))
    for key in ("startTimeCode", "endTimeCode"):
        asset.SetMetadata(key, raw_stage.GetMetadata(key))
    asset.SetMetadata("metersPerUnit", raw_stage.GetMetadata("metersPerUnit"))
    asset.SetMetadata("upAxis", raw_stage.GetMetadata("upAxis"))
    prim = asset.DefinePrim(f"/{robot}", "Xform")
    prim.GetReferences().AddReference(Sdf.Reference(f"./{raw.relative_to(out_dir)}"))
    variant = recipe["asset"].get("physics", "physx")
    prim.GetVariantSets().GetVariantSet("Physics").SetVariantSelection(variant)
    asset.SetDefaultPrim(prim)

    problems = overrides.author(asset, recipe, str(out_dir / "overrides.usda"))
    asset.GetRootLayer().subLayerPaths.append("./overrides.usda")
    asset.GetRootLayer().Save()
    for problem in problems:
        print(f"[import] recipe: {problem}", file=sys.stderr)
    if problems:
        return 2

    # Re-open so the checks see the finished composition.
    final = Usd.Stage.Open(str(asset_path))
    joints, links = overrides.index(final)
    roots = [
        p.GetPath().pathString for p in final.Traverse() if p.HasAPI(UsdPhysics.ArticulationRootAPI)
    ]
    driven = {n: j for n, j in joints.items() if j.GetTypeName() in overrides.DRIVE_AXIS}
    mimics = {n: [s for s in j.GetAppliedSchemas() if "Mimic" in s] for n, j in joints.items()}
    report = {
        "robot": robot,
        "importer": dataclasses.asdict(config),
        "variant": variant,
        "articulation_roots": roots,
        "joints": {n: j.GetTypeName() for n, j in joints.items()},
        "links": {n: overrides.read(p, "physics:mass") for n, p in links.items()},
        "mimic": {n: s for n, s in mimics.items() if s},
    }

    checks = {
        "one_articulation_root": len(roots) == 1,
        "every_drive_has_gains": all(overrides.has_gains(j) for j in driven.values()),
        "urdf_joints_all_imported": len(joints) >= len(ET.parse(urdf).getroot().findall("joint")),
    }
    report["checks"] = checks
    report["massless_links"] = sorted(n for n, m in report["links"].items() if not m)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str))

    for name, ok in checks.items():
        print(f"[import] {'PASS' if ok else 'FAIL'} {name}")
    if report["massless_links"]:
        print(f"[import] note: mass left to the solver for {report['massless_links']}")
    print(f"[import] asset: {asset_path.relative_to(WORKSPACE)}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    main()
