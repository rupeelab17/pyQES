# ====================================================================================
# pyQES — Python bindings for QES
#
# Builds the QES C++ core (submodule qes-core) as libraries only, then the
# pybind11 extension modules under native/.
# ====================================================================================

cmake_minimum_required(VERSION 3.24)
cmake_policy(SET CMP0074 NEW)

project(pyQES VERSION 2.3.1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# find_package() in qes-core creates IMPORTED targets (GDAL::GDAL, netCDF::*,
# …) that are directory-scoped by default. native/ is a sibling of qes-core, so
# those targets must be promoted to global visibility.
set(CMAKE_FIND_PACKAGE_TARGETS_GLOBAL ON)

# Core as libraries only (no CLI / examples / CPack).
set(QES_BUILD_APPS OFF CACHE BOOL "Build QES CLI apps" FORCE)
set(ENABLE_TESTS OFF CACHE BOOL "Enable QES C++ tests" FORCE)
# Legacy flag on older qes-core checkouts — keep bindings out of the submodule.
set(QES_BUILD_PYTHON OFF CACHE BOOL "Legacy: build bindings inside qes-core" FORCE)

if (NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/qes-core/CMakeLists.txt")
  message(FATAL_ERROR
    "qes-core submodule missing. Run:\n"
    "  git submodule update --init --recursive")
endif()

add_subdirectory(qes-core)

find_package(pybind11 CONFIG REQUIRED)
message(STATUS "Building pyQES pybind11 modules (pybind11 ${pybind11_VERSION}).")
add_subdirectory(native)
