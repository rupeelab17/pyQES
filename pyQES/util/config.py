"""Pydantic models describing QES input parameters.

The models mirror the QES XML schema (see ``data/umep_workflow/qes``) so a
configuration can be built in Python, validated, round-tripped to/from JSON and
serialized to the XML the C++ parser consumes (see :mod:`pyQES.util.xml_io`).

Field names are Pythonic ``snake_case``; each field carries the exact XML tag as
its alias so both styles can be used interchangeably.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class QESModel(BaseModel):
    """Base model: allow population by field name or XML-tag alias."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


def _split_numbers(value: Any) -> Any:
    """Accept a space-separated XML string ("146 99 89") as a sequence."""
    if isinstance(value, str):
        return value.split()
    return value


def _as_list(value: Any) -> Any:
    """Wrap a scalar (single XML element) into a one-item list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


class SimulationParameters(QESModel):
    """`<simulationParameters>` block of a QES-Winds XML file."""

    dem: str | None = Field(default=None, alias="DEM")
    halo_x: float = Field(default=0.0, alias="halo_x")
    halo_y: float = Field(default=0.0, alias="halo_y")

    domain: tuple[int, int, int] = Field(default=(1, 1, 1), alias="domain")
    cell_size: tuple[float, float, float] = Field(default=(1.0, 1.0, 1.0), alias="cellSize")

    _split_domain = field_validator("domain", "cell_size", mode="before")(_split_numbers)

    vertical_stretching: int = Field(default=0, alias="verticalStretching")
    total_time_increments: int = Field(default=1, alias="totalTimeIncrements")

    rooftop_flag: int = Field(default=1, alias="rooftopFlag")
    upwind_cavity_flag: int = Field(default=2, alias="upwindCavityFlag")
    street_canyon_flag: int = Field(default=1, alias="streetCanyonFlag")
    street_intersection_flag: int = Field(default=0, alias="streetIntersectionFlag")
    wake_flag: int = Field(default=2, alias="wakeFlag")
    high_rise_flag: int = Field(default=0, alias="highRiseFlag")
    sidewall_flag: int = Field(default=1, alias="sidewallFlag")
    log_law_flag: int = Field(default=0, alias="logLawFlag")

    max_iterations: int = Field(default=500, alias="maxIterations")
    tolerance: float = Field(default=1e-9, alias="tolerance")
    mesh_type_flag: int = Field(default=0, alias="meshTypeFlag")
    domain_rotation: float = Field(default=0.0, alias="domainRotation")

    origin_flag: int = Field(default=0, alias="originFlag")
    dem_distance_x: float = Field(default=0.0, alias="DEMDistancex")
    dem_distance_y: float = Field(default=0.0, alias="DEMDistancey")
    utm_x: float = Field(default=0.0, alias="UTMx")
    utm_y: float = Field(default=0.0, alias="UTMy")
    utm_zone: int = Field(default=1, alias="UTMZone")
    utm_zone_letter: str = Field(default="N", alias="UTMZoneLetter")
    read_coefficients_flag: int = Field(default=0, alias="readCoefficientsFlag")


class MetParams(QESModel):
    """`<metParams>` block: surface roughness and wind sensors."""

    z0_domain_flag: int = Field(default=0, alias="z0_domain_flag")
    sensor_names: list[str] = Field(default_factory=list, alias="sensorName")

    _wrap_sensor_names = field_validator("sensor_names", mode="before")(_as_list)


class BuildingsParams(QESModel):
    """`<buildingsParams>` block: urban parametrization and shapefile inputs."""

    wall_roughness: float = Field(default=0.01, alias="wallRoughness")
    rooftop_flag: int = Field(default=1, alias="rooftopFlag")
    upwind_cavity_flag: int = Field(default=2, alias="upwindCavityFlag")
    street_canyon_flag: int = Field(default=1, alias="streetCanyonFlag")
    street_intersection_flag: int = Field(default=0, alias="streetIntersectionFlag")
    wake_flag: int = Field(default=2, alias="wakeFlag")
    high_rise_flag: int = Field(default=0, alias="highRiseFlag")
    sidewall_flag: int = Field(default=1, alias="sidewallFlag")

    shp_file: str | None = Field(default=None, alias="SHPFile")
    shp_building_layer: str | None = Field(default=None, alias="SHPBuildingLayer")
    shp_height_field: str | None = Field(default=None, alias="SHPHeightField")
    height_factor: float = Field(default=1.0, alias="heightFactor")


class TurbParams(QESModel):
    """`<turbParams>` block: QES-Turb method selector."""

    method: int = Field(default=0, alias="method")


class Homogeneous(QESModel):
    """`<Homogeneous>` canopy — uniform Cionco exponential drag.

    Footprint is either a rectangle (``x_start`` / ``y_start`` / ``length`` /
    ``width`` / ``canopy_rotation``) or a polygon (paired ``x_vertex`` /
    ``y_vertex`` lists). No per-tree structure or wake — mean attenuation only.
    """

    attenuation_coefficient: float = Field(..., alias="attenuationCoefficient")
    height: float = Field(..., alias="height")
    base_height: float = Field(default=0.0, alias="baseHeight")

    x_start: float | None = Field(default=None, alias="xStart")
    y_start: float | None = Field(default=None, alias="yStart")
    length: float | None = Field(default=None, alias="length")
    width: float | None = Field(default=None, alias="width")
    canopy_rotation: float | None = Field(default=None, alias="canopyRotation")

    x_vertex: list[float] = Field(default_factory=list, alias="xVertex")
    y_vertex: list[float] = Field(default_factory=list, alias="yVertex")

    _wrap_x_vertex = field_validator("x_vertex", mode="before")(_as_list)
    _wrap_y_vertex = field_validator("y_vertex", mode="before")(_as_list)

    @model_validator(mode="after")
    def _require_footprint(self) -> Homogeneous:
        rect = (self.length is not None and self.length > 0.0) and (
            self.width is not None and self.width > 0.0
        )
        poly = len(self.x_vertex) > 0 and len(self.y_vertex) > 0
        if not rect and not poly:
            raise ValueError(
                "Homogeneous needs a rectangle (length/width > 0) "
                "or a polygon (x_vertex/y_vertex)"
            )
        if poly and len(self.x_vertex) != len(self.y_vertex):
            raise ValueError("x_vertex and y_vertex must have the same length")
        return self


class IsolatedTree(QESModel):
    """`<IsolatedTree>` canopy (circular crown, Margairaz 2021 / Lee et al.)."""

    attenuation_coefficient: float = Field(..., alias="attenuationCoefficient")
    height: float = Field(..., alias="height")
    z_max_lai: float = Field(..., alias="zMaxLAI")
    base_height: float = Field(default=0.0, alias="baseHeight")
    x_center: float = Field(..., alias="xCenter")
    y_center: float = Field(..., alias="yCenter")
    width: float = Field(..., alias="width")


class VegetationParameters(QESModel):
    """`<vegetationParams>` block: canopies and/or a tree shapefile.

    - :class:`Homogeneous` — uniform Cionco canopy (rectangle or polygon).
    - :class:`IsolatedTree` — one XML block per tree.
    - Point shapefile via ``SHPFile`` / ``SHPTreeLayer`` (fields ``H``, ``D``,
      ``LAI``).
    """

    wake_flag: int = Field(default=1, alias="wakeFlag")
    num_canopies: int | None = Field(default=None, alias="num_canopies")
    shp_file: str | None = Field(default=None, alias="SHPFile")
    shp_tree_layer: str | None = Field(default=None, alias="SHPTreeLayer")
    homogeneous: list[Homogeneous] = Field(
        default_factory=list, alias="Homogeneous"
    )
    isolated_trees: list[IsolatedTree] = Field(
        default_factory=list, alias="IsolatedTree"
    )

    _wrap_homogeneous = field_validator("homogeneous", mode="before")(_as_list)
    _wrap_trees = field_validator("isolated_trees", mode="before")(_as_list)


class FileOptions(QESModel):
    """`<fileOptions>` block: NetCDF output configuration."""

    output_flag: int = Field(default=1, alias="outputFlag")
    output_fields: list[str] = Field(default_factory=lambda: ["all"], alias="outputFields")

    _wrap_output_fields = field_validator("output_fields", mode="before")(_as_list)


class WindsParameters(QESModel):
    """Full `<QESWindsParameters>` document."""

    simulation_parameters: SimulationParameters = Field(
        default_factory=SimulationParameters, alias="simulationParameters"
    )
    met_params: MetParams = Field(default_factory=MetParams, alias="metParams")
    buildings_params: BuildingsParams = Field(
        default_factory=BuildingsParams, alias="buildingsParams"
    )
    vegetation_params: VegetationParameters | None = Field(
        default=None, alias="vegetationParams"
    )
    turb_params: TurbParams | None = Field(default=None, alias="turbParams")
    file_options: FileOptions = Field(default_factory=FileOptions, alias="fileOptions")

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize to JSON using Pythonic field names."""
        return self.model_dump_json(indent=indent, by_alias=False)

    @classmethod
    def from_json(cls, data: str | bytes) -> WindsParameters:
        """Deserialize from JSON (accepts field names or XML aliases)."""
        return cls.model_validate_json(data)


class TimeSeries(QESModel):
    """`<timeSeries>` block of a QES sensor file."""

    time_stamp: str = Field(default="2020-01-01T00:00:00", alias="timeStamp")
    boundary_layer_flag: int = Field(default=2, alias="boundaryLayerFlag")
    site_z0: float = Field(default=0.1, alias="siteZ0")
    reciprocal: float = Field(default=0.0, alias="reciprocal")
    height: float = Field(default=10.0, alias="height")
    speed: float = Field(default=3.0, alias="speed")
    direction: float = Field(default=270.0, alias="direction")
    canopy_height: float = Field(default=3.0, alias="canopyHeight")
    attenuation_coefficient: float = Field(default=1.0, alias="attenuationCoefficient")


class SensorParameters(QESModel):
    """Full `<sensor>` document."""

    site_coord_flag: int = Field(default=1, alias="site_coord_flag")
    site_x_coord: float = Field(default=0.0, alias="site_xcoord")
    site_y_coord: float = Field(default=0.0, alias="site_ycoord")
    time_series: list[TimeSeries] = Field(
        default_factory=lambda: [TimeSeries()], alias="timeSeries"
    )

    _wrap_time_series = field_validator("time_series", mode="before")(_as_list)

    def to_json(self, *, indent: int | None = 2) -> str:
        return self.model_dump_json(indent=indent, by_alias=False)

    @classmethod
    def from_json(cls, data: str | bytes) -> SensorParameters:
        return cls.model_validate_json(data)
