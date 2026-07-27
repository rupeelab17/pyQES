#!/usr/bin/env python3
"""Fetch DEM / buildings / mask via pymdurs (IGN), then run QES-Winds.

Requires network access and a bbox in mainland France (IGN). Prerequisites::

    uv sync --extra geo --extra io
    uv pip install pymdurs

Usage (from the repo root)::

    uv run python examples/pymdurs_workflow/run_from_bbox.py --to-tif
    uv run python examples/pymdurs_workflow/run_from_bbox.py \\
        --bbox=-1.152704,46.181627,-1.139893,46.18699 --to-tif --to-streamlines --to-flowlines
    # reuse previous IGN downloads:
    uv run python examples/pymdurs_workflow/run_from_bbox.py --skip-fetch --to-tif

Note: fine horizontal grids (e.g. ``--cell-size 2 2 0.5``) on this default
bbox can segfault in the native QES solver (~8M+ cells). Prefer the default
``2.5 2.5 1`` or coarser. Do not resample the DEM to cell size — QES crashes
on some warped GeoTIFFs; keep the native IGN clip resolution.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pymdurs
from pyQES import pywinds
from pyQES.util import geo
from pyQES.util.config import SensorParameters, TimeSeries, WindsParameters

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "output"
DEFAULT_BBOX = (-1.152704, 46.181627, -1.139893, 46.18699)
WORKING_CRS = 2154
# Empirically, ~8M cells segfaults on typical laptop builds; keep a margin.
MAX_DOMAIN_CELLS = 6_000_000

# Candidate attribute names produced by IGN / pymdurs for building height (m).
_HEIGHT_CANDIDATES = (
    "hauteur",
    "height",
    "HAUTEUR",
    "hauteur_mean",
    "H_MEDIANE",
    "H_MAX",
)


def _parse_bbox(raw: str) -> tuple[float, float, float, float]:
    """Parse ``minx,miny,maxx,maxy`` (WGS84) into a float tuple."""
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            f"bbox must be minx,miny,maxx,maxy (got {raw!r})"
        )
    try:
        minx, miny, maxx, maxy = (float(p) for p in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"bbox values must be floats: {raw!r}") from exc
    if minx >= maxx or miny >= maxy:
        raise argparse.ArgumentTypeError(f"bbox min must be < max: {raw!r}")
    return minx, miny, maxx, maxy


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Download IGN DEM/buildings/mask via pymdurs, then run QES-Winds."
    )
    p.add_argument(
        "--bbox",
        type=_parse_bbox,
        default=DEFAULT_BBOX,
        metavar="MINX,MINY,MAXX,MAXY",
        help=(
            "WGS84 bbox (default: La Rochelle). Use equals form when minx is "
            "negative: --bbox=-1.15,46.18,-1.14,46.19"
        ),
    )
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
        default=(2.5, 2.5, 1.0),
        metavar=("DX", "DY", "DZ"),
        help=(
            "QES cell size in metres (default: 2.5 2.5 1). "
            "Fine grids (e.g. 2 2 0.5) on large bboxes may segfault."
        ),
    )
    p.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Reuse DEM/mask/buildings already present in --work-dir (no IGN download).",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help=f"Allow domains larger than {MAX_DOMAIN_CELLS:,} cells (may segfault).",
    )
    p.add_argument(
        "--workspace",
        action="store_true",
        help="Also write windsWk.nc (larger memory footprint).",
    )
    p.add_argument(
        "--to-tif",
        action="store_true",
        help="Export |V| GeoTIFF at --tif-z m AGL after the run (needs pyqes[geo,io])",
    )
    p.add_argument(
        "--to-streamlines",
        action="store_true",
        help=(
            "Export u/v arrow GeoJSON at --tif-z m AGL after the run "
            "(needs pyqes[geo,io]; MapLibre icon-rotate bearing)"
        ),
    )
    p.add_argument(
        "--to-flowlines",
        action="store_true",
        help=(
            "Export RK4 streamline GeoJSON (LineStrings) at --tif-z m AGL "
            "(needs pyqes[geo,io]; MapLibre symbol-placement:line)"
        ),
    )
    p.add_argument(
        "--tif-z",
        type=float,
        default=1.5,
        help="AGL height for --to-tif / --to-streamlines / --to-flowlines",
    )
    return p.parse_args()


def _ensure_hauteur(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Ensure a ``hauteur`` column exists for QES building preprocessing."""
    if "hauteur" in gdf.columns:
        return gdf
    for name in _HEIGHT_CANDIDATES:
        if name in gdf.columns:
            gdf = gdf.copy()
            gdf["hauteur"] = gdf[name]
            return gdf
    raise SystemExit(
        "No building height attribute found. Expected one of: "
        + ", ".join(_HEIGHT_CANDIDATES)
        + f". Got columns: {list(gdf.columns)}"
    )


def fetch_dem(
    work_dir: Path, bbox: tuple[float, float, float, float]
) -> tuple[Path, Path]:
    """Download DEM GeoTIFF and mask shapefile from IGN via pymdurs."""
    dem = pymdurs.geometric.Dem(output_path=str(work_dir))
    dem.set_bbox(*bbox)
    dem.set_crs(WORKING_CRS)
    dem = dem.run()
    dem_tif = Path(dem.get_path_save_tiff())
    mask_shp = Path(dem.get_path_save_mask())
    if not dem_tif.is_file():
        raise SystemExit(f"DEM download failed: {dem_tif}")
    if not mask_shp.is_file():
        raise SystemExit(f"Mask download failed: {mask_shp}")
    return dem_tif, mask_shp


def project_dem_to_meters(dem_path: Path, epsg: int = WORKING_CRS) -> Path:
    """Reproject DEM to a metric CRS so QES domain sizing uses metres.

    ``pymdurs.Dem`` often writes a GeoTIFF still georeferenced in WGS84 degrees
    even after ``set_crs(2154)``. Treating degrees as metres yields a ~1×1 domain.
    """
    import rasterio
    from rasterio.warp import Resampling, calculate_default_transform, reproject

    out_path = dem_path.with_name(f"DEM_{epsg}.tif")
    with rasterio.open(dem_path) as src:
        src_epsg = src.crs.to_epsg() if src.crs is not None else None
        if src.crs is not None and not src.crs.is_geographic and src_epsg == epsg:
            return dem_path

        dst_crs = f"EPSG:{epsg}"
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        profile = src.meta.copy()
        profile.update(crs=dst_crs, transform=transform, width=width, height=height)

        with rasterio.open(out_path, "w", **profile) as dst:
            for band_idx in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, band_idx),
                    destination=rasterio.band(dst, band_idx),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=Resampling.bilinear,
                )
    return out_path


def clip_dem_to_mask(dem_path: Path, mask_shp: Path, out_path: Path) -> Path:
    """Clip a projected DEM to the mask polygon (smaller QES domain)."""
    import rasterio
    from rasterio.mask import mask as rio_mask

    mask_gdf = gpd.read_file(mask_shp)
    with rasterio.open(dem_path) as src:
        if mask_gdf.crs is not None and src.crs is not None:
            mask_gdf = mask_gdf.to_crs(src.crs)
        data, transform = rio_mask(src, mask_gdf.geometry, crop=True, filled=True)
        profile = src.profile.copy()
        profile.update(
            height=data.shape[1],
            width=data.shape[2],
            transform=transform,
        )
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(data)
    return out_path


def fetch_buildings(
    work_dir: Path, bbox: tuple[float, float, float, float]
) -> Path:
    """Download buildings from IGN and write ``buildings.shp`` (EPSG:2154)."""
    buildings = pymdurs.geometric.Building(
        output_path=str(work_dir),
        defaultStoreyHeight=3.0,
    )
    buildings.set_bbox(*bbox)
    buildings.set_crs(WORKING_CRS)
    buildings = buildings.run()

    geojson = buildings.get_geojson()
    features = geojson.get("features", []) if geojson else []
    if not features:
        raise SystemExit("No buildings returned for this bbox.")

    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    gdf = gdf.to_crs(epsg=WORKING_CRS)
    gdf = _ensure_hauteur(gdf)

    out_shp = work_dir / "buildings.shp"
    gdf.to_file(out_shp, driver="ESRI Shapefile")
    return out_shp


def resolve_inputs(
    work_dir: Path,
    bbox: tuple[float, float, float, float],
    *,
    skip_fetch: bool,
) -> tuple[Path, Path, Path]:
    """Return ``(dem_clip, mask, buildings)``, fetching from IGN unless skipped."""
    mask_shp = work_dir / "mask.shp"
    buildings_shp = work_dir / "buildings.shp"
    dem_clip = work_dir / "DEM_clip.tif"
    dem_2154 = work_dir / f"DEM_{WORKING_CRS}.tif"

    if skip_fetch:
        if not dem_clip.is_file() and dem_2154.is_file() and mask_shp.is_file():
            clip_dem_to_mask(dem_2154, mask_shp, dem_clip)
        missing = [p for p in (dem_clip, mask_shp, buildings_shp) if not p.is_file()]
        if missing:
            raise SystemExit(
                "--skip-fetch requires existing files, missing: "
                + ", ".join(str(p) for p in missing)
            )
        return dem_clip, mask_shp, buildings_shp

    print("Fetching DEM + mask from IGN (pymdurs)...")
    dem_tif, mask_shp = fetch_dem(work_dir, bbox)
    print(f"DEM (raw): {dem_tif}")
    print(f"mask:      {mask_shp}")

    dem_tif = project_dem_to_meters(dem_tif)
    print(f"DEM (m):   {dem_tif}")

    dem_clip = clip_dem_to_mask(dem_tif, mask_shp, work_dir / "DEM_clip.tif")
    print(f"DEM clip:  {dem_clip}")

    print("Fetching buildings from IGN (pymdurs)...")
    buildings_shp = fetch_buildings(work_dir, bbox)
    print(f"buildings: {buildings_shp}")
    return dem_clip, mask_shp, buildings_shp


def check_domain_size(
    params: WindsParameters,
    dem: Path,
    buildings: Path,
    *,
    force: bool,
) -> tuple[int, int, int]:
    """Print domain size and abort if the mesh is dangerously large."""
    domain = geo.compute_domain_cells(params, dem, buildings)
    n_cells = domain[0] * domain[1] * domain[2]
    print(f"domain:       {domain[0]} x {domain[1]} x {domain[2]}  ({n_cells:,} cells)")
    if n_cells > MAX_DOMAIN_CELLS and not force:
        raise SystemExit(
            f"Domain too large ({n_cells:,} cells > {MAX_DOMAIN_CELLS:,}). "
            "Increase --cell-size (e.g. 2.5 2.5 1 or 5 5 1), shrink --bbox, "
            "or pass --force (may segfault in the native solver)."
        )
    return domain


def run_winds(
    *,
    dem: Path,
    buildings_src: Path,
    buildings_mask: Path,
    work_dir: Path,
    args: argparse.Namespace,
) -> object:
    """Build README-style config and run QES-Winds."""
    params = WindsParameters()
    params.simulation_parameters.dem = str(dem.resolve())
    params.simulation_parameters.cell_size = tuple(args.cell_size)
    params.simulation_parameters.halo_x = args.halo_x
    params.simulation_parameters.halo_y = args.halo_y
    params.simulation_parameters.domain_rotation = 0.0
    params.buildings_params.shp_height_field = "hauteur"
    params.buildings_params.shp_building_layer = "buildings_clipped"

    check_domain_size(params, dem, buildings_src, force=args.force)

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

    return pywinds.run(
        config=params,
        sensor=sensor,
        solver=args.solver,
        work_dir=work_dir,
        auto_preprocess=True,
        workspace=args.workspace,
        buildings_src=buildings_src,
        buildings_mask=buildings_mask,
    )


def main() -> None:
    args = _parse_args()
    work_dir = args.work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    print(f"bbox (WGS84): {args.bbox}")
    print(f"work_dir:     {work_dir}")
    print(f"cell_size:    {tuple(args.cell_size)}")

    dem_tif, mask_shp, buildings_shp = resolve_inputs(
        work_dir, args.bbox, skip_fetch=args.skip_fetch
    )
    if args.skip_fetch:
        print(f"DEM clip:  {dem_tif}")
        print(f"mask:      {mask_shp}")
        print(f"buildings: {buildings_shp}")

    print("Running QES-Winds...")
    result = run_winds(
        dem=dem_tif,
        buildings_src=buildings_shp,
        buildings_mask=mask_shp,
        work_dir=work_dir,
        args=args,
    )
    print("winds_out:", result.winds_out)
    if result.winds_wk:
        print("winds_wk:", result.winds_wk)

    if args.to_tif:
        tif = pywinds.to_tif(z=args.tif_z, verbose=True, mask_buildings=False)
        print("tif:", tif)

    if args.to_streamlines:
        gj = pywinds.to_streamlines(z=args.tif_z, verbose=True, mask_buildings=False)
        print("streamlines:", gj)

    if args.to_flowlines:
        fl = pywinds.to_flowlines(z=args.tif_z, verbose=True, mask_buildings=False)
        print("flowlines:", fl)


if __name__ == "__main__":
    main()
