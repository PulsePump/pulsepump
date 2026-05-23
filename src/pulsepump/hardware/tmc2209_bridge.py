"""Host-side mpremote bridge for TMC2209 stepper motor controller."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from importlib import resources
from pathlib import Path

from .pico_loader import PicoNotFoundError, find_pico_port  # noqa: F401 — re-exported


def _mpremote_bin() -> str:
    return str(Path(sys.executable).parent / "mpremote")


def _firmware_file(name: str) -> Path:
    ref = resources.files("pulsepump.firmware").joinpath(name)
    with resources.as_file(ref) as p:
        return Path(p)


class Tmc2209Bridge:
    def __init__(self, port: str = "auto") -> None:
        self.port = port
        self._timeout = 10.0

    def _port_args(self) -> list[str]:
        if self.port == "auto":
            return []
        return ["connect", self.port]

    def list_ports(self) -> list[str]:
        result = subprocess.run(
            [_mpremote_bin(), "connect", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        ports = []
        for line in result.stdout.splitlines():
            m = re.match(r"^(\S+)\s", line.strip())
            if m:
                ports.append(m.group(1))
        return ports

    def upload_firmware(self) -> None:
        for name in ("tmc2209.py", "commands.py"):
            src = _firmware_file(name)
            cmd = [_mpremote_bin(), *self._port_args(), "cp", str(src), f":{name}"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                raise RuntimeError(f"mpremote cp {name} failed: {result.stderr or result.stdout}")

    def run_command(self, cmd_dict: dict, timeout: float | None = None) -> dict:
        timeout = timeout or self._timeout
        payload = json.dumps(cmd_dict)
        payload_escaped = payload.replace("'", "\\'")
        exec_str = f"import commands; commands.run('{payload_escaped}')"
        cmd = [_mpremote_bin(), *self._port_args(), "exec", exec_str]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"mpremote timed out after {timeout}s") from exc

        if result.returncode != 0:
            raise RuntimeError(
                f"mpremote exec failed (exit {result.returncode}): {result.stderr or result.stdout}"
            )

        stdout = result.stdout.strip()
        # Strip REPL prompt artefacts (>>> or ... lines)
        lines = [
            line
            for line in stdout.splitlines()
            if not line.startswith(">>>") and not line.startswith("...")
        ]
        clean = "\n".join(lines).strip()

        if not clean:
            raise RuntimeError("mpremote exec returned no output")

        try:
            response = json.loads(clean)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON from device: {clean!r}") from exc

        if not response.get("ok"):
            raise RuntimeError(f"Device error: {response.get('error', 'unknown')}")

        return response
