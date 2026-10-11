#!/usr/bin/env python3
"""Control local de una Hue Go LCT026 mediante Bluetooth LE."""

import argparse
import asyncio
import json
import fcntl
import sys
from datetime import datetime
from pathlib import Path
from hue_config import load_config, validate, schedule_date

SERVICE = "0000fe0f-0000-1000-8000-00805f9b34fb"
MODEL = "00002a24-0000-1000-8000-00805f9b34fb"
POWER = "932c32bd-0002-47a2-835a-a8d455b859dd"
BRIGHTNESS = "932c32bd-0003-47a2-835a-a8d455b859dd"


def log(message):
    print(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {message}", flush=True)


async def control(address, turn_on=False, config=None):
    from bleak import BleakClient
    log("Conectando con la Hue Go por Bluetooth.")
    async with BleakClient(address, timeout=20) as client:
        log("Conexión Bluetooth establecida; verificando modelo.")
        model = (await client.read_gatt_char(MODEL)).decode().strip("\x00 ")
        if model != "LCT026":
            raise RuntimeError(f"Modelo inesperado: {model!r}. No se modificó la luz.")
        log("Modelo LCT026 confirmado; leyendo estado de encendido.")
        before = bytes(await client.read_gatt_char(POWER))
        if turn_on:
            if config is not None and schedule_date(datetime.now().astimezone(), config) is None:
                raise RuntimeError("La ventana horaria terminó antes de enviar el encendido.")
            log("Enviando orden de encendido.")
            await client.write_gatt_char(POWER, b"\x01", response=True)
        after = bytes(await client.read_gatt_char(POWER))
        brightness = bytes(await client.read_gatt_char(BRIGHTNESS))
        if turn_on and after != b"\x01":
            raise RuntimeError(f"El encendido no se confirmó: {after.hex()}")
        return {"model": model, "power_before": before.hex(),
                "power": after.hex(), "brightness_raw": brightness.hex()}


async def main(args):
    if args.command == "scan":
        from bleak import BleakScanner
        devices = await BleakScanner.discover(
            timeout=15, service_uuids=[SERVICE], return_adv=True
        )
        print(json.dumps([
            {"name": adv.local_name or device.name, "address": device.address,
             "rssi": adv.rssi}
            for device, adv in devices.values()
        ], indent=2))
        return

    config = load_config(args.config) if args.config else validate({"address": args.address})
    address = config["address"]
    scheduled = args.command == "scheduled"
    state_path = Path(__file__).resolve().with_name("last-success.json")
    # El bloqueo dura toda la ejecución, incluso durante los reintentos.
    with state_path.with_suffix(".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("Ya hay otra operación en curso; no se repite.")
            return
        await run_control(address, config, scheduled, state_path, args.command)


async def run_control(address, config, scheduled, state_path, command):
    for attempt in range(3 if scheduled else 1):
        now = datetime.now().astimezone()
        if scheduled:
            date = schedule_date(now, config)
            if date is None:
                log("Horario omitido: fuera de la ventana de 15 minutos del horario local.")
                return
            if state_path.exists():
                last = json.loads(state_path.read_text())
                if last.get("date") == date:
                    log("Encendido diario ya confirmado; no se repite.")
                    return
        try:
            result = await asyncio.wait_for(
                control(address, turn_on=command in ("on", "scheduled"),
                        config=config if scheduled else None),
                timeout=50,
            )
            log(json.dumps(result))
            if scheduled:
                temporary = state_path.with_suffix(".tmp")
                temporary.write_text(json.dumps({"date": date}))
                temporary.replace(state_path)
            return
        except Exception as error:
            log(f"Intento {attempt + 1}: {type(error).__name__}: {error}")
            if not scheduled or attempt == 2:
                raise
            await asyncio.sleep(10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["scan", "status", "on", "scheduled"])
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--address")
    target.add_argument("--config")
    options = parser.parse_args()
    try:
        asyncio.run(main(options))
    except Exception as error:
        log(f"ERROR {type(error).__name__}: {error}")
        sys.exit(1)
