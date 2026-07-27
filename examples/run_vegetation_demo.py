#!/usr/bin/env python3
"""Vegetation demo (Homogeneous / IsolatedTree / tree shapefile).

Modes:

* ``--canopy homogeneous`` (default) — one rectangular ``Homogeneous`` block
  (FlatTerrain_wCanopy style, Cionco exponential profile).
* ``--canopy isolated`` — one ``IsolatedTree`` (FlatTerrain_wIsoTree style).
* ``--trees-shp`` — point shapefile with fields H, D, LAI (overrides ``--canopy``).

Usage (after ``uv sync`` from the repo root)::

    uv run python examples/run_vegetation_demo.py
    uv run python examples/run_vegetation_demo.py --canopy isolated
    uv run python examples/run_vegetation_demo.py --trees-shp path/to/trees.shp
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pyQES import pywinds
from pyQES.util.config import (
    Homogeneous,
    IsolatedTree,
    SensorParameters,
    TimeSeries,
    VegetationParameters,
    WindsParameters,
)

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "vegetation_output"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run QES-Winds with vegetation (demo).")
    p.add_argument("--work-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--solver", choices=("cpu", "gpu"), default="cpu")
    p.add_argument("--speed", type=float, default=5.0)
    p.add_argument("--direction", type=float, default=270.0)
    p.add_argument("--height", type=float, default=10.0)
    p.add_argument(
        "--canopy",
        choices=("homogeneous", "isolated"),
        default="homogeneous",
        help="XML canopy type when --trees-shp is omitted (default: homogeneous)",
    )
    p.add_argument(
        "--trees-shp",
        type=Path,
        default=None,
        help="Point shapefile with H, D, LAI; omit for Homogeneous/IsolatedTree XML",
    )
    p.add_argument(
        "--trees-layer",
        default="trees",
        help="SHPTreeLayer name (default: trees)",
    )
    return p.parse_args()


def _vegetation(args: argparse.Namespace) -> VegetationParameters:
    if args.trees_shp is not None:
        if not args.trees_shp.is_file():
            raise SystemExit(f"Trees shapefile not found: {args.trees_shp}")
        return VegetationParameters(
            shp_file=str(args.trees_shp.resolve()),
            shp_tree_layer=args.trees_layer,
        )
    if args.canopy == "homogeneous":
        return VegetationParameters(
            num_canopies=1,
            homogeneous=[
                Homogeneous(
                    attenuation_coefficient=1.0,
                    height=10.0,
                    base_height=0.0,
                    x_start=80.0,
                    y_start=60.0,
                    length=40.0,
                    width=80.0,
                    canopy_rotation=0.0,
                )
            ],
        )
    return VegetationParameters(
        num_canopies=1,
        isolated_trees=[
            IsolatedTree(
                attenuation_coefficient=3.0,
                height=15.0,
                base_height=0.0,
                z_max_lai=0.7,
                x_center=20.0,
                y_center=100.0,
                width=10.0,
            )
        ],
    )


def main() -> None:
    args = _parse_args()

    params = WindsParameters()
    params.simulation_parameters.domain = (200, 200, 200)
    params.simulation_parameters.cell_size = (1.0, 1.0, 1.0)
    params.simulation_parameters.domain_rotation = 0.0
    params.vegetation_params = _vegetation(args)

    sensor = SensorParameters(
        site_x_coord=1.0,
        site_y_coord=1.0,
        time_series=[
            TimeSeries(
                speed=args.speed,
                direction=args.direction,
                height=args.height,
                site_z0=0.1,
                boundary_layer_flag=1,
            )
        ],
    )

    result = pywinds.run(
        config=params,
        sensor=sensor,
        solver=args.solver,
        work_dir=args.work_dir,
        auto_preprocess=False,
    )
    print("winds_out:", result.winds_out)
    print("winds_wk:", result.winds_wk)


if __name__ == "__main__":
    main()
