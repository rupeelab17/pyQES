#!/usr/bin/env python3
"""Minimal pyQES winds demo.

Provide a DEM (and optional buildings shapefiles). All other parameters use
sensible defaults via ``WindsParameters`` / ``SensorParameters``.

Usage (after ``uv sync`` from the repo root)::

    uv run python examples/run_winds_demo.py --dem /path/to/DEM.tif
    uv run python examples/run_winds_demo.py --dem DEM.tif --speed 5 --direction 180
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pyQES import pywinds
from pyQES.util.config import SensorParameters, TimeSeries, WindsParameters


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run QES-Winds via pyQES (demo).")
    p.add_argument("--dem", type=Path, required=True, help="Path to DEM GeoTIFF")
    p.add_argument("--work-dir", type=Path, default=Path("output"))
    p.add_argument("--solver", choices=("cpu", "gpu"), default="cpu")
    p.add_argument("--speed", type=float, default=3.0)
    p.add_argument("--direction", type=float, default=270.0)
    p.add_argument("--height", type=float, default=10.0)
    p.add_argument("--halo-x", type=float, default=40.0)
    p.add_argument("--halo-y", type=float, default=40.0)
    p.add_argument("--cell-size", type=float, nargs=3, default=(2.0, 2.0, 0.5), metavar=("DX", "DY", "DZ"))
    p.add_argument("--buildings-src", type=Path, default=None)
    p.add_argument("--buildings-mask", type=Path, default=None)
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

    result = pywinds.run(
        config=params,
        sensor=sensor,
        solver=args.solver,
        work_dir=args.work_dir,
        auto_preprocess=not args.no_preprocess,
        buildings_src=args.buildings_src,
        buildings_mask=args.buildings_mask,
    )
    print("winds_out:", result.winds_out)
    print("winds_wk:", result.winds_wk)


if __name__ == "__main__":
    main()
