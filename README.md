# pyQES

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![PyPI version](https://img.shields.io/pypi/v/pyqes.svg)](https://pypi.org/project/pyqes/)

Python bindings for the [Quick Environmental Simulation (QES)](https://github.com/UtahEFD/QES-Public) C++ suite (QES-Winds, QES-Plume, QES-Fire).

The C++ core lives in the `qes-core` git submodule ([rupeelab17/QES-Public](https://github.com/rupeelab17/QES-Public), upstream [UtahEFD/QES-Public](https://github.com/UtahEFD/QES-Public)). This repository contains only the pybind11 wrappers, the Python package, an example, and GitHub Actions for wheels / PyPI.

> GPU acceleration requires an NVIDIA GPU with Compute Capability 7.0+. CPU builds work without CUDA.

## Requirements

- Python ≥ 3.10
- C++17 compiler
- Native libs: Boost, NetCDF-C++, GDAL (or [vcpkg](https://learn.microsoft.com/en-us/vcpkg/) via the included manifest)
- Git with submodule support

## Install (PyPI)

```bash
pip install pyqes
# optional geospatial / NetCDF helpers
pip install "pyqes[geo,io]"
```

## Build from source

```bash
git clone --recursive https://github.com/rupeelab17/pyQES.git
cd pyQES

# Native deps (macOS Homebrew example)
brew install boost netcdf-cxx gdal

# Editable install + extension build ([uv](https://docs.astral.sh/uv/))
uv sync --extra geo --extra io
```

Always clone or pull with submodules:

```bash
git pull --recurse-submodules
# or
git submodule update --init --recursive
```

## Quick start

```python
from pyQES import pywinds
from pyQES.util.config import WindsParameters, SensorParameters, TimeSeries

params = WindsParameters()
params.simulation_parameters.dem = "path/to/DEM.tif"
params.simulation_parameters.cell_size = (2.0, 2.0, 0.5)
params.simulation_parameters.halo_x = 40.0
params.simulation_parameters.halo_y = 40.0
params.simulation_parameters.domain_rotation = 0.0  # must be 0

sensor = SensorParameters(
    time_series=[TimeSeries(speed=3.0, direction=270.0, height=10.0, site_z0=0.24)]
)
result = pywinds.run(config=params, sensor=sensor, solver="cpu", work_dir="/tmp/qes_out")
print(result.winds_out)
```

See [`examples/run_winds_demo.py`](examples/run_winds_demo.py) for a CLI-style demo.

| Submodule | Role |
|-----------|------|
| `pyQES.pywinds` | Run QES-Winds (`run(...)`) |
| `pyQES.pyplume` | Run QES-Plume |
| `pyQES.pyfire` | Run coupled QES-Fire |
| `pyQES.util` | Pydantic config, XML/JSON I/O, geospatial helpers |

## Tests

```bash
# Fast unit tests (no full solver run)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest tests -m "not slow"

# End-to-end winds run (compiled extension + sample data under qes-core/data)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest tests -m slow
```

## Continuous Integration

| Workflow | Role |
|----------|------|
| [`ci.yml`](.github/workflows/ci.yml) | Ruff, mypy, pure-Python pytest |
| [`wheels.yml`](.github/workflows/wheels.yml) | CPU wheels (Linux / macOS / Windows) |
| [`cuda-build.yml`](.github/workflows/cuda-build.yml) | Linux CUDA wheel |
| [`publish.yml`](.github/workflows/publish.yml) | Publish to PyPI on `v*` tags |

## Updating the QES core submodule

```bash
git submodule update --remote qes-core
git add qes-core
git commit -m "Bump qes-core"
```

## License

GPL-3.0 — see [LICENSE](LICENSE). QES core: see `qes-core/LICENSE`.
