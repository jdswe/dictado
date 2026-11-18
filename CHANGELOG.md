# Changelog

## 0.2.1 — 2026-11-18

- Notifications for saved transcripts and transcribed files now preview the first lines of text. Click one (in the banner or in the notification list) to open the file, or use **Show in Folder**. They appear under Dictado's own name and icon.

## 0.2.0 — 2026-11-18

- **Spanish and English in the same recording**: the language is now detected phrase by phrase, so switching languages mid-sentence no longer drops or translates the other one. Applies to dictation, live transcripts and files.
- Live transcripts use the more accurate model for your own voice (the system audio keeps the faster one).
- **Everything in English**: top bar menu with short labels and shortcut hints (Dictate, Live Transcript, Transcribe File…), settings, notifications, transcript files (`Me` / `Others`) and folders (`~/Documents/Dictations`, `~/Documents/Transcripts`). An untouched 0.1.0 config and the old Spanish folders are migrated automatically.

## 0.1.0 — 2026-11-18

First release.

- **Dictation**: hold **Super+J**, speak and let go; the text is typed at your cursor in any app. A quick tap starts hands-free mode.
- **Live transcript** (**Super+Shift+J**): your microphone and the system audio go into a `.txt` ordered by time and saved as it goes, with an echo filter for speakers and a REC indicator.
- **Files**: `dictado transcribe video.mp4` writes `video.txt` with timestamps.
- Local Whisper via faster-whisper (CPU, int8); Spanish and English detected automatically.
- D-Bus API `dev.dictado.Dictado` for other extensions.
- Install without sudo: `curl -fsSL https://jdswe.github.io/dictado/install.sh | bash`
