#!/usr/bin/env python3
"""Instalar Hue Horario y administrar su LaunchAgent sin acceder a Bluetooth."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

from hue_config import load_config

LABEL = "local.hue-horario"
SOURCE = Path(__file__).resolve().parent


def locations(root):
    return (root / "Applications/Hue Horario.app",
            root / "Library/Application Support/HueHorario",
            root / f"Library/LaunchAgents/{LABEL}.plist")


def domain():
    return f"gui/{os.getuid()}"


def loaded():
    return subprocess.run(["launchctl", "print", f"{domain()}/{LABEL}"],
                          capture_output=True).returncode == 0


def check_owned(path, app):
    if path.exists():
        data = plistlib.loads(path.read_bytes())
        if data.get("Label") != LABEL or data.get("ProgramArguments") != arguments(app):
            raise ValueError(f"El plist existente no pertenece a esta instalación: {path}")


def arguments(app):
    return ["/usr/bin/open", "-n", "-g", "-W", str(app), "--args", "scheduled"]


def prepare(root, replace=False):
    if not (3, 9) <= sys.version_info[:2] < (3, 13):
        raise ValueError("Usá Python 3.9 a 3.12 para estas dependencias fijadas.")
    app, runtime, agent = locations(root)
    if root == Path.home().resolve() and loaded():
        raise ValueError("El horario está cargado. Desactivalo antes de reinstalar.")
    if (app.exists() or runtime.exists() or agent.exists()) and not replace:
        raise ValueError("Ya existe una instalación. No se modificó. Revisala y usá --replace explícitamente.")
    check_owned(agent, app)
    if (runtime / "config.json").exists():
        # Se conserva incluso si todavía es el ejemplo; no se activa aquí.
        json.loads((runtime / "config.json").read_text())
    with tempfile.TemporaryDirectory(prefix="hue-build-") as temporary:
        built = Path(temporary) / "Hue Horario.app"
        subprocess.run(["sh", str(SOURCE / "build.sh"), str(built)], check=True)
        info = built / "Contents/Info.plist"
        data = plistlib.loads(info.read_bytes())
        data["HueRuntimeDirectory"] = str(runtime)
        info.write_bytes(plistlib.dumps(data))
        subprocess.run(["codesign", "--force", "--sign", "-", str(built)], check=True)
        subprocess.run(["codesign", "--verify", "--strict", str(built)], check=True)
        runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        python = runtime / ".venv/bin/python"
        if not python.exists():
            subprocess.run([sys.executable, "-m", "venv", str(runtime / ".venv")], check=True)
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(SOURCE / "requirements.txt")], check=True)
        subprocess.run([str(python), "-m", "pip", "check"], check=True)
        for name in ["hue.py", "hue_config.py", "manage.py", "requirements.txt", "config.example.json"]:
            target = runtime / name
            if (SOURCE / name).resolve() != target.resolve():
                shutil.copy2(SOURCE / name, target)
        config = runtime / "config.json"
        if not config.exists():
            shutil.copy2(SOURCE / "config.example.json", config)
            config.chmod(0o600)
        app.parent.mkdir(parents=True, exist_ok=True)
        if app.exists():
            # --replace ya fue verificado y el agente no está cargado.
            shutil.rmtree(app)
        shutil.copytree(built, app)
    print(f"Instalación preparada en {runtime}\nApp: {app}\nNo se abrió la app ni se activó el horario.")


def generate(root):
    app, runtime, _ = locations(root)
    config = load_config(runtime / "config.json")
    if not (app / "Contents/MacOS/HueHorario").is_file() or not (runtime / ".venv/bin/python").is_file():
        raise ValueError("Primero prepará la instalación.")
    payload = {
        "Label": LABEL,
        "ProgramArguments": arguments(app),
        "StartCalendarInterval": {"Hour": config["hour"], "Minute": config["minute"]},
        "StandardOutPath": str(runtime / "launchd.log"),
        "StandardErrorPath": str(runtime / "launchd-error.log"),
        "ProcessType": "Background",
        "LimitLoadToSessionType": "Aqua",
    }
    target = runtime / f"{LABEL}.plist"
    target.write_bytes(plistlib.dumps(payload))
    target.chmod(0o600)
    print(f"Plist preparado: {target}\nHorario local: {config['hour']:02d}:{config['minute']:02d}")
    return target


def enable(root):
    app, _, agent = locations(root)
    if loaded():
        raise ValueError("Ya está cargado. Desactivá el horario antes de cambiarlo o volver a activarlo.")
    check_owned(agent, app)
    prepared = generate(root)  # Validación obligatoria antes de modificar launchd.
    agent.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(prepared, agent)
    subprocess.run(["launchctl", "enable", f"{domain()}/{LABEL}"], check=True)
    subprocess.run(["launchctl", "bootstrap", domain(), str(agent)], check=True)
    print("Horario activado. No se solicitó un encendido inmediato.")


def disable(root):
    app, _, agent = locations(root)
    check_owned(agent, app)
    subprocess.run(["launchctl", "disable", f"{domain()}/{LABEL}"], check=True)
    if loaded():
        subprocess.run(["launchctl", "bootout", f"{domain()}/{LABEL}"], check=True)
    print("Horario desactivado. Se conservaron la app, configuración, estado y plist.")


def status(root):
    _, runtime, agent = locations(root)
    config = load_config(runtime / "config.json")
    print(f"Configuración: {config['hour']:02d}:{config['minute']:02d}, hora local de macOS", flush=True)
    if agent.exists():
        data = plistlib.loads(agent.read_bytes())
        print("Horario del plist instalado:", data.get("StartCalendarInterval"), flush=True)
    subprocess.run(["launchctl", "print", f"{domain()}/{LABEL}"], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "generate", "enable", "disable", "status"])
    parser.add_argument("--root", type=Path, default=Path.home(), help="Raíz alternativa para preparar/verificar sin activar")
    parser.add_argument("--replace", action="store_true", help="Reinstalar explícitamente, conservando configuración y estado")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    if args.replace and args.command != "prepare":
        parser.error("--replace solo se aplica a prepare")
    if root != Path.home().resolve() and args.command not in ("prepare", "generate"):
        parser.error("La raíz alternativa solo permite prepare/generate; nunca activa un agente")
    if sys.platform != "darwin":
        parser.error("Este proyecto requiere macOS")
    if args.command == "prepare":
        prepare(root, args.replace)
    else:
        {"generate": generate, "enable": enable, "disable": disable, "status": status}[args.command](root)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
