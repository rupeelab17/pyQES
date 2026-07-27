"""Tests for pydantic <-> QES XML conversion."""

from __future__ import annotations

from pyQES.util.config import (
    Homogeneous,
    IsolatedTree,
    VegetationParameters,
    WindsParameters,
)
from pyQES.util.xml_io import (
    from_qes_xml,
    from_sensor_xml,
    to_qes_xml,
    write_qes_xml,
)


def test_parse_umep_winds_xml(winds_xml):
    params = from_qes_xml(winds_xml)
    sim = params.simulation_parameters
    assert sim.domain == (146, 99, 89)
    assert sim.cell_size == (2.0, 2.0, 0.5)
    assert sim.halo_x == 40.0
    assert sim.halo_y == 40.0
    assert sim.domain_rotation == 90.0

    assert params.buildings_params.shp_height_field == "hauteur"
    assert params.buildings_params.shp_building_layer == "buildings_clipped"
    assert params.met_params.sensor_names == ["sensor_umep.xml"]
    assert "mag" in params.file_options.output_fields


def test_winds_xml_round_trip(winds_xml, tmp_path):
    params = from_qes_xml(winds_xml)
    out = write_qes_xml(params, tmp_path / "round_trip.xml")
    restored = from_qes_xml(out)
    assert restored == params


def test_to_qes_xml_contains_expected_tags():
    params = WindsParameters()
    params.simulation_parameters.domain = (12, 34, 56)
    xml = to_qes_xml(params)
    assert "<QESWindsParameters>" in xml
    assert "<simulationParameters>" in xml
    assert "<domain>12 34 56</domain>" in xml
    assert "<vegetationParams>" not in xml


def test_vegetation_xml_round_trip(tmp_path):
    params = WindsParameters()
    params.simulation_parameters.domain = (200, 200, 200)
    params.vegetation_params = VegetationParameters(
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
    xml = to_qes_xml(params)
    assert "<vegetationParams>" in xml
    assert "<IsolatedTree>" in xml
    assert "<attenuationCoefficient>3.0</attenuationCoefficient>" in xml
    assert "<xCenter>20.0</xCenter>" in xml
    assert "<num_canopies>1</num_canopies>" in xml

    out = write_qes_xml(params, tmp_path / "veg.xml")
    restored = from_qes_xml(out)
    assert restored.vegetation_params is not None
    assert len(restored.vegetation_params.isolated_trees) == 1
    tree = restored.vegetation_params.isolated_trees[0]
    assert tree.height == 15.0
    assert tree.width == 10.0
    assert restored.vegetation_params.num_canopies == 1


def test_vegetation_shp_xml():
    params = WindsParameters()
    params.vegetation_params = VegetationParameters(
        shp_file="qes/trees.shp",
        shp_tree_layer="trees",
    )
    xml = to_qes_xml(params)
    assert "<SHPFile>qes/trees.shp</SHPFile>" in xml
    assert "<SHPTreeLayer>trees</SHPTreeLayer>" in xml
    assert "<IsolatedTree>" not in xml
    assert "<Homogeneous>" not in xml


def test_homogeneous_rect_xml_round_trip(tmp_path):
    params = WindsParameters()
    params.simulation_parameters.domain = (200, 200, 200)
    params.vegetation_params = VegetationParameters(
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
    xml = to_qes_xml(params)
    assert "<Homogeneous>" in xml
    assert "<xStart>80.0</xStart>" in xml
    assert "<length>40.0</length>" in xml
    assert "<xVertex>" not in xml

    out = write_qes_xml(params, tmp_path / "homog.xml")
    restored = from_qes_xml(out)
    assert restored.vegetation_params is not None
    canopy = restored.vegetation_params.homogeneous[0]
    assert canopy.height == 10.0
    assert canopy.width == 80.0
    assert canopy.x_start == 80.0


def test_homogeneous_polygon_xml_round_trip(tmp_path):
    params = WindsParameters()
    params.vegetation_params = VegetationParameters(
        num_canopies=1,
        homogeneous=[
            Homogeneous(
                attenuation_coefficient=0.81,
                height=5.1,
                base_height=0.0,
                x_vertex=[25.0, 25.0, 175.0, 175.0],
                y_vertex=[25.0, 175.0, 175.0, 25.0],
            )
        ],
    )
    xml = to_qes_xml(params)
    assert xml.count("<xVertex>") == 4
    assert xml.count("<yVertex>") == 4
    assert "<xStart>" not in xml

    out = write_qes_xml(params, tmp_path / "homog_poly.xml")
    restored = from_qes_xml(out)
    canopy = restored.vegetation_params.homogeneous[0]
    assert canopy.x_vertex == [25.0, 25.0, 175.0, 175.0]
    assert canopy.y_vertex == [25.0, 175.0, 175.0, 25.0]


def test_parse_sensor_xml(sensor_xml):
    sensor = from_sensor_xml(sensor_xml)
    assert sensor.site_coord_flag == 1
    assert len(sensor.time_series) == 1
    ts = sensor.time_series[0]
    assert ts.speed == 3.0
    assert ts.direction == 270.0
