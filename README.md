# ESP32-S3 Super Mini e-paper

Sistema de bajo consumo para actualizar una pantalla e-ink Pervasive Displays
2.66" (296x152, blanco/negro/rojo) una vez al dia.

El proyecto tiene dos componentes:

- Firmware PlatformIO para ESP32-S3.
- Bot de Telegram en Python que recorta, convierte y publica la imagen.

Lee primero [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) para conocer las decisiones
del proyecto y [AGENT_CONTEXT.md](AGENT_CONTEXT.md) antes de modificar codigo.

## Flujo

1. El usuario envia una foto al bot.
2. El bot corrige EXIF, recorta sin deformar y genera una previsualizacion.
3. El usuario ajusta estilo, recorte, brillo, contraste, trama, nitidez y rojo.
   Puede usar botones o introducir los cinco valores en una sola respuesta.
4. `Publicar` crea `current.epd` y lo guarda mediante GitHub Contents API.
5. El ESP despierta, conecta al WiFi durante un maximo de 10 segundos y consulta
   el archivo.
6. Si la imagen es nueva y valida, apaga WiFi, actualiza la e-ink y duerme hasta
   la proxima medianoche chilena.

## Firmware

1. Copia `include/secrets.example.h` como `include/secrets.h`.
2. Configura WiFi y la URL publica de `current.epd`.
3. Revisa el mapa provisional de pines en `include/project_config.h`.
4. Compila y sube:

```powershell
pio run
pio run --target upload
pio device monitor
```

Para probar solo la ruta servidor -> e-paper, sin deep sleep ni optimizaciones:

```powershell
pio run -e epaper-server-test
pio run -e epaper-server-test --target upload
pio device monitor -e epaper-server-test
```

Ese firmware de prueba descarga `current.epd`, valida `EPD1` y refresca la
pantalla una sola vez en un ESP32-WROOM-32. Usa el cableado MOSI=GPIO23,
SCK=GPIO18, BUSY=GPIO27, DC=GPIO26, RST=GPIO25 y CS=GPIO32.

La configuracion usa `esp32-s3-devkitc-1` como base para la Super Mini y fija
`PDLS_EXT3_Basic_Global` en la version 8.2.0.

## Bot

Instala dependencias:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r bot\requirements-dev.txt
pytest bot\tests
```

Variables necesarias:

| Variable | Uso |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token entregado por BotFather |
| `TELEGRAM_WEBHOOK_URL` | Opcional fuera de Render; Render aporta `RENDER_EXTERNAL_URL` |
| `TELEGRAM_WEBHOOK_SECRET` | Secreto aleatorio; el bot lo normaliza para Telegram |
| `ALLOWED_USER_IDS` | IDs numericos separados por coma |
| `GITHUB_TOKEN` | Token con permiso Contents: Read and write |
| `GITHUB_REPOSITORY` | Repositorio `owner/name` |
| `GITHUB_PATH` | Ruta: `docs/display/22a7a15a92a99aae4446f9d62b5f57dd/current.epd` |
| `GITHUB_BRANCH` | Rama, por defecto `main` |
| `PUBLIC_IMAGE_URL` | URL final de GitHub Pages, opcional |

Para desarrollo local se puede omitir `TELEGRAM_WEBHOOK_URL`; el bot usara
long polling. En Render se puede crear el servicio desde `render.yaml`.

Configura GitHub Pages para publicar desde la carpeta `/docs` de la rama
seleccionada. La imagen e-ink sera publica para quien conozca la URL.

Repositorio:
https://github.com/xXROCHETXx/ESPSUPERMINI

GitHub Pages:
https://xxrochetxx.github.io/ESPSUPERMINI/

Archivo que publicara el bot:
https://xxrochetxx.github.io/ESPSUPERMINI/display/22a7a15a92a99aae4446f9d62b5f57dd/current.epd

## Formato EPD1

`current.epd` usa una cabecera little-endian de 24 bytes:

| Offset | Tipo | Campo |
|---:|---|---|
| 0 | 4 bytes | Magic `EPD1` |
| 4 | `uint8` | Version, actualmente 1 |
| 5 | `uint8` | Modo: 1 BW, 2 BWR |
| 6 | `uint8` | Tamano de cabecera, 24 |
| 7 | `uint8` | Flags, actualmente 0 |
| 8 | `uint16` | Ancho, 296 |
| 10 | `uint16` | Alto, 152 |
| 12 | `uint16` | Bytes por fila, 37 |
| 14 | `uint16` | Longitud del payload |
| 16 | `uint32` | Unix timestamp de publicacion |
| 20 | `uint32` | CRC32 del payload |

Cada plano ocupa 5.624 bytes. Las filas usan MSB primero y un bit `0` activa
el color. BW contiene solo negro; BWR contiene primero negro y despues rojo.

## Seguridad de energia

- Timeout WiFi: 10 segundos.
- Timeout de descarga: 15 segundos.
- `flush()` no se interrumpe si ya comenzo.
- Watchdog de pantalla: 120 segundos.
- Un reinicio por watchdog provoca deep sleep inmediato durante 24 horas para
  evitar un bucle de reinicios.
- El estado aplicado se guarda solo despues de que `flush()` retorna.

Las corrientes y los pines siguen siendo estimaciones hasta realizar pruebas
con la placa conectada.
