# Memoria tecnica para agentes

Leer `PROJECT_CONTEXT.md` y este archivo antes de modificar el proyecto.

## Invariantes

- El objetivo principal es evitar consumo indefinido.
- Toda ruta del firmware debe terminar en deep sleep.
- WiFi tiene timeout absoluto de 10 segundos.
- La descarga tiene timeout de 15 segundos y tamano maximo de 11.272 bytes.
- Nunca inicializar ni refrescar la e-ink con datos no validados.
- Apagar WiFi antes de preparar/refrescar la pantalla.
- No interrumpir un `flush()` normal.
- Un watchdog que reinicie el ESP debe provocar sueño inmediato en el arranque
  siguiente para impedir reset loops.
- Guardar CRC/ETag aplicado solo despues de un refresco retornado con exito.
- En contenido identico se puede guardar un ETag nuevo porque el payload ya fue
  validado y coincide con el CRC aplicado.

## Contrato binario

- Magic: `EPD1`.
- Version: 1.
- Cabecera: 24 bytes little-endian.
- Resolucion unica: 296x152.
- Stride: 37 bytes.
- Plano: 5.624 bytes.
- Modo 1 BW: un plano.
- Modo 2 BWR: negro seguido de rojo.
- Bit 0 activa color, MSB primero.
- CRC32 compatible con `zlib.crc32`.
- No puede existir un bit activo en ambos planos.

El contrato esta implementado de forma independiente en:

- `bot/epd_format.py`.
- `include/epd_format.h` y `src/epd_format.cpp`.

Mantener ambos sincronizados y ampliar las pruebas si cambia.

## Hardware provisional

- ESP32-S3 Super Mini representada por `esp32-s3-devkitc-1`.
- SPI del variant: MOSI 11, SCK 12, MISO 13.
- Control: BUSY 4, DC 5, RESET 6, FLASH_CS 7, PANEL_CS 8.
- Pantalla: `eScreen_EPD_266_JS_0C`.
- Libreria: `PDLS_EXT3_Basic_Global` 8.2.0.
- No usar `boardESP32DevKitC`.

La orientacion del framebuffer es landscape 296x152. Debe verificarse
fisicamente y no corregirse en el bot hasta observar el panel real.

## Tiempo

- No usar NTP en el ciclo normal.
- Obtener UTC desde la cabecera HTTP `Date`.
- Regla POSIX: `CLT4CLST,M9.1.6/24,M4.1.6/24`.
- Si la fecha falta o falla, dormir 24 horas.
- Si quedan menos de 15 minutos para medianoche, saltar a la siguiente.

## Red y seguridad

- `current.epd` se sirve desde GitHub Pages en
  `docs/display/22a7a15a92a99aae4446f9d62b5f57dd/current.epd`.
- El firmware usa TLS sin validar CA porque en el primer arranque aun no conoce
  la hora. CRC protege integridad accidental, no autenticidad.
- La ruta publica debe ser dificil de adivinar.
- Mejora futura posible: firma/HMAC del archivo si el riesgo lo justifica.
- ETag es una optimizacion, no una fuente de verdad.

## Bot

- No introducir base de datos salvo que cambien los requisitos.
- El mensaje de preview responde al mensaje que contiene la foto original.
- El estado cabe en callback_data y debe seguir bajo el limite Telegram de
  64 bytes.
- Un callback tras cold start vuelve a descargar la foto original desde
  Telegram.
- Usuarios permitidos vienen de `ALLOWED_USER_IDS`.
- El original nunca se sube a GitHub.
- No agregar OpenCV/NumPy/Tkinter sin una necesidad demostrada.

## Repositorios y commits revisados

- Firmware Lory:
  `012ce3552bb09f52ae31cfc374f6b2f8a26635fc`.
- Desktop app Lory:
  `a2daba60ada6d69b2673707594f4eb91b170beab`.
- PDLS_EXT3 8.2.0:
  `ca37a598a80e6d77ffb978bdcd2142d808b1269b`.

La app de escritorio no es una referencia de formato BWR: produce 2 bits por
pixel, mientras el firmware asociado recibe 1 bit por pixel.

## Riesgos conocidos

- GPIO y orientacion aun no probados.
- `PDLS_EXT3` espera indefinidamente en BUSY; el watchdog es la proteccion.
- GitHub Pages puede entregar temporalmente la version anterior tras publicar.
  Esto es aceptable.
- Render y GitHub pueden cambiar sus planes gratuitos.
- TLS sin CA permite un atacante de red activo; CRC no evita manipulacion.
- El panel BWR probablemente usa tiempos de refresco similares incluso en BW;
  BW ahorra descarga y RAM, no necesariamente energia del panel.

## Proxima sesion recomendada

1. Instalar Python 3.12 y PlatformIO.
2. Ejecutar `pytest bot/tests`.
3. Ejecutar `pio test -e native`.
4. Ejecutar `pio run`.
5. Corregir cualquier incompatibilidad de toolchain.
6. Configurar bot, Pages y secretos.
7. Probar con hardware y actualizar esta memoria con medidas reales.
