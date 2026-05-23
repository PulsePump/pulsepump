"""Hardware Bench: flexible test rig for servos, steppers, and pressure sensors.

The bench owns a single Pico over UART, a configurable set of device instances
(0-2 of each kind), a run recorder that writes Parquet per device + a JSON
manifest, and a signal registry that backs live plotting.

Wire format (newline-delimited JSON over UART, both directions)
----------------------------------------------------------------

Host → Pico:

    {"cmd": "configure", "devices": [<DeviceConfig>, ...]}
        Full (re-)configure. May be called mid-run; the firmware diffs against
        its current set, instantiates new devices, tears down removed ones,
        and reconfigures those that changed.

    {"cmd": "start_streaming"}
    {"cmd": "stop_streaming"}

    {"cmd": "set", "id": "servo0", "field": "angle_deg", "value": 42.0}
        Generic setter for a device output (e.g. servo angle, stepper enable).

    {"cmd": "step", "id": "stepper0", "steps": 200, "rate_hz": 1000, "dir": 1}
        Stepper move command (count + rate + direction).

    {"cmd": "read_now", "id": "<dev>"}
        Force an immediate sample frame for that device.

Pico → Host:

    {"t": <us>, "id": "<dev>", "data": {<signal_name>: <number>, ...}}
        Sample frame. ``t`` is microseconds since the firmware booted.

    {"event": "hello", "fw": "bench-0.1", "caps": {...}}
        Sent once on boot.

    {"event": "configured", "id": "<dev>", "ok": true}
    {"event": "error", "id": "<dev>"|null, "msg": "..."}
"""

from __future__ import annotations

FW_VERSION = "bench-0.1"
WIRE_VERSION = 1
"""Bumped if the JSON frame format changes incompatibly."""
