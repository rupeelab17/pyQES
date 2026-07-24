#!/usr/bin/env python3
"""Vendor Windows DLLs into a pyQES wheel via delvewheel.

Looks for vcpkg runtime DLLs under the manifest install dir and the
runner's default vcpkg installed tree. CMake -D paths with backslashes
can mis-resolve on Windows, so the build may have used either location.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _candidate_bin_dirs() -> list[Path]:
    ws = Path(os.environ.get("GITHUB_WORKSPACE", os.getcwd()))
    vcpkg_root = Path(os.environ.get("VCPKG_INSTALLATION_ROOT", ""))
    installed = Path(os.environ.get("VCPKG_INSTALLED_DIR", ws / "vcpkg_installed"))

    dirs: list[Path] = [
        installed / "x64-windows" / "bin",
        ws / "vcpkg_installed" / "x64-windows" / "bin",
        vcpkg_root / "installed" / "x64-windows" / "bin",
    ]

    for root in (installed, ws / "vcpkg_installed", vcpkg_root / "installed"):
        if not root.is_dir():
            continue
        for dll in root.rglob("gdal.dll"):
            dirs.append(dll.parent)

    seen: set[str] = set()
    unique: list[Path] = []
    for path in dirs:
        if not path.is_dir():
            continue
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} DEST_DIR WHEEL", file=sys.stderr)
        return 2

    dest_dir, wheel = sys.argv[1], sys.argv[2]
    bins = _candidate_bin_dirs()
    print("delvewheel DLL search paths:")
    for path in bins:
        dlls = sorted(p.name for p in path.glob("*.dll"))
        print(f"  {path} ({len(dlls)} dlls)")
        if "gdal.dll" in dlls:
            print("    has gdal.dll")

    if not any((path / "gdal.dll").is_file() for path in bins):
        print("error: gdal.dll not found in any vcpkg bin directory", file=sys.stderr)
        return 1

    cmd = ["delvewheel", "repair", "-w", dest_dir, "-v", wheel]
    for path in bins:
        cmd.extend(["--add-path", str(path)])
    print("+", subprocess.list2cmdline(cmd))
    subprocess.check_call(cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
