#!/usr/bin/env python3
"""Fetch DEM / buildings / trees / mask via pymdurs (IGN), then run QES-Winds.

Requires network access and a bbox in mainland France (IGN). Prerequisites::

    uv sync --extra geo --extra io
    uv pip install pymdurs

Usage (from the repo root)::

    uv run python examples/pymdurs_workflow/run_from_bbox.py --to-tif
    uv run python examples/pymdurs_workflow/run_from_bbox.py \\
        --bbox=-1.152704,46.181627,-1.139893,46.18699 --to-tif --to-streamlines --to-flowlines
    # reuse previous IGN / LiDAR downloads:
    uv run python examples/pymdurs_workflow/run_from_bbox.py --skip-fetch --to-tif
    # skip vegetation entirely:
    uv run python examples/pymdurs_workflow/run_from_bbox.py --no-trees --to-tif

Note: fine horizontal grids (e.g. ``--cell-size 2 2 0.5``) on this default
bbox can segfault in the native QES solver (~8M+ cells). Prefer the default
``2.5 2.5 1`` or coarser. Do not resample the DEM to cell size — QES crashes
on some warped GeoTIFFs; keep the native IGN clip resolution.

LiDAR tree extraction is heavier than DEM/buildings (COPC download + CHM).
QES reads crown **polygons** (fields ``H``, ``D``, ``LAI``); point tops from
pymdurs are buffered to circles before the run.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pymdurs
from pymdurs.trees import run_trees
from pyQES import pywinds
from pyQES.util import geo
from pyQES.util.config import (
    SensorParameters,
    TimeSeries,
    VegetationParameters,
    WindsParameters,
)

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "output"
DEFAULT_BBOX = (-1.152704, 46.181627, -1.139893, 46.18699)
WORKING_CRS = 2154
# Empirically, ~8M cells segfaults on typical laptop builds; keep a margin.
MAX_DOMAIN_CELLS = 6_000_000

TREES_POINTS_NAME = "trees_points.shp"
TREES_QES_NAME = "trees.shp"
TREES_LAYER = "trees"
_TREE_REQUIRED_FIELDS = ("H", "D", "LAI")

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
        description=(
            "Download IGN DEM/buildings/trees/mask via pymdurs, then run QES-Winds."
        )
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
        help=(
            "Reuse DEM/mask/buildings/trees already present in --work-dir "
            "(no IGN / LiDAR download)."
        ),
    )
    p.add_argument(
        "--no-trees",
        action="store_true",
        help="Skip LiDAR tree fetch and omit vegetationParams.",
    )
    p.add_argument(
        "--lai",
        type=float,
        default=4.0,
        help="Constant LAI written to every tree (default: 4.0).",
    )
    p.add_argument(
        "--trees-resolution",
        type=float,
        default=1.0,
        help="CHM pixel size in metres for LiDAR tree extraction (default: 1.0).",
    )
    p.add_argument(
        "--min-tree-height",
        type=float,
        default=2.0,
        help="Minimum canopy height (m) for tree extraction (default: 2.0).",
    )
    p.add_argument(
        "--max-tree-height",
        type=float,
        default=30.0,
        help=(
            "Drop CHM outliers taller than this (m) before QES "
            "(default: 30; avoids domain/k_start crashes)."
        ),
    )
    p.add_argument(
        "--trees-min-spacing",
        type=float,
        default=50.0,
        help=(
            "Keep tallest trees with at least this spacing (m). Dense LiDAR "
            "crowns blank near-ground wind under IsolatedTree; 0 disables "
            "thinning (default: 50 ≈ ≤100 trees on the sample bbox)."
        ),
    )
    p.add_argument(
        "--tree-wake",
        action="store_true",
        help=(
            "Enable isolated-tree wake (wakeFlag=1). Off by default: with "
            "many crowns the wake model (11×H) blanks the wind field."
        ),
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


def fetch_trees(
    work_dir: Path,
    bbox: tuple[float, float, float, float],
    *,
    lai: float,
    resolution: float,
    min_tree_height: float,
    min_distance: int = 5,
) -> Path:
    """Download LiDAR CHM and write point tops ``trees_points.shp`` (EPSG:2154)."""
    lidar = pymdurs.geometric.Lidar(output_path=str(work_dir))
    lidar.set_bbox(*bbox)
    lidar.set_crs(WORKING_CRS)
    return Path(
        run_trees(
            lidar,
            file_name=TREES_POINTS_NAME,
            resolution=resolution,
            min_tree_height=min_tree_height,
            min_distance=min_distance,
            lai=lai,
        )
    )


def _thin_trees_by_spacing(gdf: gpd.GeoDataFrame, min_spacing: float) -> gpd.GeoDataFrame:
    """Keep tallest trees first; drop any within ``min_spacing`` of a kept tree."""
    if min_spacing <= 0 or gdf.empty:
        return gdf
    ordered = gdf.sort_values("H", ascending=False)
    kept_idx: list[object] = []
    kept_pts: list[tuple[float, float]] = []
    spacing2 = float(min_spacing) ** 2
    for idx, row in ordered.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        c = geom.centroid
        x, y = float(c.x), float(c.y)
        if any((x - kx) ** 2 + (y - ky) ** 2 < spacing2 for kx, ky in kept_pts):
            continue
        kept_idx.append(idx)
        kept_pts.append((x, y))
    out = gdf.loc[kept_idx].copy()
    print(
        f"Thinned trees: {len(gdf)} → {len(out)} "
        f"(min spacing {min_spacing:g} m, prefer taller)."
    )
    return out


def prepare_trees_shp(
    points_shp: Path,
    mask_shp: Path,
    out_shp: Path,
    *,
    max_tree_height: float | None = 30.0,
    min_spacing: float = 50.0,
) -> Path | None:
    """Convert point tops to crown polygons, clip to mask, write ``trees.shp``.

    QES ``ESRIShapefile`` only keeps polygon geometries; point features are
    ignored. Crowns are circles of radius ``D/2``. Returns ``None`` if no trees
    remain after clipping. ``max_tree_height`` drops CHM outliers; ``min_spacing``
    thins dense crowns (IsolatedTree is not meant for a closed canopy).
    """
    gdf = gpd.read_file(points_shp)
    missing = [f for f in _TREE_REQUIRED_FIELDS if f not in gdf.columns]
    if missing:
        raise SystemExit(
            f"Tree shapefile missing fields {missing}. "
            f"Got columns: {list(gdf.columns)}"
        )

    n_in = len(gdf)
    if max_tree_height is not None:
        gdf = gdf[gdf["H"] <= float(max_tree_height)].copy()
        n_drop = n_in - len(gdf)
        if n_drop:
            print(
                f"Warning: dropped {n_drop} trees with H > {max_tree_height} m "
                "(CHM outliers)."
            )

    mask_gdf = gpd.read_file(mask_shp)
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=WORKING_CRS)
    if mask_gdf.crs is not None and gdf.crs != mask_gdf.crs:
        gdf = gdf.to_crs(mask_gdf.crs)

    # Buffer Point → Polygon crown; leave existing polygons unchanged.
    if not gdf.empty:
        geom_types = set(gdf.geometry.geom_type.unique())
        if "Point" in geom_types or "MultiPoint" in geom_types:
            gdf = gdf.copy()
            gdf["geometry"] = gdf.apply(
                lambda row: (
                    row.geometry.buffer(float(row["D"]) / 2.0)
                    if row.geometry is not None
                    and row.geometry.geom_type in ("Point", "MultiPoint")
                    else row.geometry
                ),
                axis=1,
            )

    mask_union = mask_gdf.geometry.union_all()
    if not gdf.empty:
        gdf = gdf[gdf.geometry.intersects(mask_union)].copy()
    if gdf.empty:
        print("Warning: no trees inside mask after clip; omitting vegetation.")
        return None

    gdf = _thin_trees_by_spacing(gdf, min_spacing)
    if gdf.empty:
        print("Warning: no trees left after thinning; omitting vegetation.")
        return None

    gdf = gdf[list(_TREE_REQUIRED_FIELDS) + ["geometry"]]
    gdf.to_file(out_shp, driver="ESRI Shapefile")
    print(f"trees (QES): {out_shp}  ({len(gdf)} crowns)")
    return out_shp


def resolve_inputs(
    work_dir: Path,
    bbox: tuple[float, float, float, float],
    *,
    skip_fetch: bool,
    no_trees: bool,
    lai: float,
    trees_resolution: float,
    min_tree_height: float,
    max_tree_height: float,
    trees_min_spacing: float,
) -> tuple[Path, Path, Path, Path | None]:
    """Return ``(dem_clip, mask, buildings, trees)``, fetching unless skipped."""
    mask_shp = work_dir / "mask.shp"
    buildings_shp = work_dir / "buildings.shp"
    trees_shp = work_dir / TREES_QES_NAME
    trees_points = work_dir / TREES_POINTS_NAME
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
        if no_trees:
            return dem_clip, mask_shp, buildings_shp, None
        src_trees = trees_points if trees_points.is_file() else trees_shp
        if not src_trees.is_file():
            raise SystemExit(
                f"--skip-fetch requires {trees_points} or {trees_shp} "
                "(or pass --no-trees)."
            )
        trees_out = prepare_trees_shp(
            src_trees,
            mask_shp,
            trees_shp,
            max_tree_height=max_tree_height,
            min_spacing=trees_min_spacing,
        )
        return dem_clip, mask_shp, buildings_shp, trees_out

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

    if no_trees:
        return dem_clip, mask_shp, buildings_shp, None

    print("Fetching trees from IGN LiDAR (pymdurs)...")
    points_shp = fetch_trees(
        work_dir,
        bbox,
        lai=lai,
        resolution=trees_resolution,
        min_tree_height=min_tree_height,
    )
    print(f"trees (pts): {points_shp}")
    trees_out = prepare_trees_shp(
        points_shp,
        mask_shp,
        trees_shp,
        max_tree_height=max_tree_height,
        min_spacing=trees_min_spacing,
    )
    return dem_clip, mask_shp, buildings_shp, trees_out


def check_domain_size(
    params: WindsParameters,
    dem: Path,
    buildings: Path,
    *,
    trees: Path | None,
    force: bool,
) -> tuple[int, int, int]:
    """Print domain size and abort if the mesh is dangerously large."""
    domain = geo.compute_domain_cells(params, dem, buildings, trees_shp=trees)
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
    trees_shp: Path | None,
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

    if trees_shp is not None:
        # Dense LiDAR crowns: wakeFlag=1 applies an isolated-tree wake (~11×H)
        # per crown and typically zeroes near-ground wind over the whole domain.
        params.vegetation_params = VegetationParameters(
            wake_flag=1 if args.tree_wake else 0,
            shp_file=str(trees_shp.resolve()),
            shp_tree_layer=TREES_LAYER,
        )

    check_domain_size(
        params, dem, buildings_src, trees=trees_shp, force=args.force
    )

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

    dem_tif, mask_shp, buildings_shp, trees_shp = resolve_inputs(
        work_dir,
        args.bbox,
        skip_fetch=args.skip_fetch,
        no_trees=args.no_trees,
        lai=args.lai,
        trees_resolution=args.trees_resolution,
        min_tree_height=args.min_tree_height,
        max_tree_height=args.max_tree_height,
        trees_min_spacing=args.trees_min_spacing,
    )
    if args.skip_fetch:
        print(f"DEM clip:  {dem_tif}")
        print(f"mask:      {mask_shp}")
        print(f"buildings: {buildings_shp}")
        if trees_shp is not None:
            print(f"trees:     {trees_shp}")
        else:
            print("trees:     (none)")

    print("Running QES-Winds...")
    result = run_winds(
        dem=dem_tif,
        buildings_src=buildings_shp,
        buildings_mask=mask_shp,
        trees_shp=trees_shp,
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
