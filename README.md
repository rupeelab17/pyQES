# pyQES

[![PyPI version](https://img.shields.io/pypi/v/pyqes.svg)](https://pypi.org/project/pyqes/)
[![Python versions](https://img.shields.io/pypi/pyversions/pyqes.svg)](https://pypi.org/project/pyqes/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Platforms](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)](https://pypi.org/project/pyqes/)

**Version:** `2.3.1` · **Python:** `≥ 3.10` · **License:** [GPL-3.0-only](LICENSE)

Python bindings for the [Quick Environmental Simulation (QES)](https://github.com/UtahEFD/QES-Public) C++ suite — **QES-Winds**, **QES-Plume**, and **QES-Fire**.

The C++ core lives in the [`qes-core`](https://github.com/rupeelab17/QES-Public) git submodule (fork of [UtahEFD/QES-Public](https://github.com/UtahEFD/QES-Public), branch `develop_pyqes`). This repository ships the pybind11 wrappers, the `pyQES` package, examples, and GitHub Actions for wheels / PyPI.

> **GPU:** NVIDIA GPU with Compute Capability **7.0+** (CUDA wheel on Linux). CPU builds work without CUDA.

---

## Table of contents

- [Features](#features)
- [Compatibility](#compatibility)
- [Installation](#installation)
- [Build from source](#build-from-source)
- [Quick start](#quick-start)
- [Package layout](#package-layout)
- [Examples](#examples)
- [Development](#development)
- [Continuous integration](#continuous-integration)
- [Updating the QES core](#updating-the-qes-core)
- [Links](#links)
- [License](#license)

---

## Features

- Run **QES-Winds** from Python (`config` / XML / JSON), with optional DEM / buildings preprocessing
- Export wind magnitude to georeferenced GeoTIFF (`pywinds.to_tif`)
- Run **QES-Plume** on winds + turbulence NetCDF fields
- Run coupled **QES-Fire** (optional smoke plume)
- Pydantic v2 config models, XML/JSON I/O, geospatial helpers
- Prebuilt **CPU wheels** for Linux, macOS (arm64), and Windows; optional Linux **CUDA** wheel

---

## Compatibility

| | |
|---|---|
| **Package version** | `2.3.1` |
| **Python** | 3.10 · 3.11 · 3.12 · 3.13 |
| **OS (CPU wheels)** | Linux `x86_64` (manylinux_2_28) · macOS `arm64` (deployment target 14.0+) · Windows `AMD64` |
| **GPU wheel** | Linux CUDA (cp312), NVIDIA CC ≥ 7.0 |
| **Build system** | [scikit-build-core](https://scikit-build-core.readthedocs.io/) ≥ 1.0 · CMake ≥ 3.18 · C++17 · pybind11 ≥ 2.12 |

### Runtime dependencies

| Extra | Packages | Role |
|-------|----------|------|
| *(core)* | `pydantic≥2`, `numpy` | Config models & arrays |
| `geo` | `rasterio`, `pyproj`, `geopandas` | DEM / buildings preprocessing, GeoTIFF export |
| `io` | `netCDF4` | NetCDF helpers |

### Native libraries (from-source builds)

Boost (program-options, date-time, property-tree, optional), NetCDF-C++, GDAL — install via system packages or the included [vcpkg](https://learn.microsoft.com/en-us/vcpkg/) manifest (`vcpkg.json`).

---

## Installation

### From PyPI

```bash
pip install pyqes

# optional extras
pip install "pyqes[geo]"      # geospatial preprocessing / GeoTIFF
pip install "pyqes[io]"       # NetCDF helpers
pip install "pyqes[geo,io]"   # both
```

```bash
# with uv
uv add pyqes
uv add "pyqes[geo,io]"
```

Verify:

```python
import pyQES
print(pyQES.__version__)  # e.g. 2.3.1
```

### From source

```bash
git clone --recursive https://github.com/rupeelab17/pyQES.git
cd pyQES

# Native deps (macOS Homebrew example)
brew install boost netcdf-cxx gdal

# Editable install + extras ([uv](https://docs.astral.sh/uv/))
uv sync --extra geo --extra io
```

Always clone or pull with submodules:

```bash
git pull --recurse-submodules
# or
git submodule update --init --recursive
```

---

## Build from source

Requirements beyond Python:

- C++17 compiler
- CMake ≥ 3.18
- Git with submodule support
- Native libs: Boost, NetCDF-C++, GDAL (or vcpkg via the repo manifest)

```bash
# after clone --recursive
uv sync --extra geo --extra io
# or
pip install -e ".[geo,io]"
```

Wheels are built with [cibuildwheel](https://cibuildwheel.pypa.io/) (see [Continuous integration](#continuous-integration)).

---

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

# optional GeoTIFF of |V| at 1.5 m AGL (needs pyqes[geo,io])
tif = pywinds.to_tif(z=1.5)
print(tif)
```

`pywinds.run` accepts exactly one of `config`, `xml`, or `json` (or none, with keyword overrides). Solvers: `"cpu"` / `"gpu"` (or the QES integer code).

---

## Package layout

| Module | Role |
|--------|------|
| `pyQES.pywinds` | QES-Winds — `run(...)`, `to_tif(...)` |
| `pyQES.pyplume` | QES-Plume — `run(xml=..., winds_file=..., turb_file=...)` |
| `pyQES.pyfire` | Coupled QES-Fire — `run(...)` (+ optional `plume_xml`) |
| `pyQES.util` | Pydantic config, XML/JSON I/O, paths, geo helpers, NetCDF→GeoTIFF |
| `pyQES._winds` / `_plume` / `_fire` / `_util` | Compiled pybind11 extensions |

Config models live in `pyQES.util.config`: `WindsParameters`, `SimulationParameters`, `SensorParameters`, `TimeSeries`, etc.

---

## Examples

Sample La Rochelle / UMEP inputs: [`examples/umep_workflow/`](examples/umep_workflow/) (DEM, buildings, mask, QES XML).

```bash
uv run python examples/run_winds_demo.py
uv run python examples/run_winds_demo.py --speed 5 --direction 180
uv run python examples/umep_workflow/run_qeswinds.py
uv run python examples/umep_workflow/run_qeswinds_args.py --speed 5 --direction 180
```

---

## Development

```bash
uv sync --extra geo --extra io

# lint / typecheck
uv run ruff check pyQES tests examples
uv run mypy

# fast unit tests (no full solver run)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest tests -m "not slow"

# end-to-end winds run (compiled extension + example data)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest tests -m slow
```

Dev tools (via `[dependency-groups] dev`): pytest, pytest-cov, ruff, mypy, plus the `geo` / `io` extras.

---

## Continuous integration

| Workflow | Role |
|----------|------|
| [`ci.yml`](.github/workflows/ci.yml) | Ruff, mypy, pure-Python pytest |
| [`wheels.yml`](.github/workflows/wheels.yml) | CPU wheels — Linux / macOS / Windows · cp310–cp313 · sdist |
| [`cuda-build.yml`](.github/workflows/cuda-build.yml) | Linux CUDA wheel (cp312) |
| [`publish.yml`](.github/workflows/publish.yml) | Publish to PyPI on `v*` tags |

---

## Updating the QES core

```bash
git submodule update --remote qes-core
git add qes-core
git commit -m "Bump qes-core"
```

---

## Links

| | |
|---|---|
| **Homepage / source** | <https://github.com/rupeelab17/pyQES> |
| **PyPI** | <https://pypi.org/project/pyqes/> |
| **QES documentation** | <https://qes-documentation.readthedocs.io/en/latest> |
| **QES core (submodule)** | <https://github.com/rupeelab17/QES-Public> |
| **Upstream QES** | <https://github.com/UtahEFD/QES-Public> |

---

## License

**GPL-3.0-only** — see [LICENSE](LICENSE).

QES core: see [`qes-core/LICENSE`](qes-core/LICENSE).
