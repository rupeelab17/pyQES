"""Unit tests for the pyQES pydantic configuration models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pyQES.util.config import (
    Homogeneous,
    IsolatedTree,
    SimulationParameters,
    VegetationParameters,
    WindsParameters,
)


def test_defaults_and_types():
    params = WindsParameters()
    assert params.simulation_parameters.domain == (1, 1, 1)
    assert params.simulation_parameters.cell_size == (1.0, 1.0, 1.0)
    assert params.file_options.output_fields == ["all"]
    assert params.turb_params is None
    assert params.vegetation_params is None


def test_json_round_trip():
    params = WindsParameters()
    params.simulation_parameters.domain = (10, 20, 30)
    params.simulation_parameters.halo_x = 40.0
    restored = WindsParameters.from_json(params.to_json())
    assert restored == params


def test_vegetation_json_round_trip():
    params = WindsParameters()
    params.vegetation_params = VegetationParameters(
        num_canopies=1,
        isolated_trees=[
            IsolatedTree(
                attenuation_coefficient=3.0,
                height=15.0,
                z_max_lai=0.7,
                x_center=20.0,
                y_center=100.0,
                width=10.0,
            )
        ],
    )
    restored = WindsParameters.from_json(params.to_json())
    assert restored == params
    assert restored.vegetation_params is not None
    assert len(restored.vegetation_params.isolated_trees) == 1
    assert restored.vegetation_params.isolated_trees[0].height == 15.0


def test_homogeneous_rect_json_round_trip():
    params = WindsParameters()
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
    restored = WindsParameters.from_json(params.to_json())
    assert restored == params
    assert restored.vegetation_params is not None
    assert restored.vegetation_params.homogeneous[0].length == 40.0


def test_homogeneous_polygon_and_alias_wrap():
    veg = VegetationParameters.model_validate(
        {
            "Homogeneous": {
                "attenuationCoefficient": 0.81,
                "height": 5.1,
                "baseHeight": 0.0,
                "xVertex": ["25", "25", "175", "175"],
                "yVertex": ["25", "175", "175", "25"],
            }
        }
    )
    assert len(veg.homogeneous) == 1
    canopy = veg.homogeneous[0]
    assert canopy.attenuation_coefficient == 0.81
    assert canopy.x_vertex == [25.0, 25.0, 175.0, 175.0]
    assert canopy.y_vertex == [25.0, 175.0, 175.0, 25.0]


def test_homogeneous_requires_footprint():
    with pytest.raises(ValidationError):
        Homogeneous(attenuation_coefficient=1.0, height=10.0)


def test_vegetation_alias_and_single_tree_wrap():
    veg = VegetationParameters.model_validate(
        {
            "IsolatedTree": {
                "attenuationCoefficient": 2.0,
                "height": 10.0,
                "zMaxLAI": 0.5,
                "xCenter": 1.0,
                "yCenter": 2.0,
                "width": 4.0,
            }
        }
    )
    assert len(veg.isolated_trees) == 1
    assert veg.isolated_trees[0].attenuation_coefficient == 2.0


def test_vegetation_shp_fields():
    veg = VegetationParameters(shp_file="trees.shp", shp_tree_layer="trees")
    assert veg.shp_file == "trees.shp"
    assert veg.shp_tree_layer == "trees"


def test_alias_population_and_space_separated_vector():
    params = WindsParameters.model_validate(
        {"simulationParameters": {"domain": "10 20 30", "cellSize": "2 2 0.5"}}
    )
    assert params.simulation_parameters.domain == (10, 20, 30)
    assert params.simulation_parameters.cell_size == (2.0, 2.0, 0.5)


def test_field_name_population():
    sim = SimulationParameters(halo_x=15.0, domain=(5, 6, 7))
    assert sim.halo_x == 15.0
    assert sim.domain == (5, 6, 7)


def test_invalid_domain_raises():
    with pytest.raises(ValidationError):
        SimulationParameters(domain=(1, 2))  # wrong arity
