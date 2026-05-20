"""MicroPython command dispatcher for TMC2209 — called via mpremote exec."""

import ujson
from tmc2209 import TMC2209

_tmc = None


def _get_tmc() -> TMC2209:
    global _tmc
    if _tmc is None:
        _tmc = TMC2209(uart_id=0, tx_pin=0, rx_pin=1, slave_addr=0)
    return _tmc


def run(cmd_json: str) -> None:
    global _tmc
    try:
        cmd = ujson.loads(cmd_json)
        name = cmd["cmd"]

        if name == "init":
            _tmc = TMC2209(
                uart_id=int(cmd.get("uart_id", 0)),
                tx_pin=int(cmd.get("tx_pin", 0)),
                rx_pin=int(cmd.get("rx_pin", 1)),
                slave_addr=int(cmd.get("slave_addr", 0)),
            )
            _tmc.init()
            print(ujson.dumps({"ok": True, "data": {}}))

        elif name == "enable":
            _get_tmc().enable()
            print(ujson.dumps({"ok": True, "data": {}}))

        elif name == "disable":
            _get_tmc().disable()
            print(ujson.dumps({"ok": True, "data": {}}))

        elif name == "set_current":
            _get_tmc().set_current(
                int(cmd["irun"]),
                int(cmd["ihold"]),
                int(cmd.get("iholddelay", 6)),
            )
            print(ujson.dumps({"ok": True, "data": {}}))

        elif name == "set_microsteps":
            _get_tmc().set_microsteps(int(cmd["ms"]))
            print(ujson.dumps({"ok": True, "data": {}}))

        elif name == "set_spreadcycle":
            _get_tmc().set_spreadcycle(bool(cmd["enable"]))
            print(ujson.dumps({"ok": True, "data": {}}))

        elif name == "set_stealthchop_threshold":
            _get_tmc().set_stealthchop_threshold(int(cmd["tpwmthrs"]))
            print(ujson.dumps({"ok": True, "data": {}}))

        elif name == "set_stallguard_threshold":
            _get_tmc().set_stallguard_threshold(int(cmd["sgthrs"]))
            print(ujson.dumps({"ok": True, "data": {}}))

        elif name == "set_coolthrs":
            _get_tmc().set_coolthrs(int(cmd["tcoolthrs"]))
            print(ujson.dumps({"ok": True, "data": {}}))

        elif name == "set_shaft":
            _get_tmc().set_shaft(bool(cmd["invert"]))
            print(ujson.dumps({"ok": True, "data": {}}))

        elif name == "set_chopper":
            _get_tmc().set_chopper_config(
                toff=int(cmd.get("toff", 5)),
                hstrt=int(cmd.get("hstrt", 4)),
                hend=int(cmd.get("hend", 0)),
                tbl=int(cmd.get("tbl", 2)),
            )
            print(ujson.dumps({"ok": True, "data": {}}))

        elif name == "read_status":
            tmc = _get_tmc()
            data = {
                "gstat": tmc.read_gstat(),
                "drv_status": tmc.read_drv_status(),
                "mscnt": tmc.read_mscnt(),
                "sg_result": tmc.read_sg_result(),
                "tstep": tmc.read_tstep(),
            }
            print(ujson.dumps({"ok": True, "data": data}))

        elif name == "read_position":
            tmc = _get_tmc()
            data = {
                "mscnt": tmc.read_mscnt(),
                "mscuract": tmc.read_mscuract(),
            }
            print(ujson.dumps({"ok": True, "data": data}))

        elif name == "read_all":
            tmc = _get_tmc()
            data = {
                "gstat": tmc.read_gstat(),
                "drv_status": tmc.read_drv_status(),
                "mscnt": tmc.read_mscnt(),
                "mscuract": tmc.read_mscuract(),
                "sg_result": tmc.read_sg_result(),
                "tstep": tmc.read_tstep(),
                "ifcnt": tmc.read_ifcnt(),
                "ioin": tmc.read_ioin(),
            }
            print(ujson.dumps({"ok": True, "data": data}))

        else:
            print(ujson.dumps({"ok": False, "error": "unknown command: " + name}))

    except Exception as e:
        print(ujson.dumps({"ok": False, "error": str(e)}))
