"""Sketch: read physics overrides back out of a tuned stage, as recipe data.

    pipeline/run.sh extract_overrides.py TUNED.usda --baseline RAW.usda [--physics physx]

Compares joint drives, limits and link masses in TUNED against BASELINE (the
importer's raw output) and prints the differences as recipe TOML, keyed by joint
and link name. Run on an asset built by import_asset.py it reproduces the recipe,
which is the round-trip check; run on a hand-tuned scene it gives the starting
point for that asset's recipe.
"""

from __future__ import annotations

import argparse
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]


def main() -> None:
    """Print the recipe overrides found in the tuned stage."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("tuned", type=Path)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--physics", default="physx", help="Physics variant to select on the baseline")
    args = p.parse_args()

    from isaacsim import SimulationApp

    kit = SimulationApp({"headless": True})
    import overrides
    from pxr import Usd

    tuned = Usd.Stage.Open(str(WORKSPACE / args.tuned))
    baseline = Usd.Stage.Open(str(WORKSPACE / args.baseline))
    variants = baseline.GetDefaultPrim().GetVariantSets()
    variants.GetVariantSet("Physics").SetVariantSelection(args.physics)
    print(overrides.dump_toml(overrides.extract(tuned, baseline)))
    kit.close()


if __name__ == "__main__":
    main()
