#!/bin/sh
# Compila solamente. Nunca instala, abre la app ni carga un LaunchAgent.
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
app_dir=${1:-"$source_dir/build/Hue Horario.app"}
if [ -e "$app_dir" ]; then
    printf '%s\n' "El destino ya existe; elegí una ruta nueva: $app_dir" >&2
    exit 1
fi
mkdir -p "$app_dir/Contents/MacOS"
cp "$source_dir/Info.plist" "$app_dir/Contents/Info.plist"
xcrun swiftc "$source_dir/Launcher.swift" -framework AppKit -o "$app_dir/Contents/MacOS/HueHorario"
codesign --sign - --identifier local.hue-horario.app "$app_dir"
codesign --verify --strict "$app_dir"
printf '%s\n' "App compilada y firmada localmente: $app_dir"
