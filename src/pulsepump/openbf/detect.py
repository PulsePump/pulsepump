from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

INSTALL_JULIA_URL = "https://julialang.org/downloads/"
INSTALL_OPENBF_CMD = "julia -e 'import Pkg; Pkg.add(\"openBF\")'"


@dataclass(frozen=True)
class JuliaStatus:
    julia_found: bool
    julia_version: str
    openbf_found: bool
    error: str


def check_julia() -> JuliaStatus:
    if shutil.which("julia") is None:
        return JuliaStatus(
            julia_found=False,
            julia_version="",
            openbf_found=False,
            error="julia not found on PATH",
        )
    try:
        result = subprocess.run(
            ["julia", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version = result.stdout.strip() or result.stderr.strip()
    except Exception as exc:
        return JuliaStatus(
            julia_found=False,
            julia_version="",
            openbf_found=False,
            error=str(exc),
        )
    return JuliaStatus(
        julia_found=True,
        julia_version=version,
        openbf_found=False,
        error="",
    )


def check_openbf() -> JuliaStatus:
    base = check_julia()
    if not base.julia_found:
        return base
    try:
        result = subprocess.run(
            ["julia", "-e", "using openBF; println(pkgversion(openBF))"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return JuliaStatus(
                julia_found=True,
                julia_version=base.julia_version,
                openbf_found=True,
                error="",
            )
        return JuliaStatus(
            julia_found=True,
            julia_version=base.julia_version,
            openbf_found=False,
            error=(result.stderr or result.stdout).strip(),
        )
    except Exception as exc:
        return JuliaStatus(
            julia_found=True,
            julia_version=base.julia_version,
            openbf_found=False,
            error=str(exc),
        )
