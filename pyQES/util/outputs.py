"""Export QES-Winds NetCDF fields to georeferenced rasters and vector layers.

Geometry (``dx``, ``dy``, ``halo_x``, ``halo_y``, DEM path) is supplied by the
caller — typically the in-memory :class:`~pyQES.util.config.SimulationParameters`
of the current :mod:`pyQES.pywinds` run — not re-parsed from XML.
"""

from __future__ import annotations

import json
import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import netCDF4
import numpy as np
import rasterio
from rasterio.transform import from_origin

__all__ = [
    "mag_to_tif",
    "default_mag_tif_name",
    "uv_to_arrows_geojson",
    "default_arrows_geojson_name",
    "uv_to_flowlines_geojson",
    "default_flowlines_geojson_name",
]

NODATA = -9999.0


def default_mag_tif_name(basename: str, agl_height: float, direction: float) -> str:
    """Return ``{basename}_Vmag_z{h}m_dir{dir}.tif``."""
    return f"{basename}_Vmag_z{agl_height:g}m_dir{direction:.0f}.tif"


def default_arrows_geojson_name(basename: str, agl_height: float, direction: float) -> str:
    """Return ``{basename}_arrows_z{h}m_dir{dir}.geojson``."""
    return f"{basename}_arrows_z{agl_height:g}m_dir{direction:.0f}.geojson"


def default_flowlines_geojson_name(basename: str, agl_height: float, direction: float) -> str:
    """Return ``{basename}_flowlines_z{h}m_dir{dir}.geojson``."""
    return f"{basename}_flowlines_z{agl_height:g}m_dir{direction:.0f}.geojson"


def _load_terrain(
    ds: netCDF4.Dataset,
    dem_path: str,
    ny: int,
    nx: int,
) -> np.ndarray:
    if "terrain" in ds.variables:
        terrain = np.asarray(ds.variables["terrain"][:], dtype=np.float64)
        if terrain.shape != (ny, nx):
            raise ValueError(f"terrain shape {terrain.shape} != mag spatial shape ({ny}, {nx})")
        return terrain

    with rasterio.open(dem_path) as dem_ds:
        if dem_ds.height != ny or dem_ds.width != nx:
            raise ValueError(
                f"terrain not in NetCDF and DEM shape ({dem_ds.height}, {dem_ds.width}) "
                f"!= mag shape ({ny}, {nx})"
            )
        warnings.warn(
            "terrain not in NetCDF, using elevations from DEM",
            stacklevel=2,
        )
        # DEM is north-up; QES mag/terrain NetCDF are south-up (j=0 at south).
        return np.flipud(dem_ds.read(1).astype(np.float64))


def _select_mag_at_agl(
    mag: np.ndarray,
    z_levels: np.ndarray,
    terrain: np.ndarray,
    agl_height: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Select mag at nearest z level to terrain + agl_height for each pixel."""
    target_z = terrain + agl_height
    k_idx = np.abs(z_levels[:, None, None] - target_z[None, :, :]).argmin(axis=0)
    out = np.take_along_axis(mag, k_idx[None, :, :], axis=0)[0].astype(np.float32)
    return out, k_idx


def _apply_icell_mask(
    out: np.ndarray,
    icell: np.ndarray,
    k_idx: np.ndarray,
) -> np.ndarray:
    icell_sel = np.take_along_axis(icell, k_idx[None, :, :], axis=0)[0]
    return np.where(icell_sel == 1, out, NODATA)


def _write_geotiff(
    output_path: str,
    array: np.ndarray,
    x0: float,
    y0: float,
    dx: float,
    dy: float,
    crs,
    agl_height: float,
) -> None:
    """Write GeoTIFF. ``x0, y0`` = SW corner of the full QES domain (DEM SW − halo)."""
    ny, nx = array.shape
    transform = from_origin(x0, y0 + ny * dy, dx, dy)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "width": nx,
        "height": ny,
        "count": 1,
        "crs": crs,
        "transform": transform,
        "nodata": NODATA,
        "compress": "deflate",
        "tiled": True,
    }
    with rasterio.open(output_path, "w", **profile) as dst:
        # QES j=0 at south; GeoTIFF line 0 must be north.
        dst.write(np.flipud(array), 1)
        dst.set_band_description(1, f"velocity magnitude at {agl_height} m AGL (m/s)")
        dst.update_tags(1, units="m/s")


def _log_summary(
    *,
    nc_path: str,
    output_path: str,
    dem_path: str,
    x0: float,
    y0: float,
    dx: float,
    dy: float,
    halo_x: float,
    halo_y: float,
    mask_buildings: bool,
    nx: int,
    ny: int,
    z_levels: np.ndarray,
    terrain: np.ndarray,
    agl_height: float,
    k_idx: np.ndarray,
    out: np.ndarray,
) -> None:
    selected_z = z_levels[k_idx]
    agl_actual = selected_z - terrain
    target_z = terrain + agl_height
    valid = out[out != NODATA]

    print(f"windsOut.nc → GeoTIFF (mag @ {agl_height} m AGL)")
    print(f"  Input  : {nc_path}")
    print(f"  Output : {output_path}")
    print(f"  DEM    : {dem_path}")
    print(
        f"  Origin : domain SW x0={x0} y0={y0} "
        f"(DEM SW − halo {halo_x}x{halo_y})  cellSize={dx}x{dy} m"
    )
    print(f"  Mask buildings: {'yes' if mask_buildings else 'no'}")
    print(f"  Grid   : {nx} x {ny} pixels, {len(z_levels)} z levels")
    print(
        f"  z target (AMSL): min={target_z.min():.2f} max={target_z.max():.2f} "
        f"mean={target_z.mean():.2f} m"
    )
    print(
        f"  z selected (AMSL): min={selected_z.min():.2f} max={selected_z.max():.2f} "
        f"mean={selected_z.mean():.2f} m"
    )
    print(
        f"  AGL at selected z: min={agl_actual.min():.2f} max={agl_actual.max():.2f} "
        f"mean={agl_actual.mean():.2f} m"
    )
    unique_k, counts = np.unique(k_idx, return_counts=True)
    top = sorted(zip(counts, unique_k), reverse=True)[:5]
    print(
        "  Top z-band usage (count, z_m):",
        ", ".join(f"{c}@{z_levels[k]:.2f}" for c, k in top),
    )
    if valid.size:
        print(
            f"  mag    : min={valid.min():.3f} max={valid.max():.3f} "
            f"mean={valid.mean():.3f} m/s ({valid.size} valid pixels)"
        )
    else:
        print("  mag    : no valid pixels after masking")
    print(f"Success: {output_path}")


def mag_to_tif(
    nc_path: str | Path,
    *,
    dx: float,
    dy: float,
    halo_x: float,
    halo_y: float,
    dem: str | Path,
    output_path: str | Path | None = None,
    agl_height: float = 1.5,
    time_idx: int = 0,
    mask_buildings: bool = True,
    verbose: bool = False,
) -> str:
    """Export wind magnitude at AGL height from a QES windsOut.nc to GeoTIFF.

    ``dx``, ``dy``, ``halo_x``, ``halo_y`` and ``dem`` must come from the active
    run binding (e.g. :class:`~pyQES.util.config.SimulationParameters`), not from
    re-parsing a QES XML file.
    """
    nc_path = os.path.abspath(str(nc_path))
    dem_path = os.path.abspath(str(dem))
    if not os.path.isfile(nc_path):
        raise FileNotFoundError(f"Input NetCDF not found: {nc_path}")
    if not os.path.isfile(dem_path):
        raise FileNotFoundError(f"DEM not found: {dem_path}")

    if output_path is None:
        base = os.path.basename(nc_path)
        for suffix in ("_windsOut.nc", ".nc"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        output_path = os.path.join(
            os.path.dirname(nc_path),
            f"{base}_mag_{agl_height:g}m.tif",
        )
    else:
        output_path = os.path.abspath(str(output_path))

    with netCDF4.Dataset(nc_path) as ds:
        nt = ds.dimensions["t"].size
        if time_idx < 0 or time_idx >= nt:
            raise ValueError(f"time index {time_idx} out of range (0..{nt - 1})")

        z_levels = np.asarray(ds.variables["z"][:], dtype=np.float64)
        mag = np.asarray(ds.variables["mag"][time_idx], dtype=np.float32)

        if mag.ndim != 3:
            raise ValueError(f"Expected mag shape (z, y, x), got {mag.shape}")
        nz, ny, nx = mag.shape
        if len(z_levels) != nz:
            raise ValueError(f"z level count ({len(z_levels)}) != mag z count ({nz})")

        terrain = _load_terrain(ds, dem_path, ny, nx)
        out, k_idx = _select_mag_at_agl(mag, z_levels, terrain, agl_height)

        if mask_buildings:
            icell = np.asarray(ds.variables["icell"][time_idx], dtype=np.float32)
            if icell.shape != mag.shape:
                raise ValueError(f"icell shape {icell.shape} != mag shape {mag.shape}")
            out = _apply_icell_mask(out, icell, k_idx)

    out[np.isnan(out)] = NODATA

    with rasterio.open(dem_path) as dem_ds:
        crs = dem_ds.crs
        x0 = dem_ds.bounds.left - halo_x
        y0 = dem_ds.bounds.bottom - halo_y
    if crs is None:
        raise ValueError(f"Could not read CRS from {dem_path}")

    _write_geotiff(output_path, out, x0, y0, dx, dy, crs, agl_height)

    if verbose:
        _log_summary(
            nc_path=nc_path,
            output_path=output_path,
            dem_path=dem_path,
            x0=x0,
            y0=y0,
            dx=dx,
            dy=dy,
            halo_x=halo_x,
            halo_y=halo_y,
            mask_buildings=mask_buildings,
            nx=nx,
            ny=ny,
            z_levels=z_levels,
            terrain=terrain,
            agl_height=agl_height,
            k_idx=k_idx,
            out=out,
        )
    return output_path


def _flow_bearing_deg(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """MapLibre ``icon-rotate`` bearing: degrees clockwise from north (flow *toward*).

    Uses ``atan2(u, v)`` with QES ``u`` = east, ``v`` = north. This is the
    flow direction (going to), not meteorological wind-from (+180°).
    """
    return np.mod(np.degrees(np.arctan2(u, v)), 360.0)


def _select_field_at_agl(
    field: np.ndarray,
    k_idx: np.ndarray,
) -> np.ndarray:
    """Take ``field`` values at per-pixel ``k_idx`` (shape ``(z,y,x)`` → ``(y,x)``)."""
    return np.take_along_axis(field, k_idx[None, :, :], axis=0)[0].astype(np.float32)


@dataclass(frozen=True)
class _UvSlice:
    """2-D AGL wind slice in local metres (cell centres) plus domain origin/CRS."""

    u2: np.ndarray
    v2: np.ndarray
    x_local: np.ndarray
    y_local: np.ndarray
    valid: np.ndarray
    x0: float
    y0: float
    crs: Any
    nx: int
    ny: int


def _load_uv_slice(
    nc_path: str,
    dem_path: str,
    *,
    halo_x: float,
    halo_y: float,
    agl_height: float,
    time_idx: int,
    mask_buildings: bool,
    min_speed: float,
) -> _UvSlice:
    """Read u/v at AGL, apply building/speed mask, resolve domain SW origin + CRS."""
    with netCDF4.Dataset(nc_path) as ds:
        nt = ds.dimensions["t"].size
        if time_idx < 0 or time_idx >= nt:
            raise ValueError(f"time index {time_idx} out of range (0..{nt - 1})")
        if "u" not in ds.variables or "v" not in ds.variables:
            raise ValueError(
                f"NetCDF missing u/v fields (need both): {nc_path}. "
                "Ensure <outputFields> includes u and v (or 'all')."
            )

        z_levels = np.asarray(ds.variables["z"][:], dtype=np.float64)
        x_local = np.asarray(ds.variables["x"][:], dtype=np.float64)
        y_local = np.asarray(ds.variables["y"][:], dtype=np.float64)
        u3 = np.asarray(ds.variables["u"][time_idx], dtype=np.float32)
        v3 = np.asarray(ds.variables["v"][time_idx], dtype=np.float32)

        if u3.ndim != 3 or v3.ndim != 3:
            raise ValueError(f"Expected u/v shape (z, y, x), got u={u3.shape} v={v3.shape}")
        nz, ny, nx = u3.shape
        if v3.shape != u3.shape:
            raise ValueError(f"u shape {u3.shape} != v shape {v3.shape}")
        if len(z_levels) != nz:
            raise ValueError(f"z level count ({len(z_levels)}) != u z count ({nz})")
        if len(x_local) != nx or len(y_local) != ny:
            raise ValueError(
                f"x/y length ({len(x_local)}, {len(y_local)}) != grid ({nx}, {ny})"
            )

        terrain = _load_terrain(ds, dem_path, ny, nx)
        _, k_idx = _select_mag_at_agl(u3, z_levels, terrain, agl_height)
        u2 = _select_field_at_agl(u3, k_idx)
        v2 = _select_field_at_agl(v3, k_idx)

        valid = np.ones((ny, nx), dtype=bool)
        if mask_buildings:
            if "icell" not in ds.variables:
                raise ValueError("mask_buildings=True but 'icell' missing from NetCDF")
            icell = np.asarray(ds.variables["icell"][time_idx], dtype=np.float32)
            if icell.shape != u3.shape:
                raise ValueError(f"icell shape {icell.shape} != u shape {u3.shape}")
            icell_sel = _select_field_at_agl(icell, k_idx)
            valid &= icell_sel == 1

    speed = np.hypot(u2, v2)
    valid &= np.isfinite(speed) & (speed >= min_speed)

    with rasterio.open(dem_path) as dem_ds:
        crs = dem_ds.crs
        x0 = dem_ds.bounds.left - halo_x
        y0 = dem_ds.bounds.bottom - halo_y
    if crs is None:
        raise ValueError(f"Could not read CRS from {dem_path}")

    return _UvSlice(
        u2=u2,
        v2=v2,
        x_local=x_local,
        y_local=y_local,
        valid=valid,
        x0=x0,
        y0=y0,
        crs=crs,
        nx=nx,
        ny=ny,
    )


def _default_geojson_path(nc_path: str, agl_height: float, kind: str) -> str:
    base = os.path.basename(nc_path)
    for suffix in ("_windsOut.nc", ".nc"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return os.path.join(os.path.dirname(nc_path), f"{base}_{kind}_{agl_height:g}m.geojson")


def _bilinear_uv(
    x: float,
    y: float,
    slice_: _UvSlice,
    min_speed: float,
) -> tuple[float, float] | None:
    """Bilinear ``(u,v)`` at local ``(x,y)``; ``None`` if OOB / invalid / too slow."""
    x_loc, y_loc = slice_.x_local, slice_.y_local
    if x < x_loc[0] or x > x_loc[-1] or y < y_loc[0] or y > y_loc[-1]:
        return None

    dx = float(x_loc[1] - x_loc[0]) if slice_.nx > 1 else 1.0
    dy = float(y_loc[1] - y_loc[0]) if slice_.ny > 1 else 1.0
    fi = (x - float(x_loc[0])) / dx
    fj = (y - float(y_loc[0])) / dy
    i0 = int(np.floor(fi))
    j0 = int(np.floor(fj))
    i1 = min(i0 + 1, slice_.nx - 1)
    j1 = min(j0 + 1, slice_.ny - 1)
    i0 = max(0, min(i0, slice_.nx - 1))
    j0 = max(0, min(j0, slice_.ny - 1))
    tx = fi - np.floor(fi)
    ty = fj - np.floor(fj)

    corners = ((j0, i0), (j0, i1), (j1, i0), (j1, i1))
    if not all(slice_.valid[j, i] for j, i in corners):
        return None

    u00 = float(slice_.u2[j0, i0])
    u10 = float(slice_.u2[j0, i1])
    u01 = float(slice_.u2[j1, i0])
    u11 = float(slice_.u2[j1, i1])
    v00 = float(slice_.v2[j0, i0])
    v10 = float(slice_.v2[j0, i1])
    v01 = float(slice_.v2[j1, i0])
    v11 = float(slice_.v2[j1, i1])

    u = (
        u00 * (1 - tx) * (1 - ty)
        + u10 * tx * (1 - ty)
        + u01 * (1 - tx) * ty
        + u11 * tx * ty
    )
    v = (
        v00 * (1 - tx) * (1 - ty)
        + v10 * tx * (1 - ty)
        + v01 * (1 - tx) * ty
        + v11 * tx * ty
    )
    if not np.isfinite(u) or not np.isfinite(v) or np.hypot(u, v) < min_speed:
        return None
    return u, v


def _rk4_step(
    x: float,
    y: float,
    dt: float,
    slice_: _UvSlice,
    min_speed: float,
) -> tuple[float, float] | None:
    """One RK4 step; ``None`` if any stage fails."""
    k1 = _bilinear_uv(x, y, slice_, min_speed)
    if k1 is None:
        return None
    k2 = _bilinear_uv(x + 0.5 * dt * k1[0], y + 0.5 * dt * k1[1], slice_, min_speed)
    if k2 is None:
        return None
    k3 = _bilinear_uv(x + 0.5 * dt * k2[0], y + 0.5 * dt * k2[1], slice_, min_speed)
    if k3 is None:
        return None
    k4 = _bilinear_uv(x + dt * k3[0], y + dt * k3[1], slice_, min_speed)
    if k4 is None:
        return None
    nx = x + (dt / 6.0) * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0])
    ny = y + (dt / 6.0) * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1])
    return nx, ny


def _occ_index(x: float, y: float, slice_: _UvSlice, seed_stride: int) -> tuple[int, int]:
    """Occupation-grid indices at resolution ``seed_stride`` cells."""
    dx = float(slice_.x_local[1] - slice_.x_local[0]) if slice_.nx > 1 else 1.0
    dy = float(slice_.y_local[1] - slice_.y_local[0]) if slice_.ny > 1 else 1.0
    i = int((x - float(slice_.x_local[0])) / dx)
    j = int((y - float(slice_.y_local[0])) / dy)
    return j // seed_stride, i // seed_stride


def _integrate_streamline(
    x_start: float,
    y_start: float,
    *,
    slice_: _UvSlice,
    dx: float,
    dy: float,
    min_speed: float,
    max_steps: int,
    max_length_m: float,
    step_cell: float,
    sign: float,
    occupied: np.ndarray,
    seed_stride: int,
    min_points: int,
    mark: bool,
) -> tuple[list[tuple[float, float]], list[float], float]:
    """Integrate one direction (``sign`` +1 forward / −1 backward)."""
    points: list[tuple[float, float]] = [(x_start, y_start)]
    speeds: list[float] = []
    length = 0.0
    x, y = x_start, y_start
    cell_size = min(dx, dy)
    eps = 1e-6

    for _ in range(max_steps):
        uv = _bilinear_uv(x, y, slice_, min_speed)
        if uv is None:
            break
        speed = float(np.hypot(uv[0], uv[1]))
        speeds.append(speed)

        oj, oi = _occ_index(x, y, slice_, seed_stride)
        if (
            0 <= oj < occupied.shape[0]
            and 0 <= oi < occupied.shape[1]
            and occupied[oj, oi]
            and len(points) >= min_points
        ):
            break

        if mark and 0 <= oj < occupied.shape[0] and 0 <= oi < occupied.shape[1]:
            occupied[oj, oi] = True

        dt = sign * step_cell * cell_size / max(speed, eps)
        nxt = _rk4_step(x, y, dt, slice_, min_speed)
        if nxt is None:
            break
        nx, ny = nxt
        step_len = float(np.hypot(nx - x, ny - y))
        if step_len < eps:
            break
        length += step_len
        if length > max_length_m:
            break
        points.append((nx, ny))
        x, y = nx, ny

    return points, speeds, length


def _polyline_length(pts: list[tuple[float, float]]) -> float:
    if len(pts) < 2:
        return 0.0
    return float(
        sum(np.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]) for i in range(1, len(pts)))
    )


def uv_to_arrows_geojson(
    nc_path: str | Path,
    *,
    dx: float,
    dy: float,
    halo_x: float,
    halo_y: float,
    dem: str | Path,
    output_path: str | Path | None = None,
    agl_height: float = 1.5,
    time_idx: int = 0,
    mask_buildings: bool = True,
    stride: int = 4,
    min_speed: float = 0.05,
    verbose: bool = False,
) -> str:
    """Export a subsampled u/v arrow seed as GeoJSON points (EPSG:4326).

    Each feature has properties ``bearing`` (MapLibre ``icon-rotate``, flow
    *toward*, degrees clockwise from north), ``speed`` (m/s), plus ``u``/``v``.

    ``stride`` keeps one arrow every N cells in x and y. Cells with
    ``speed < min_speed`` or solid buildings (``icell != 1``) are skipped.
    """
    if stride < 1:
        raise ValueError(f"stride must be >= 1, got {stride}")

    nc_path = os.path.abspath(str(nc_path))
    dem_path = os.path.abspath(str(dem))
    if not os.path.isfile(nc_path):
        raise FileNotFoundError(f"Input NetCDF not found: {nc_path}")
    if not os.path.isfile(dem_path):
        raise FileNotFoundError(f"DEM not found: {dem_path}")

    if output_path is None:
        output_path = _default_geojson_path(nc_path, agl_height, "arrows")
    else:
        output_path = os.path.abspath(str(output_path))

    slice_ = _load_uv_slice(
        nc_path,
        dem_path,
        halo_x=halo_x,
        halo_y=halo_y,
        agl_height=agl_height,
        time_idx=time_idx,
        mask_buildings=mask_buildings,
        min_speed=min_speed,
    )

    from pyproj import Transformer

    to_wgs84 = Transformer.from_crs(slice_.crs, "EPSG:4326", always_xy=True)

    features: list[dict] = []
    for j in range(0, slice_.ny, stride):
        for i in range(0, slice_.nx, stride):
            if not slice_.valid[j, i]:
                continue
            ui = float(slice_.u2[j, i])
            vi = float(slice_.v2[j, i])
            spd = float(np.hypot(ui, vi))
            bearing = float(_flow_bearing_deg(np.array(ui), np.array(vi)))
            easting = float(slice_.x0 + slice_.x_local[i])
            northing = float(slice_.y0 + slice_.y_local[j])
            lon, lat = to_wgs84.transform(easting, northing)
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {
                        "bearing": round(bearing, 2),
                        "speed": round(spd, 4),
                        "u": round(ui, 4),
                        "v": round(vi, 4),
                    },
                }
            )

    collection = {
        "type": "FeatureCollection",
        "features": features,
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
    }
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(collection, fh)

    if verbose:
        print(f"windsOut.nc → GeoJSON arrows (u/v @ {agl_height} m AGL)")
        print(f"  Input  : {nc_path}")
        print(f"  Output : {output_path}")
        print(f"  DEM    : {dem_path}")
        print(
            f"  Origin : domain SW x0={slice_.x0} y0={slice_.y0} "
            f"(DEM SW − halo {halo_x}x{halo_y})  cellSize={dx}x{dy} m"
        )
        print(f"  Mask buildings: {'yes' if mask_buildings else 'no'}")
        print(f"  Stride : {stride}, min_speed={min_speed} m/s")
        print(f"  Grid   : {slice_.nx} x {slice_.ny}, arrows written: {len(features)}")
        print(f"Success: {output_path}")

    return output_path


def uv_to_flowlines_geojson(
    nc_path: str | Path,
    *,
    dx: float,
    dy: float,
    halo_x: float,
    halo_y: float,
    dem: str | Path,
    output_path: str | Path | None = None,
    agl_height: float = 1.5,
    time_idx: int = 0,
    mask_buildings: bool = True,
    seed_stride: int = 8,
    min_speed: float = 0.05,
    max_steps: int = 2000,
    max_length_m: float | None = None,
    step_cell: float = 0.5,
    bidirectional: bool = True,
    min_points: int = 4,
    verbose: bool = False,
) -> str:
    """Export RK4 streamlines as GeoJSON LineStrings (EPSG:4326) for MapLibre.

    Integrate the AGL ``u``/``v`` field from a seed grid. MapLibre can draw the
    lines and place chevrons with ``symbol-placement: 'line'`` (no bearing needed).

    Properties per feature: ``mean_speed`` (m/s), ``length_m``, ``n_vertices``.
    """
    if seed_stride < 1:
        raise ValueError(f"seed_stride must be >= 1, got {seed_stride}")
    if step_cell <= 0:
        raise ValueError(f"step_cell must be > 0, got {step_cell}")
    if min_points < 2:
        raise ValueError(f"min_points must be >= 2, got {min_points}")

    nc_path = os.path.abspath(str(nc_path))
    dem_path = os.path.abspath(str(dem))
    if not os.path.isfile(nc_path):
        raise FileNotFoundError(f"Input NetCDF not found: {nc_path}")
    if not os.path.isfile(dem_path):
        raise FileNotFoundError(f"DEM not found: {dem_path}")

    if output_path is None:
        output_path = _default_geojson_path(nc_path, agl_height, "flowlines")
    else:
        output_path = os.path.abspath(str(output_path))

    slice_ = _load_uv_slice(
        nc_path,
        dem_path,
        halo_x=halo_x,
        halo_y=halo_y,
        agl_height=agl_height,
        time_idx=time_idx,
        mask_buildings=mask_buildings,
        min_speed=min_speed,
    )

    if max_length_m is None:
        max_length_m = 0.5 * float(np.hypot(slice_.nx * dx, slice_.ny * dy))

    n_occ_j = (slice_.ny + seed_stride - 1) // seed_stride
    n_occ_i = (slice_.nx + seed_stride - 1) // seed_stride
    occupied = np.zeros((n_occ_j, n_occ_i), dtype=bool)

    from pyproj import Transformer

    to_wgs84 = Transformer.from_crs(slice_.crs, "EPSG:4326", always_xy=True)

    features: list[dict] = []
    for j in range(0, slice_.ny, seed_stride):
        for i in range(0, slice_.nx, seed_stride):
            if not slice_.valid[j, i]:
                continue
            oj, oi = j // seed_stride, i // seed_stride
            if occupied[oj, oi]:
                continue

            x_seed = float(slice_.x_local[i])
            y_seed = float(slice_.y_local[j])

            fwd_pts, fwd_spd, _ = _integrate_streamline(
                x_seed,
                y_seed,
                slice_=slice_,
                dx=dx,
                dy=dy,
                min_speed=min_speed,
                max_steps=max_steps,
                max_length_m=max_length_m,
                step_cell=step_cell,
                sign=1.0,
                occupied=occupied,
                seed_stride=seed_stride,
                min_points=min_points,
                mark=True,
            )

            if bidirectional:
                bwd_pts, bwd_spd, _ = _integrate_streamline(
                    x_seed,
                    y_seed,
                    slice_=slice_,
                    dx=dx,
                    dy=dy,
                    min_speed=min_speed,
                    max_steps=max_steps,
                    max_length_m=max_length_m,
                    step_cell=step_cell,
                    sign=-1.0,
                    occupied=occupied,
                    seed_stride=seed_stride,
                    min_points=min_points,
                    mark=True,
                )
                # Exclude duplicate seed; reverse so polyline goes upstream → downstream.
                pts = list(reversed(bwd_pts[1:])) + fwd_pts
                speeds = list(reversed(bwd_spd[1:] if len(bwd_spd) > 1 else bwd_spd)) + fwd_spd
            else:
                pts = fwd_pts
                speeds = fwd_spd

            if len(pts) < min_points:
                continue

            length_m = _polyline_length(pts)
            mean_speed = float(np.mean(speeds)) if speeds else 0.0
            coords = []
            for xl, yl in pts:
                lon, lat = to_wgs84.transform(slice_.x0 + xl, slice_.y0 + yl)
                coords.append([lon, lat])

            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {
                        "mean_speed": round(mean_speed, 4),
                        "length_m": round(length_m, 2),
                        "n_vertices": len(pts),
                    },
                }
            )

    collection = {
        "type": "FeatureCollection",
        "features": features,
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
    }
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(collection, fh)

    if verbose:
        print(f"windsOut.nc → GeoJSON flowlines (RK4 @ {agl_height} m AGL)")
        print(f"  Input  : {nc_path}")
        print(f"  Output : {output_path}")
        print(f"  DEM    : {dem_path}")
        print(
            f"  Origin : domain SW x0={slice_.x0} y0={slice_.y0} "
            f"(DEM SW − halo {halo_x}x{halo_y})  cellSize={dx}x{dy} m"
        )
        print(f"  Mask buildings: {'yes' if mask_buildings else 'no'}")
        print(
            f"  Seeds  : stride={seed_stride}, bidirectional={bidirectional}, "
            f"min_speed={min_speed} m/s, max_length={max_length_m:.1f} m"
        )
        print(f"  Grid   : {slice_.nx} x {slice_.ny}, flowlines written: {len(features)}")
        print(f"Success: {output_path}")

    return output_path
