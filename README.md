# Dictado

Dictado por voz y transcripción **locales** para Linux (GNOME en Wayland), al
estilo de Wispr Flow. Usa Whisper en tu CPU: sin nube, sin cuenta, nada sale
de tu equipo.

- **Dictado** (solo micrófono): pulsa **Super+J**, habla, y el texto aparece
  donde está el cursor, en cualquier app (VS Code, el navegador, la terminal…).
- **Transcripción en vivo** (lo que oyes + lo que dices): **Super+Shift+J**
  graba a la vez el audio del sistema (reuniones, vídeos, clases) y tu
  micrófono, y escribe un `.txt` con líneas `Yo:` y `Otros:` por orden de hora.
- **Archivos**: transcribe un audio o vídeo a un `.txt` junto a él.
- **API D-Bus** para que otras extensiones (p. ej. la barra de Macify) añadan
  un botón de micrófono o un indicador sin contener nada de este código.

Español e inglés se detectan solos.

## Instalación

### Requisitos (Ubuntu 26.04 / GNOME 50)

```bash
sudo apt install python3-venv python3-gi ffmpeg pipewire-bin
```

(`python3-gi`, `ffmpeg` y `pw-record` normalmente ya vienen instalados; lo
único que suele faltar es `python3-venv`.)

### Instalar

```bash
./install.sh
```

El instalador, sin sudo:

1. crea un entorno de Python en `~/.local/share/dictado/venv` e instala
   [faster-whisper](https://github.com/SYSTRAN/faster-whisper);
2. instala el servicio (`dictado.service` de systemd + activación D-Bus);
3. instala y activa la extensión de GNOME Shell `dictado@dictado.dev`;
4. avisa si **Super+J** choca con otro atajo (no toca los atajos de GNOME;
   Super+H sigue siendo «minimizar»);
5. descarga los modelos una sola vez (`~/.cache/huggingface`, ~350 MB).

En Wayland, GNOME solo carga extensiones nuevas al iniciar sesión: **cierra
sesión y vuelve a entrar** la primera vez.

`./uninstall.sh` lo quita todo menos tus textos, la configuración y los modelos.

## Uso

| Acción | Cómo |
|---|---|
| Dictar (pulsar para hablar) | Mantén **Super+J** mientras hablas; al soltar se escribe el texto |
| Dictar (manos libres) | Toque corto en **Super+J** para empezar, otro para terminar |
| Transcripción en vivo | **Super+Shift+J** para empezar y para terminar |
| Transcribir un archivo | `dictado transcribe video.mp4` o el menú del icono → «Transcribir un archivo…» |

Mientras dictas aparece una píldora abajo («● Escuchando» con el nivel del
micrófono). Durante la transcripción en vivo la barra superior muestra un
**REC rojo con el tiempo** y sale una notificación: estás grabando a otras
personas, **avísales y pide su consentimiento**.

### Dónde se guarda

- Cada dictado, con su hora: `~/Documents/Dictados/AAAA-MM-DD.txt`
  (desactivable con `save_dictations = false`).
- Transcripciones en vivo: `~/Documents/Transcripciones/AAAA-MM-DD HH-MM.txt`.
  Cada línea se escribe y se guarda en disco al momento: si algo se cierra, no
  se pierde lo ya transcrito.

```
# Transcripción 2026-11-18 14:03
# Yo = micrófono · Otros = audio del sistema

[14:03:15] Otros: Bueno, empecemos con la revisión del sprint.
[14:03:21] Yo: Vale, yo terminé la validación de la placa.
[14:03:27] Otros: Perfecto, ¿y los duplicados?
```

- Archivos: `video.mp4` → `video.txt` (o `video (2).txt` si ya existe), con
  marcas `[00:01:23]`.

### Línea de órdenes

```bash
dictado toggle          # empieza/termina un dictado
dictado live            # empieza/termina la transcripción en vivo
dictado transcribe a.m4a b.mp4
dictado status          # estado del servicio
dictado watch           # ver las señales D-Bus en directo
dictado bench audio.wav tiny base small   # medir velocidad en tu equipo
```

## Configuración

`~/.config/dictado/config.toml` (se crea con comentarios la primera vez).
Tras cambiarlo: `systemctl --user restart dictado`.

| Clave | Por defecto | |
|---|---|---|
| `dictation_model` | `small` | Modelo del dictado y de los archivos |
| `transcription_model` | `base` | Modelo de la transcripción en vivo (tiene que ir a tiempo real con dos fuentes) |
| `detect_model` | `tiny` | Solo para detectar el idioma (más abajo, por qué) |
| `languages` | `["es", "en"]` | Idiomas permitidos; con uno solo no se detecta nada |
| `save_dictations` | `true` | Guardar cada dictado con hora |
| `mic_source` | `""` | Micrófono de PipeWire (vacío = el predeterminado) |
| `mic_label` / `system_label` | `Yo` / `Otros` | Etiquetas en la transcripción |
| `echo_filter` | `true` | Descartar el eco de los altavoces (ver abajo) |

Las preferencias de la extensión (atajos, cómo insertar el texto, restaurar el
portapapeles) están en *Extensiones → Dictado → Configuración*.

## Cómo funciona

```
 Super+J ─► extensión de GNOME Shell ──D-Bus──► servicio (Python)
                 ▲                                  │ pw-record (PipeWire)
                 │ DictationText                    │ faster-whisper (CPU, int8)
                 └──────────────────────────────────┘
   escribe el texto en la app con el foco
```

### Escribir en otras apps en Wayland

En Wayland una app normal no puede teclear en otra. Opciones que se valoraron:

| Vía | Ventajas | Problemas |
|---|---|---|
| **Extensión de GNOME Shell** (elegida) | Corre dentro del compositor: puede usar el método de entrada y un teclado virtual de Clutter. Sin permisos extra, sin diálogos, sin root. Además da el atajo global y el indicador | Hay que cerrar sesión una vez al instalar; solo GNOME |
| Portal RemoteDesktop | Estándar de Wayland | GNOME pide permiso con un diálogo y muestra el aviso de «control remoto» mientras está activo; pensado para escritorio remoto, no para un servicio siempre encendido. Teclea según la distribución de teclado |
| ydotool | Funciona en cualquier compositor | Necesita un demonio con acceso a `/dev/uinput` (root o reglas udev): cualquier programa podría teclear por ti. Teclea según la distribución de teclado (tildes y ñ fallan) |
| wtype | Sencillo | GNOME no implementa el protocolo de teclado virtual que usa |

La extensión inserta el texto así:

1. **Método de entrada** (`Main.inputMethod.commit`), el mismo camino que el
   teclado en pantalla de GNOME, si la app con el foco lo admite (GTK, Qt,
   Firefox…): entra tal cual, con tildes, ñ y emojis, sin tocar el
   portapapeles.
2. Si no (apps X11/XWayland, VS Code y Chromium sin IME de Wayland):
   **portapapeles + Ctrl+V** con un teclado virtual de Clutter (Ctrl+Shift+V
   en terminales) y después se **restaura el portapapeles** anterior (solo
   texto; si tenías una imagen copiada, se pierde).

Se puede forzar uno u otro en las preferencias.

### Eco con altavoces

Con auriculares el micrófono solo te oye a ti. Con altavoces también capta a
los demás, que ya están en el canal «Otros». Dictado lo resuelve en dos capas:

1. **Filtro por texto (siempre activo):** cada frase del micrófono se compara
   con lo que sonó por los altavoces en ese momento (±2,5 s). Si la mayoría de
   sus palabras ya están ahí, es eco y se descarta. Por eso las líneas «Yo»
   tardan unos segundos más en escribirse.
2. **Cancelación de eco de PipeWire (opcional, recomendada con altavoces):**

   ```bash
   mkdir -p ~/.config/pipewire/pipewire.conf.d
   cp data/99-dictado-echo-cancel.conf ~/.config/pipewire/pipewire.conf.d/
   systemctl --user restart pipewire pipewire-pulse wireplumber
   ```

   y en `config.toml`: `mic_source = "echo-cancel-source"`. Resta el sonido de
   los altavoces de la señal del micrófono antes de transcribir.

### Velocidad (AMD Ryzen 5 7520U, solo CPU, int8, 4 hilos)

Medido con `dictado bench` sobre 60 s de habla, **con otro programa usando 3
núcleos a la vez** (en un equipo libre será algo más rápido):

| Modelo | 60 s de audio | Factor | Carga |
|---|---|---|---|
| tiny | 3,2 s | 0,05× | ~1 s |
| base | 9,7 s | 0,16× | ~1 s |
| small | 29 s | 0,49× | ~2 s |
| large-v3-turbo | — | ~4,6× en clips cortos | 37 s |

Whisper procesa siempre ventanas de 30 s, así que un dictado corto cuesta casi
lo mismo que uno de 30 s: con `small`, entre 3 y 5 s tras soltar la tecla. Si
prefieres rapidez, `dictation_model = "base"` (~1-2 s, algo menos preciso).
La detección de idioma se hace con `tiny` porque hacerla con el mismo modelo
costaría otra pasada completa; si solo dictas en un idioma, pon
`languages = ["es"]` y te ahorras ese paso.

Se eligió **faster-whisper** (CTranslate2) frente a whisper.cpp porque se
instala con `pip` sin compilar nada, trae ruedas para Python 3.14, usa int8 en
CPU (rápido y poca memoria) e incluye el VAD de Silero para no transcribir
silencios.

## API D-Bus

Bus de sesión · nombre `dev.dictado.Dictado` · objeto `/dev/dictado/Dictado` ·
interfaz `dev.dictado.Dictado1` (definición completa en
[`dictado/dev.dictado.Dictado1.xml`](dictado/dev.dictado.Dictado1.xml)). Llamar
a cualquier método arranca el servicio si no está en marcha.

| Métodos | |
|---|---|
| `StartDictation()`, `StopDictation()`, `CancelDictation()`, `Toggle()` | Dictado |
| `StartTranscription() → s ruta`, `StopTranscription() → s ruta`, `ToggleTranscription()` | Transcripción en vivo |
| `TranscribeFile(s ruta) → s salida` | En segundo plano; avisa con `FileDone` |
| `GetStatus() → a{sv}` | Todas las propiedades |

| Señales | |
|---|---|
| `StateChanged(s dictado, s transcripcion)` | `idle`/`recording`/`processing` y `idle`/`recording` |
| `DictationText(s texto, s idioma)` | Resultado del dictado (la extensión lo escribe) |
| `Level(d nivel)` | Nivel del micro 0..1, ~10/s mientras se dicta (para una onda en una «isla») |
| `TranscriptLine(s quien, s texto, x ms_unix)` | Cada línea nueva de la transcripción en vivo |
| `FileProgress(s ruta, d fraccion)`, `FileDone(s ruta, s salida)`, `Error(s mensaje)` | |

Propiedades (con `PropertiesChanged`): `Dictation`, `Transcription`,
`TranscriptPath`, `TranscriptionStarted` (ms unix), `ModelReady`.

Ejemplo:

```bash
gdbus call --session -d dev.dictado.Dictado -o /dev/dictado/Dictado -m dev.dictado.Dictado1.Toggle
```

Si otra extensión llama a `Toggle`, el texto lo sigue escribiendo la extensión
de Dictado (escucha `DictationText`), así que la otra solo necesita el botón.

## Desarrollo

```bash
./install.sh --dev                  # instalación editable
~/.local/share/dictado/venv/bin/pip install pytest
~/.local/share/dictado/venv/bin/python -m pytest tests
tests/shell/smoke.sh                # carga la extensión en un GNOME Shell aislado
journalctl --user -u dictado -f     # registro del servicio
```

## Privacidad

Todo el audio se procesa en tu equipo y no se guarda: solo el texto. Lo único
que se descarga de internet son los modelos (Hugging Face, una vez). La
transcripción en vivo graba a otras personas: en muchos lugares es obligatorio
avisar y obtener su consentimiento.

## Licencia

MIT.
