"""Shared utilities for pyQES: config models, XML I/O and geospatial helpers."""

from __future__ import annotations

from typing import Any

# Geospatial helpers depend on optional native libraries (rasterio/pyproj/
# geopandas); import lazily so `import pyQES.util` works without them.
from . import geo  # noqa: F401  (re-exported module)
from .config import (
    BuildingsParams,
    FileOptions,
    Homogeneous,
    IsolatedTree,
    MetParams,
    SensorParameters,
    SimulationParameters,
    TimeSeries,
    TurbParams,
    VegetationParameters,
    WindsParameters,
)
from .paths import resolve_path, resolve_work_dir
from .xml_io import (
    from_qes_xml,
    from_sensor_xml,
    to_qes_xml,
    to_sensor_xml,
    write_qes_xml,
    write_sensor_xml,
)

__all__ = [
    "SimulationParameters",
    "MetParams",
    "BuildingsParams",
    "Homogeneous",
    "IsolatedTree",
    "VegetationParameters",
    "TurbParams",
    "FileOptions",
    "WindsParameters",
    "TimeSeries",
    "SensorParameters",
    "to_qes_xml",
    "from_qes_xml",
    "to_sensor_xml",
    "from_sensor_xml",
    "write_qes_xml",
    "write_sensor_xml",
    "resolve_work_dir",
    "resolve_path",
    "geo",
    "mag_to_tif",
    "default_mag_tif_name",
    "uv_to_arrows_geojson",
    "default_arrows_geojson_name",
    "uv_to_flowlines_geojson",
    "default_flowlines_geojson_name",
]


def __getattr__(name: str) -> Any:
    """Lazy-load NetCDF/rasterio exporters so light imports stay optional-free."""
    if name in (
        "mag_to_tif",
        "default_mag_tif_name",
        "uv_to_arrows_geojson",
        "default_arrows_geojson_name",
        "uv_to_flowlines_geojson",
        "default_flowlines_geojson_name",
    ):
        from . import outputs

        return getattr(outputs, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
