# Contexto completo del proyecto ESP32-S3 e-paper

## Objetivo original

Construir un dispositivo con ESP32-S3 Super Mini, bateria LiPo de 400 mAh y
pantalla e-ink que:

- Permanezca en deep sleep casi todo el dia.
- Despierte una vez al dia, idealmente a las 00:00 de Chile.
- Busque una imagen nueva mediante WiFi.
- No modifique la pantalla si no hay cambios o los datos son inconsistentes.
- Actualice la pantalla y vuelva a dormir.
- Priorice autonomia y evite cualquier bucle que deje la radio o la CPU activas.

Estimaciones iniciales conversadas:

- Deep sleep objetivo: aproximadamente 20 uA.
- WiFi activo: aproximadamente 80-300 mA, con picos mayores.
- Conexion WiFi limitada a 10 segundos.
- Descarga y preparacion limitadas a 15 segundos.
- Un `flush()` ya iniciado se deja terminar para no cortar la transferencia SPI.
- Autonomia esperada: teoricamente cientos de dias, pero debe medirse con el
  hardware real.

Las advertencias sobre antena pequena, LED RGB, power LED, regulador, cargador
y consumo real se documentan, pero se depuraran mas adelante con la placa.

## Hardware y pantalla

- Placa: ESP32-S3 Super Mini.
- Pantalla elegida: Pervasive Displays 2.66", 296x152.
- Identificador PDLS: `eScreen_EPD_266_JS_0C`.
- La pelicula `J` admite blanco, negro y rojo.
- Libreria: `PDLS_EXT3_Basic_Global` 8.2.0.
- El mapa de GPIO es provisional.
- SPI predeterminado del variant ESP32-S3:
  - MOSI GPIO11.
  - SCK GPIO12.
  - MISO GPIO13.
- Control provisional:
  - BUSY GPIO4.
  - DC GPIO5.
  - RESET GPIO6.
  - FLASH_CS GPIO7.
  - PANEL_CS GPIO8.

No debe reutilizarse `boardESP32DevKitC`: usa GPIO que no corresponden a la
Super Mini. El proyecto define un `pins_t` propio.

## Ciclo diario acordado

1. Arrancar y revisar la causa del reinicio.
2. Si el ciclo anterior termino por watchdog, dormir inmediatamente 24 horas.
3. Conectar al WiFi durante un maximo de 10 segundos.
4. Consultar condicionalmente `current.epd` mediante ETag.
5. Leer la cabecera HTTP `Date`; no realizar una peticion NTP adicional.
6. Si HTTP responde 304, apagar WiFi y dormir.
7. Si responde 200, descargar como maximo 11.272 bytes en 15 segundos.
8. Validar magic, version, dimensiones, modo, longitud, CRC32 y planos.
9. Si el CRC ya fue aplicado, guardar el ETag verificado y dormir.
10. Apagar completamente WiFi antes de inicializar la pantalla.
11. Dibujar el framebuffer y ejecutar `flush()`.
12. Guardar CRC y ETag solamente despues de que `flush()` termine.
13. Calcular el sueño hasta la siguiente medianoche de Chile.
14. Si no se obtuvo una hora valida, dormir 24 horas.

Si faltan menos de 15 minutos para la siguiente medianoche, se omite ese
despertar cercano y se programa el dia siguiente para evitar dos ciclos casi
consecutivos.

La zona horaria se representa con la regla POSIX continental chilena:
`CLT4CLST,M9.1.6/24,M4.1.6/24`.

## Publicacion y bot de Telegram

Se eligio Telegram porque ya existe experiencia previa del usuario controlando
un ESP mediante comandos `/wake` y `/status`.

Arquitectura:

- Bot Python en Render Free.
- Pillow para conversion.
- `python-telegram-bot` para webhook y botones.
- GitHub Contents API para sobrescribir
  `docs/display/22a7a15a92a99aae4446f9d62b5f57dd/current.epd`.
- GitHub Pages para servir el archivo sin depender del cold start de Render.
- Sin base de datos.
- Solo Telegram user IDs autorizados pueden preparar o publicar imagenes.
- En Render, el webhook usa automaticamente la variable nativa
  `RENDER_EXTERNAL_URL`; no hay que adivinar la URL durante el primer deploy.
- El secreto generado por Render se normaliza con SHA-256 porque Telegram solo
  admite letras, numeros, guion y guion bajo en el token del webhook.
- Las previsualizaciones editadas usan adjuntos multipart `attach://`; no se
  debe construir un `InputFile` sin `attach=True` dentro de `InputMediaPhoto`.

Recursos creados:

- Repositorio: `https://github.com/xXROCHETXx/ESPSUPERMINI`.
- Pages: `https://xxrochetxx.github.io/ESPSUPERMINI/`.
- Bitmap:
  `https://xxrochetxx.github.io/ESPSUPERMINI/display/22a7a15a92a99aae4446f9d62b5f57dd/current.epd`.
- Telegram user ID autorizado: `1815804105`.

Render puede suspender el bot, pero esto no afecta al ESP: la conversion se hace
al pulsar `Publicar`, normalmente horas antes del ciclo diario. El ESP descarga
el archivo estatico de GitHub Pages y nunca despierta al bot.

La imagen e-ink puede ser publica para quien conozca la URL. Se recomienda una
ruta dificil de adivinar y no indexada. Solo se publica la version 296x152, no
la fotografia original.

## Experiencia de edicion

Flujo principal:

1. Enviar foto o documento de imagen.
2. Corregir orientacion EXIF.
3. Recortar al aspect ratio 296:152 sin deformar.
4. Mostrar una simulacion ampliada 4x con nearest-neighbour.
5. Ajustar mediante botones.
6. Publicar.

Menu principal:

- `Publicar`.
- `Cambiar estilo`.
- `Ajustar recorte`.
- `Luz y color`.
- `Cancelar`.

Recorte:

- Arriba, abajo, izquierda y derecha.
- Acercar y alejar.
- Restablecer recorte.

Presets:

- Foto BWR: blanco, negro y rojo con dithering.
- Foto B/N: omite por completo el plano rojo.
- Texto/Logo: contraste alto, bordes definidos y umbral fijo.

Ajustes:

- Brillo.
- Contraste.
- Intensidad de trama/dithering.
- Sensibilidad al rojo.
- Nitidez de 0 a 10.
- Entrada manual en una linea: brillo, contraste, trama, nitidez y rojo.
- Restablecer valores del preset.

El estado completo cabe en menos de 64 bytes y se codifica dentro de cada
`callback_data`. La previsualizacion responde a la foto original, por lo que un
cold start puede recuperar el archivo desde Telegram sin almacenamiento local.
La solicitud de valores manuales lleva una sesion firmada en una entidad de
enlace: contiene `file_id`, estado, chat y mensaje de preview, sin base de datos.

## Conversion de imagen

El conversor es propio y no depende de OpenCV ni NumPy:

- Pillow corrige EXIF y aplana transparencias sobre blanco.
- Crop tipo cover conserva el aspect ratio.
- Filtro mediano para fotografias.
- Unsharp mask ajustable despues de reducir ruido y antes del dithering.
- Ajustes de brillo y contraste.
- Las fotos BWR usan cuantizacion RGB vectorial con paleta blanco/negro/rojo y
  difusion Floyd-Steinberg por canal, siguiendo la intencion visual de Lory.
- Esto usa rojo como tercer tono perceptual: piel y otros tonos calidos pueden
  convertirse en tramas rojo/blanco o rojo/negro.
- La sensibilidad roja ajusta gradualmente la calidez antes de cuantizar; a
  nivel 5 reproduce la seleccion por distancia RGB sin modificar la imagen.
- No multiplicar la distancia al rojo: provoca transiciones abruptas y manchas
  solidas al pasar entre niveles consecutivos.
- El preset Foto BWR parte con contraste 0, dithering 10 y rojo 5 para imitar
  los valores efectivos predeterminados de la app de escritorio.
- Floyd-Steinberg para fotos.
- Umbral fijo para texto/logo.
- Nunca se permite que un pixel sea negro y rojo simultaneamente.

## Formato `current.epd`

Cabecera `EPD1` little-endian de 24 bytes:

- Magic de 4 bytes.
- Version 1.
- Modo 1=BW o 2=BWR.
- Tamano de cabecera.
- Flags.
- Ancho 296.
- Alto 152.
- 37 bytes por fila.
- Longitud de payload.
- Unix timestamp.
- CRC32 del payload.

Plano BW:

- 5.624 bytes.
- MSB primero.
- Bit `0` significa pixel negro activo.

Plano BWR:

- 5.624 bytes negros seguidos por 5.624 bytes rojos.
- Bit `0` activa el color correspondiente.
- Total de payload: 11.248 bytes.

El ESP rechaza archivos truncados, con datos sobrantes, CRC incorrecto,
dimensiones inesperadas o colores solapados. Ante cualquier problema conserva
la imagen anterior y duerme hasta el siguiente ciclo.

## Repositorios investigados

### Firmware de Lory

Repositorio:
https://github.com/Loryuwu/Firmware-for-ESP32-to-ePaper-control

Commit revisado:
`012ce3552bb09f52ae31cfc374f6b2f8a26635fc`

Hallazgos:

- Confirma el uso de `Screen_EPD_EXT3`.
- Confirma el modelo `eScreen_EPD_266_JS_0C`.
- `testWBR()` demuestra blanco, negro y rojo.
- Su receptor de bitmap solo procesa un plano monocromo.
- Espera comandos seriales y no esta orientado a deep sleep.
- Algunos timeouts procesan datos parciales; el proyecto nuevo nunca lo hara.

### App de escritorio de Lory

Repositorio:
https://github.com/Loryuwu/Desktop-app-for-ePaper

Commit revisado:
`a2daba60ada6d69b2673707594f4eb91b170beab`

Ideas conservadas:

- Brillo, contraste, dithering, reduccion de ruido y bordes.
- Modos BW y BWR.
- Sensibilidad roja.
- Previsualizacion y restablecimiento de valores.

Codigo no reutilizado:

- Fuerza `resize(296, 152)` y deforma fotografias.
- Calcula una mascara HSV roja que no usa en la seleccion final.
- Genera BWR de 2 bits por pixel, incompatible con el firmware serial.
- El editor de dibujo reconstruye una imagen blanca al exportar.
- No corrige EXIF.
- No incluye una licencia visible.

## Estimacion de consumo

Escala relativa de corriente instantanea:

| Accion | Nivel 1-10 | Comentario |
|---|---:|---|
| Deep sleep | 1 | Objetivo 0,020 mA |
| Leer NVS/CRC | 2 | Muy breve |
| Arranque y CPU | 3 | Breve |
| Preparar framebuffer | 3 | WiFi ya apagado |
| Refresco e-ink | 6 | Menor pico que WiFi, pero puede durar varios segundos |
| HTTP/descarga | 8 | Radio activa |
| Asociacion WiFi | 10 | Mayor corriente y picos |

El deep sleep domina el consumo diario por durar casi 24 horas:
20 uA equivalen aproximadamente a 0,48 mAh por dia. El firmware imprime una
estimacion provisional por ciclo; las constantes se ajustaran con mediciones.

## Estado actual y pendientes

Implementado en el workspace:

- Proyecto PlatformIO.
- Parser C++ `EPD1`.
- Firmware de ciclo diario.
- Bot Telegram.
- Conversor Pillow.
- Publicador GitHub.
- Configuracion Render.
- Pruebas Python y prueba nativa C++.

Pendiente de hardware:

- Confirmar pinout real y cableado EXT3.
- Subir el firmware al ESP32-S3.
- Medir tiempo real de `flush()`.
- Medir deep sleep, picos WiFi y consumo del regulador/LED.
- Confirmar orientacion fisica de la pantalla.
- Ajustar timeout y corrientes estimadas.

Servicios configurados:

- Bot creado con BotFather y usuario autorizado.
- Render activo con webhook de Telegram.
- Token GitHub de alcance limitado configurado en Render.
- GitHub Pages activo desde `/docs`.
- URL final configurada en bot, Pages y ejemplo de firmware.

Pendiente antes del hardware:

- Pulsar `Publicar` en Telegram al menos una vez.
- Confirmar que `current.epd` deja de responder 404 y validar tamano/cabecera.
- Crear `include/secrets.h` con WiFi real y la URL final.
- GitHub Actions sigue desactivado por el bloqueo de facturacion de la cuenta;
  las pruebas locales pasan y el firmware compila.
