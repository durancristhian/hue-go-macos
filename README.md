# Hue Go en macOS por Bluetooth

Enciende una Philips Hue Go **LCT026** cada día a las **19:00**, sin Hue Bridge. Envía únicamente la orden de encendido, conserva el color y brillo configurados en la lámpara y comprueba el estado después de escribirlo. No incluye apagado automático, servicios remotos ni telemetría.

Python y [Bleak](https://github.com/hbldh/bleak) realizan la comunicación Bluetooth. Una app pequeña en Swift, **Hue Horario**, da al proceso una identidad propia para el permiso de macOS. Un LaunchAgent abre esa app en el horario elegido.

## Requisitos

- Una Philips Hue Go LCT026 con alimentación y al alcance de Bluetooth. Es el único modelo probado; el programa rechaza otros modelos antes de escribir.
- Una Mac con Bluetooth activo y una sesión gráfica iniciada. La preparación se verificó en macOS 26.6 sobre Apple Silicon. No se comprobó la instalación en otros sistemas, versiones de macOS ni Macs Intel.
- Command Line Tools de Xcode, con `xcrun`, `swiftc`, `codesign` y Git. Si faltan, ejecutar `xcode-select --install` y completar el instalador de Apple.
- Python 3.9 a 3.12 con `venv` y `pip`. Se verificó Python 3.9.6. El instalador rechaza otras versiones porque las dependencias están fijadas para este rango.
- Internet durante la instalación de dependencias. El control posterior es local.
- La app Hue del celular para poner la lámpara en modo descubrible cuando sea necesario.

## Instalar desde un clon limpio

Comprobar las herramientas:

```sh
python3 --version
xcrun swiftc --version
```

Clonar y preparar:

```sh
git clone https://github.com/durancristhian/hue-go-macos.git
cd hue-go-macos
python3 manage.py prepare
```

No usar `sudo`. Si `python3` no está entre 3.9 y 3.12, ejecutar `manage.py` con un intérprete de ese rango.

La preparación compila y firma la app con una firma local ad hoc, crea el entorno Python, instala las dependencias fijadas y copia el ejemplo como configuración privada. No abre la app, accede a Bluetooth ni activa el horario.

Archivos instalados:

| Ruta | Contenido |
| --- | --- |
| `~/Applications/Hue Horario.app` | Launcher firmado localmente |
| `~/Library/Application Support/HueHorario/` | Python, `.venv`, configuración, administrador, estado y logs |
| `~/Library/LaunchAgents/local.hue-horario.plist` | Se crea al activar el horario |

La app usa rutas absolutas generadas para esa instalación. Después se puede mover o eliminar el clon. Hay que conservar la app, el directorio de ejecución y el Python base con el que se creó el entorno virtual. No trasladar la instalación preparada a otra cuenta o Mac: instalarla allí desde el código fuente.

Para compilar solamente, sin instalar:

```sh
sh build.sh
```

El resultado queda en `build/Hue Horario.app`. También se puede pasar una ruta de salida nueva como primer argumento. El build rechaza destinos existentes.

## Descubrir, configurar y emparejar

Definir estas variables en la terminal. Los comandos siguientes usan siempre la instalación estable:

```sh
runtime="$HOME/Library/Application Support/HueHorario"
app="$HOME/Applications/Hue Horario.app"
```

Abrir la app para escanear. Esto solicita el permiso Bluetooth mediante el aviso normal de macOS:

```sh
open -n -W "$app" --args scan
tail -n 80 "$runtime/app.log"
cat "$runtime/app-result.json"
```

Aceptar el permiso de **Hue Horario**. La búsqueda dura unos 15 segundos y muestra nombre, `address` y RSSI de las luces anunciadas. El identificador `address` de CoreBluetooth debe obtenerse **desde la Mac donde se instalará**. No es una dirección MAC y no debe copiarse de otra computadora. Véase la [documentación de Bleak para macOS](https://bleak.readthedocs.io/en/stable/backends/macos.html).

Si la luz no aparece o no permite conectar, ponerla en modo descubrible desde Hue en el celular. [HueBLE documenta](https://hueble.readthedocs.io/en/latest/usage.html#pairing) el recorrido Settings → Voice assistants → Amazon Alexa → Make discoverable. Los nombres pueden variar según la versión de la app. Este procedimiento no requiere restablecer la lámpara.

Editar la copia local creada por el instalador:

```sh
open -e "$runtime/config.json"
```

Su estructura es:

```json
{
  "address": "REPLACE_WITH_BLUETOOTH_DEVICE_UUID",
  "hour": 19,
  "minute": 0
}
```

Reemplazar únicamente el marcador de `address` por el UUID encontrado. `hour` y `minute` son enteros en formato de 24 horas. Si se omiten, se usan 19 y 0. No se aceptan campos desconocidos. El ejemplo, una dirección vacía o un horario inválido impiden activar el agente. La validación sintáctica del UUID no demuestra que la luz esté disponible; confirmar la lectura antes de activar.

Consultar el estado sin encender:

```sh
open -n -W "$app" --args status
tail -n 30 "$runtime/app.log"
cat "$runtime/app-result.json"
```

macOS puede pedir emparejamiento al leer una característica protegida. Aceptar el aviso. Si el tiempo de espera termina mientras se responde, repetir `status`. CoreBluetooth gestiona ese emparejamiento; no se llama a un método de emparejamiento explícito.

El permiso otorgado a una terminal o editor no basta para Python lanzado directamente por `launchd`. Por eso el agente abre la app `local.hue-horario.app`, cuyo `Info.plist` contiene la descripción de uso de Bluetooth. Si se denegó el permiso, habilitar **Hue Horario** en Ajustes del Sistema → Privacidad y seguridad → Bluetooth. No hace falta cambiar permisos de otras apps.

## Prueba manual y horario

Cuando se quiera hacer una prueba física, este comando **enciende la lámpara inmediatamente**, sin aplicar la ventana horaria:

```sh
open -n -W "$app" --args on
tail -n 30 "$runtime/app.log"
cat "$runtime/app-result.json"
```

El resultado esperado contiene `power: "01"`. El código de salida de `open` solo indica que pudo abrir o esperar a la app. Confirmar en `app-result.json` que `command` corresponde a la operación, `finishedAt` es reciente y `exitCode` vale `0`; revisar también el log. Un resultado viejo no confirma la operación actual. Si hay otra operación en curso, el programa registra que no la repite.

Generar el plist sin cargarlo, para revisar las rutas y el horario:

```sh
"$runtime/.venv/bin/python" "$runtime/manage.py" generate
plutil -p "$runtime/local.hue-horario.plist"
```

Activar y consultar:

```sh
"$runtime/.venv/bin/python" "$runtime/manage.py" enable
"$runtime/.venv/bin/python" "$runtime/manage.py" status
```

`enable` valida la configuración, genera el plist, lo instala y carga con `launchctl`. No usa `RunAtLoad` ni solicita un encendido inmediato. Si el agente ya está cargado, exige desactivarlo antes. Activarlo después del horario no garantiza recuperar la ejecución de ese día.

Desactivar, conservando los archivos y el estado diario:

```sh
"$runtime/.venv/bin/python" "$runtime/manage.py" disable
```

Para revisar directamente el agente:

```sh
launchctl print "gui/$(id -u)/local.hue-horario"
```

El comando falla si no está cargado. Que un agente esté cargado no confirma una conexión Bluetooth ni un encendido.

## Hora local, suspensión y duplicados

El LaunchAgent y Python usan **el reloj y la zona horaria del sistema macOS**. No hay una zona fija de Buenos Aires. A las 19:00 locales comienza una ventana de 15 minutos; desde las 19:15 se omite el encendido. La ventana se vuelve a comprobar antes de escribir la orden, además de al iniciar cada intento.

Para cambiar el horario, desactivar el agente, editar `hour` y `minute` en `config.json`, volver a ejecutar `enable` y consultar `status`. No editar solo el plist: Python valida contra la configuración. Si cambia la zona horaria del sistema, desactivar y reactivar para que ambos usen el nuevo horario local. `status` muestra el horario configurado y el del plist instalado.

- La Mac apagada o con la sesión cerrada no ejecuta este LaunchAgent de usuario. No se garantiza recuperar el encendido al iniciar sesión.
- Si está suspendida a la hora prevista, `launchd` puede ejecutar el evento pendiente al despertar. Solo se permite encender dentro de la ventana; más tarde se omite. Varios eventos pendientes se agrupan en uno. Es el comportamiento de `StartCalendarInterval` descrito en `man launchd.plist`.
- No se programa un despertar, no se evita la suspensión y no se cambian ajustes de energía. Cerrar la tapa puede impedir el encendido puntual.
- Hay hasta tres intentos programados, con un límite de 50 segundos por intento y 10 segundos entre fallos. Las operaciones manuales tienen un solo intento. Los avisos de permiso o emparejamiento pueden agotar ese tiempo.
- Un encendido programado confirmado guarda su fecha en `last-success.json`. Otra ejecución para esa fecha se omite, incluso si la luz se apagó después. Un bloqueo evita operaciones de control simultáneas. Los comandos manuales `on` no registran el éxito diario.
- En un horario cercano a medianoche, la fecha guardada corresponde al comienzo de la ventana. Los cambios manuales del reloj pueden cambiar esa referencia. No es un sistema de entrega garantizada: si el proceso se interrumpe después de escribir y antes de guardar el éxito, un reintento puede repetir la orden de encendido.

## Diagnóstico

Todos estos archivos son privados y quedan en el directorio de ejecución:

| Archivo | Uso |
| --- | --- |
| `config.json` | Dirección de la luz y horario |
| `app.log` | Escaneo, estado, omisiones y fallos del programa |
| `app-result.json` | Último comando terminado y su código de salida |
| `launcher-error.log` | Fallos al iniciar Python desde Swift |
| `launchd.log`, `launchd-error.log` | Salida del agente y errores de apertura |
| `last-success.json`, `last-success.lock` | Prevención de duplicados y bloqueo |

Si no aparece un resultado reciente, revisar `launcher-error.log` y comprobar que `.venv/bin/python` sigue existiendo. Un archivo de error antiguo puede permanecer después de resolver el problema: revisar las fechas.

Ante errores de autorización, revisar el permiso de la app y repetir `status` en primer plano. Ante fallos de conexión, verificar alimentación, Bluetooth, UUID obtenido en esta Mac y modo descubrible. Cerrar la app Hue del celular si está manteniendo la conexión y reintentar cerca de la luz.

El RSSI del escaneo ayuda a comparar ubicaciones: valores más negativos suelen indicar señal más débil. Acercar la Mac y reducir obstáculos; no hay un umbral que garantice conexión. No publicar logs sin revisarlos porque pueden incluir nombres e identificadores Bluetooth. Los logs se anexan y no tienen rotación automática.

## Reinstalación

`prepare` rechaza una instalación existente por defecto. Para actualizarla desde un clon, esperar a que termine cualquier operación manual, ejecutar `disable` y después:

```sh
python3 manage.py prepare --replace
```

Esto reemplaza explícitamente el código y la app, y conserva `config.json` y el estado diario. Rechaza un agente cargado y un plist que no corresponda a esta instalación. No vuelve a activar el horario. Revisar `status` de la lámpara y los permisos antes de ejecutar `enable`; una nueva firma local puede requerir autorización de nuevo. No distribuir la app ad hoc como si estuviera notarizada por Apple.

## Verificación sin tocar una lámpara

Las pruebas usan Bluetooth y `launchctl` simulados:

```sh
python3 -m unittest discover -s tests -v
sh -n build.sh
plutil -lint Info.plist
```

Para comprobar compilación e instalación en una carpeta temporal, sin cambiar `HOME`:

```sh
sandbox=$(mktemp -d "${TMPDIR:-/tmp}/hue-check.XXXXXX")
python3 manage.py prepare --root "$sandbox/installation with spaces"
```

`--root` solo permite preparar y generar archivos. Rechaza activar, desactivar o consultar agentes reales. No abrir la app de prueba: comparte el identificador con la app instalada. `generate` rechazará la configuración de ejemplo; las pruebas automatizadas usan UUID sintéticos creados durante su ejecución.

Se verificaron la sintaxis, los plists, compilación y firma local, instalación aislada con espacios, dependencias, preservación de configuración al reinstalar y protecciones de horario con dobles de prueba. También se revisaron las exclusiones y el contenido publicable.

La implementación de origen tuvo un encendido real y una lectura en segundo plano verificados con una LCT026. **Esta preparación del repositorio no repitió pruebas físicas**, no pidió permisos ni cargó un agente de prueba. Siguen pendientes una instalación con permisos desde cero en otra Mac y la observación del disparo automático del reloj con esta versión. Compilar no demuestra esas condiciones.

## Referencias y licencias

- El perfil GATT se basa en la referencia de [hue-ble-mcp](https://github.com/jonnyblankinship/hue-ble-mcp/blob/main/hue_ble_mcp/server.py), de Jonny Blankinship. Su aviso MIT se conserva en [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- [Bleak](https://github.com/hbldh/bleak) y [PyObjC](https://github.com/ronaldoussoren/pyobjc) se instalan como dependencias y conservan sus licencias. HueBLE se cita como documentación de emparejamiento, no se incluye como dependencia.
- Código del proyecto bajo [licencia MIT](LICENSE). Proyecto independiente, sin afiliación con Philips Hue o Signify.
