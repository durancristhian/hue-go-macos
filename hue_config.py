"""Configuración compartida entre el programa y el instalador, sin Bluetooth."""
import json
import re
from datetime import timedelta
from pathlib import Path

WINDOW_MINUTES = 15


def validate(config):
    if not isinstance(config, dict):
        raise ValueError("La configuración debe ser un objeto JSON.")
    address = config.get("address", "")
    if not isinstance(address, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", address
    ) or not address.replace("-", "").strip("0"):
        raise ValueError("Completá address con el UUID obtenido al escanear desde esta Mac.")
    result = dict(config)
    for key, default, maximum in [("hour", 19, 23), ("minute", 0, 59),
                                  ("off_hour", 1, 23), ("off_minute", 0, 59)]:
        value = config.get(key, default)
        if type(value) is not int or not 0 <= value <= maximum:
            raise ValueError(f"{key} debe ser un entero entre 0 y {maximum}.")
        result[key] = value
    unknown = config.keys() - {"address", "hour", "minute", "off_hour", "off_minute"}
    if unknown:
        raise ValueError("Campos desconocidos: " + ", ".join(sorted(unknown)))
    distance = (result["off_hour"] * 60 + result["off_minute"]
                - result["hour"] * 60 - result["minute"]) % (24 * 60)
    if min(distance, 24 * 60 - distance) < WINDOW_MINUTES:
        raise ValueError("Los horarios de encendido y apagado deben separarse al menos 15 minutos.")
    return result


def load_config(path):
    return validate(json.loads(Path(path).read_text()))


def schedule_date(now, config, action="on"):
    """Fecha del horario dentro de su ventana, usando el reloj local de macOS."""
    wall = now.replace(tzinfo=None)
    prefix = "off_" if action == "off" else ""
    start = wall.replace(hour=config[prefix + "hour"], minute=config[prefix + "minute"],
                         second=0, microsecond=0)
    if wall < start:
        start -= timedelta(days=1)
    if timedelta(0) <= wall - start < timedelta(minutes=WINDOW_MINUTES):
        return start.date().isoformat()
    return None
