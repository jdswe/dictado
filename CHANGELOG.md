# Cambios

## 0.1.0 — 2026-11-18

Primera versión.

- **Dictado**: mantén **Super+J**, habla y suelta; el texto se escribe donde está el cursor, en cualquier app. Un toque corto activa el modo manos libres.
- **Transcripción en vivo** (**Super+Shift+J**): micrófono («Yo») y audio del sistema («Otros») en un `.txt` ordenado por hora, guardado al momento, con filtro de eco para altavoces e indicador REC.
- **Archivos**: `dictado transcribe video.mp4` crea `video.txt` con marcas de tiempo.
- Whisper local con faster-whisper (CPU, int8); español e inglés detectados solos.
- API D-Bus `dev.dictado.Dictado` para otras extensiones.
- Instalación sin sudo: `curl -fsSL https://jdswe.github.io/dictado/install.sh | bash`
