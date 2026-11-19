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
# Los reintentos programados siguen hasta agotar la ventana horaria; este tope es una red de seguridad.
MAX_SCHEDULED_ATTEMPTS = 15


def log(message):
    print(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {message}", flush=True)


async def control(address, turn_on=None, config=None):
    """None consulta; True enciende y False apaga, solo si hace falta."""
    from bleak import BleakClient
    log("Conectando con la Hue Go por Bluetooth.")
    async with BleakClient(address, timeout=20) as client:
        log("Conexión Bluetooth establecida; verificando modelo.")
        model = (await client.read_gatt_char(MODEL)).decode().strip("\x00 ")
        if model != "LCT026":
            raise RuntimeError(f"Modelo inesperado: {model!r}. No se modificó la luz.")
        log("Modelo LCT026 confirmado; leyendo estado de encendido.")
        before = bytes(await client.read_gatt_char(POWER))
        if before not in (b"\x00", b"\x01"):
            raise RuntimeError(f"Estado de encendido inesperado: {before.hex()}. No se modificó la luz.")
        desired = None if turn_on is None else (b"\x01" if turn_on else b"\x00")
        changed = False
        if desired is not None:
            action = "on" if turn_on else "off"
            if config is not None and schedule_date(datetime.now().astimezone(), config, action) is None:
                raise RuntimeError("La ventana horaria terminó antes de confirmar el estado.")
            if before == desired:
                log("La luz ya está encendida; no se envía una orden." if turn_on else
                    "La luz ya está apagada; no se envía una orden.")
            else:
                log("Enviando orden de encendido." if turn_on else "Enviando orden de apagado.")
                await client.write_gatt_char(POWER, desired, response=True)
                changed = True
        after = bytes(await client.read_gatt_char(POWER))
        brightness = bytes(await client.read_gatt_char(BRIGHTNESS))
        if desired is not None and after != desired:
            raise RuntimeError(f"El estado solicitado no se confirmó: {after.hex()}")
        return {"model": model, "power_before": before.hex(),
                "power": after.hex(), "brightness_raw": brightness.hex(), "changed": changed}


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
    action = "on" if command == "on" else None
    if scheduled:
        now = datetime.now().astimezone()
        for candidate in ("on", "off"):
            date = schedule_date(now, config, candidate)
            if date is not None:
                action = candidate
                break
        else:
            log("Horario omitido: fuera de las ventanas de 15 minutos del horario local.")
            return
        # Conserva la fecha de encendido de instalaciones anteriores.
        state_key = "date" if action == "on" else "off_date"
    last_error = None
    for attempt in range(MAX_SCHEDULED_ATTEMPTS if scheduled else 1):
        now = datetime.now().astimezone()
        if scheduled:
            if schedule_date(now, config, action) != date:
                if last_error is not None:
                    raise RuntimeError(
                        f"La ventana horaria terminó sin confirmar la acción {action}."
                    ) from last_error
                log("Horario omitido: fuera de la ventana de 15 minutos del horario local.")
                return
            last = json.loads(state_path.read_text()) if state_path.exists() else {}
            if last.get(state_key) == date:
                log(f"Acción diaria {action} ya confirmada; no se repite.")
                return
        try:
            result = await asyncio.wait_for(
                control(address, turn_on=None if action is None else action == "on",
                        config=config if scheduled else None),
                timeout=50,
            )
            log(json.dumps(result))
            if scheduled:
                temporary = state_path.with_suffix(".tmp")
                last[state_key] = date
                temporary.write_text(json.dumps(last))
                temporary.replace(state_path)
            return
        except Exception as error:
            log(f"Intento {attempt + 1}: {type(error).__name__}: {error}")
            if not scheduled or attempt == MAX_SCHEDULED_ATTEMPTS - 1:
                raise
            last_error = error
            # Las fallas de Bluetooth suelen ser transitorias: se espera cada vez más.
            await asyncio.sleep(min(10 * (attempt + 1), 30))


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
