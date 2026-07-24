# syntax=docker/dockerfile:1.7
#
# Build (requires qes-core submodule populated):
#   git clone --recursive https://github.com/rupeelab17/pyQES.git
#   cd pyQES && docker build -t pyqes .
#
# Run:
#   docker run --rm -it -v "$PWD:/app" pyqes

FROM python:3.13-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# ─── APT (Boost, NetCDF-C++, GDAL) ───────────────────────────────────────────
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    export DEBIAN_FRONTEND=noninteractive && \
    rm -f /var/cache/apt/archives/lock /var/lib/dpkg/lock /var/lib/dpkg/lock-frontend && \
    apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
      build-essential cmake git pkg-config \
      libboost-all-dev \
      libnetcdf-dev libnetcdf-c++4-dev netcdf-bin \
      libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Venv outside /app so bind-mount ./:/app does not shadow installed packages.
# Debian puts GDAL headers in /usr/include/gdal; FindGDAL CONFIG often leaves
# GDAL_INCLUDE_DIR empty → fatal gdal_priv.h during qesutil build.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    CMAKE_ARGS="-DGDAL_INCLUDE_DIR=/usr/include/gdal" \
    CXXFLAGS="-I/usr/include/gdal"

# ─── PYTHON / NATIVE BUILD (uv) ──────────────────────────────────────────────
COPY pyproject.toml uv.lock CMakeLists.txt LICENSE README.md ./
COPY vcpkg.json vcpkg-configuration.json ./
COPY native ./native
COPY pyQES ./pyQES
COPY qes-core ./qes-core
COPY overlays ./overlays

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --extra geo --extra io --no-dev --frozen

ENV PATH="/opt/venv/bin:${PATH}" \
    VIRTUAL_ENV=/opt/venv

COPY . .

RUN python -c "import pyQES; print('pyQES', getattr(pyQES, '__version__', 'ok'))"

CMD ["python"]
