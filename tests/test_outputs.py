"""Tests for NetCDF → GeoTIFF / GeoJSON export helpers."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("numpy")
pytest.importorskip("netCDF4")
pytest.importorskip("rasterio")
pytest.importorskip("pyproj")

import netCDF4
import numpy as np
import rasterio
from rasterio.transform import from_origin

from pyQES.util.outputs import (  # noqa: E402
    default_arrows_geojson_name,
    default_flowlines_geojson_name,
    default_mag_tif_name,
    uv_to_arrows_geojson,
    uv_to_flowlines_geojson,
)


def test_default_mag_tif_name():
    assert default_mag_tif_name("umep_larochelle", 1.5, 180.0) == (
        "umep_larochelle_Vmag_z1.5m_dir180.tif"
    )
    assert default_mag_tif_name("run", 10.0, 270.0) == "run_Vmag_z10m_dir270.tif"


def test_default_arrows_geojson_name():
    assert default_arrows_geojson_name("qes", 1.5, 270.0) == (
        "qes_arrows_z1.5m_dir270.geojson"
    )


def test_default_flowlines_geojson_name():
    assert default_flowlines_geojson_name("qes", 1.5, 270.0) == (
        "qes_flowlines_z1.5m_dir270.geojson"
    )


def _write_flat_dem(path, *, nx: int, ny: int, dx: float, dy: float, x0: float, y0: float) -> None:
    """North-up DEM whose SW corner is ``(x0, y0)`` (EPSG:2154)."""
    transform = from_origin(x0, y0 + ny * dy, dx, dy)
    data = np.zeros((ny, nx), dtype=np.float32)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=ny,
        width=nx,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=transform,
    ) as dst:
        dst.write(data, 1)


def _write_synthetic_winds_nc(
    path,
    *,
    nx: int,
    ny: int,
    dx: float,
    dy: float,
    u_val: float,
    v_val: float,
) -> None:
    """Minimal windsOut-like NetCDF with uniform u/v and flat terrain."""
    nz = 3
    z_levels = np.array([0.5, 1.5, 2.5], dtype=np.float64)
    x = (np.arange(nx, dtype=np.float64) + 0.5) * dx
    y = (np.arange(ny, dtype=np.float64) + 0.5) * dy
    terrain = np.zeros((ny, nx), dtype=np.float32)
    u = np.full((1, nz, ny, nx), u_val, dtype=np.float32)
    v = np.full((1, nz, ny, nx), v_val, dtype=np.float32)
    icell = np.ones((1, nz, ny, nx), dtype=np.float32)

    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("t", 1)
        ds.createDimension("z", nz)
        ds.createDimension("y", ny)
        ds.createDimension("x", nx)
        ds.createVariable("z", "f8", ("z",))[:] = z_levels
        ds.createVariable("x", "f8", ("x",))[:] = x
        ds.createVariable("y", "f8", ("y",))[:] = y
        ds.createVariable("terrain", "f4", ("y", "x"))[:] = terrain
        ds.createVariable("u", "f4", ("t", "z", "y", "x"))[:] = u
        ds.createVariable("v", "f4", ("t", "z", "y", "x"))[:] = v
        ds.createVariable("icell", "f4", ("t", "z", "y", "x"))[:] = icell


def test_uv_to_arrows_geojson_eastward_bearing(tmp_path):
    """u>0, v=0 → bearing ≈ 90° (flow toward east, MapLibre icon-rotate)."""
    nx, ny = 4, 4
    dx = dy = 2.0
    x0, y0 = 500_000.0, 6_600_000.0
    dem = tmp_path / "dem.tif"
    nc = tmp_path / "synth_windsOut.nc"
    out = tmp_path / "arrows.geojson"

    _write_flat_dem(dem, nx=nx, ny=ny, dx=dx, dy=dy, x0=x0, y0=y0)
    _write_synthetic_winds_nc(nc, nx=nx, ny=ny, dx=dx, dy=dy, u_val=2.0, v_val=0.0)

    path = uv_to_arrows_geojson(
        nc,
        dx=dx,
        dy=dy,
        halo_x=0.0,
        halo_y=0.0,
        dem=dem,
        output_path=out,
        agl_height=1.5,
        stride=1,
        min_speed=0.05,
        mask_buildings=True,
    )

    assert path == str(out.resolve())
    with open(out, encoding="utf-8") as fh:
        gj = json.load(fh)

    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == nx * ny
    for feat in gj["features"]:
        assert feat["geometry"]["type"] == "Point"
        props = feat["properties"]
        assert props["bearing"] == pytest.approx(90.0, abs=0.01)
        assert props["speed"] == pytest.approx(2.0, abs=1e-4)
        assert props["u"] == pytest.approx(2.0, abs=1e-4)
        assert props["v"] == pytest.approx(0.0, abs=1e-4)
        lon, lat = feat["geometry"]["coordinates"]
        assert -180.0 <= lon <= 180.0
        assert -90.0 <= lat <= 90.0


def test_uv_to_flowlines_geojson_eastward(tmp_path):
    """Uniform eastward flow → LineStrings with increasing longitude."""
    nx, ny = 12, 12
    dx = dy = 2.0
    x0, y0 = 500_000.0, 6_600_000.0
    dem = tmp_path / "dem.tif"
    nc = tmp_path / "synth_windsOut.nc"
    out = tmp_path / "flowlines.geojson"

    _write_flat_dem(dem, nx=nx, ny=ny, dx=dx, dy=dy, x0=x0, y0=y0)
    _write_synthetic_winds_nc(nc, nx=nx, ny=ny, dx=dx, dy=dy, u_val=2.0, v_val=0.0)

    path = uv_to_flowlines_geojson(
        nc,
        dx=dx,
        dy=dy,
        halo_x=0.0,
        halo_y=0.0,
        dem=dem,
        output_path=out,
        agl_height=1.5,
        seed_stride=4,
        min_speed=0.05,
        min_points=4,
        bidirectional=True,
        mask_buildings=True,
    )

    assert path == str(out.resolve())
    with open(out, encoding="utf-8") as fh:
        gj = json.load(fh)

    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) >= 1
    for feat in gj["features"]:
        assert feat["geometry"]["type"] == "LineString"
        coords = feat["geometry"]["coordinates"]
        props = feat["properties"]
        assert props["n_vertices"] >= 4
        assert props["n_vertices"] == len(coords)
        assert "mean_speed" in props
        assert "length_m" in props
        assert props["length_m"] > 0
        assert props["mean_speed"] == pytest.approx(2.0, abs=0.1)
        lons = [c[0] for c in coords]
        # Flow toward east → longitude non-decreasing along the line
        assert lons[-1] > lons[0]
        assert all(lons[i] <= lons[i + 1] + 1e-9 for i in range(len(lons) - 1))
