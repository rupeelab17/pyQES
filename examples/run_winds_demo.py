#!/usr/bin/env python3
"""Minimal pyQES winds demo (defaults to examples/umep_workflow).

Usage (after ``uv sync`` from the repo root)::

    uv run python examples/run_winds_demo.py
    uv run python examples/run_winds_demo.py --speed 5 --direction 180
    uv run python examples/run_winds_demo.py --dem /path/to/DEM.tif
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pyQES import pywinds
from pyQES.util.config import SensorParameters, TimeSeries, WindsParameters

HERE = Path(__file__).resolve().parent
UMEP = HERE / "umep_workflow"
DEFAULT_DEM = UMEP / "DEM_clip.tif"
DEFAULT_BUILDINGS = UMEP / "buildings.shp"
DEFAULT_MASK = UMEP / "mask.shp"
DEFAULT_OUT = UMEP / "output"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run QES-Winds via pyQES (demo).")
    p.add_argument("--dem", type=Path, default=DEFAULT_DEM, help="Path to DEM GeoTIFF")
    p.add_argument("--work-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--solver", choices=("cpu", "gpu"), default="cpu")
    p.add_argument("--speed", type=float, default=3.0)
    p.add_argument("--direction", type=float, default=270.0)
    p.add_argument("--height", type=float, default=10.0)
    p.add_argument("--halo-x", type=float, default=40.0)
    p.add_argument("--halo-y", type=float, default=40.0)
    p.add_argument(
        "--cell-size",
        type=float,
        nargs=3,
        default=(2.0, 2.0, 0.5),
        metavar=("DX", "DY", "DZ"),
    )
    p.add_argument("--buildings-src", type=Path, default=DEFAULT_BUILDINGS)
    p.add_argument("--buildings-mask", type=Path, default=DEFAULT_MASK)
    p.add_argument("--no-preprocess", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    if not args.dem.is_file():
        raise SystemExit(f"DEM not found: {args.dem}")

    params = WindsParameters()
    params.simulation_parameters.dem = str(args.dem.resolve())
    params.simulation_parameters.cell_size = tuple(args.cell_size)
    params.simulation_parameters.halo_x = args.halo_x
    params.simulation_parameters.halo_y = args.halo_y
    params.simulation_parameters.domain_rotation = 0.0

    sensor = SensorParameters(
        time_series=[
            TimeSeries(
                speed=args.speed,
                direction=args.direction,
                height=args.height,
                site_z0=0.24,
            )
        ]
    )

    buildings_src = args.buildings_src if args.buildings_src and args.buildings_src.is_file() else None
    buildings_mask = args.buildings_mask if args.buildings_mask and args.buildings_mask.is_file() else None

    result = pywinds.run(
        config=params,
        sensor=sensor,
        solver=args.solver,
        work_dir=args.work_dir,
        auto_preprocess=not args.no_preprocess,
        buildings_src=buildings_src,
        buildings_mask=buildings_mask,
    )
    print("winds_out:", result.winds_out)
    print("winds_wk:", result.winds_wk)


if __name__ == "__main__":
    main()
