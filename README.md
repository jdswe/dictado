# Dictado

**Website:** https://jdswe.github.io/dictado/

**Local** voice dictation and transcription for Linux (GNOME on Wayland), in
the spirit of Wispr Flow. Whisper runs on your own CPU: no cloud, no account,
nothing leaves your computer.

- **Dictation** (microphone only): hold **Super+J**, speak, and the text appears
  at your cursor in any app (VS Code, your browser, the terminal…).
- **Live transcript** (what you hear + what you say): **Super+Shift+J** records
  the system audio (meetings, videos, classes) and your microphone at the same
  time and writes a `.txt` with `Me:` and `Others:` lines in time order.
- **Files**: transcribe an audio or video file to a `.txt` next to it.
- **D-Bus API** so other extensions (for example Macify's menu bar) can add a
  microphone button or an indicator without containing any of this code.

Spanish and English are detected **phrase by phrase**, so you can switch
languages in the middle of a recording.

## Install

### Requirements (Ubuntu 26.04 / GNOME 50)

```bash
sudo apt install python3-venv python3-gi ffmpeg pipewire-bin
```

(`python3-gi`, `ffmpeg` and `pw-record` usually come preinstalled; what is
usually missing is `python3-venv`.)

### One command

```bash
curl -fsSL https://jdswe.github.io/dictado/install.sh | bash
```

It downloads the latest release, checks its SHA-256 fingerprint and runs
`install.sh`. From a clone, run `./install.sh` directly. Without sudo, it:

1. creates a Python environment in `~/.local/share/dictado/venv` and installs
   [faster-whisper](https://github.com/SYSTRAN/faster-whisper);
2. installs the service (`dictado.service` for systemd + D-Bus activation);
3. installs and enables the GNOME Shell extension `dictado@dictado.dev`;
4. warns if **Super+J** clashes with another shortcut (GNOME's own shortcuts
   are left alone; Super+H stays «minimize»);
5. downloads the models once (`~/.cache/huggingface`, ~350 MB).

On Wayland, GNOME only loads new or updated extensions at login: **log out
and back in** after installing or updating.

`./uninstall.sh` removes everything except your texts, settings and models.

## Usage

| Action | How |
|---|---|
| Dictate (push to talk) | Hold **Super+J** while you speak; the text is typed when you let go |
| Dictate (hands-free) | Tap **Super+J** to start, tap again to stop |
| Live transcript | **Super+Shift+J** to start and to stop |
| Transcribe a file | `dictado transcribe video.mp4`, or the top bar menu → «Transcribe File…» |

While you dictate, a pill appears at the bottom («● Listening» with the
microphone level). During a live transcript the top bar shows a **red REC with
the elapsed time** and a notification appears: you are recording other people,
**tell them and ask for their consent**.

### Where things are saved

- Each dictation, with its time: `~/Documents/Dictations/YYYY-MM-DD.txt`
  (turn off with `save_dictations = false`).
- Live transcripts: `~/Documents/Transcripts/YYYY-MM-DD HH-MM.txt`. Each line
  is written and flushed to disk immediately: if something closes, nothing
  already transcribed is lost.

```
# Transcript 2026-11-18 14:03
# Me = microphone · Others = system audio

[14:03:15] Others: OK, let's start the review.
[14:03:21] Me: Sure, I finished the sign-up form.
[14:03:27] Others: Great, and the tests?
```

- Files: `video.mp4` → `video.txt` (or `video (2).txt` if it exists), with
  `[00:01:23]` timestamps.

### Command line

```bash
dictado toggle          # start/stop a dictation
dictado live            # start/stop a live transcript
dictado transcribe a.m4a b.mp4
dictado status          # service status
dictado watch           # print D-Bus signals live
dictado bench audio.wav tiny base small   # measure speed on your machine
```

## Settings

`~/.config/dictado/config.toml` (created with comments the first time).
After editing it: `systemctl --user restart dictado`.

| Key | Default | |
|---|---|---|
| `dictation_model` | `small` | Dictation, files and your own voice in live transcripts |
| `transcription_model` | `base` | System audio in live transcripts (must keep up in real time) |
| `detect_model` | `tiny` | Only detects the language (see below for why) |
| `languages` | `["es", "en"]` | Languages to recognize; with one, nothing is detected |
| `save_dictations` | `true` | Keep every dictation with its time |
| `mic_source` | `""` | PipeWire microphone (empty = the default one) |
| `mic_label` / `system_label` | `Me` / `Others` | Labels in live transcripts |
| `echo_filter` | `true` | Drop speaker echo (see below) |

Most of these can also be changed in **Dictado Settings** (top bar menu →
Settings…, or *Dictado* in the app grid): shortcuts, how text is inserted,
clipboard restore, dictation model, languages and whether dictations are kept.
It restarts the service for you.

## How it works

```
 Super+J ─► GNOME Shell extension ──D-Bus──► service (Python)
                 ▲                                │ pw-record (PipeWire)
                 │ DictationText                  │ faster-whisper (CPU, int8)
                 └────────────────────────────────┘
   types the text into the focused app
```

### Typing into other apps on Wayland

On Wayland a normal app cannot type into another one. Options considered:

| Approach | Pros | Cons |
|---|---|---|
| **GNOME Shell extension** (chosen) | Runs inside the compositor: can use the input method and a Clutter virtual keyboard. No extra permissions, no dialogs, no root. Also provides the global shortcut and the indicator | One logout after installing; GNOME only |
| RemoteDesktop portal | Wayland standard | GNOME asks for permission with a dialog and shows a «remote control» indicator while active; meant for remote desktop, not an always-on service. Types according to the keyboard layout |
| ydotool | Works on any compositor | Needs a daemon with access to `/dev/uinput` (root or udev rules): any program could type as you. Types by keyboard layout (accents and ñ break) |
| wtype | Simple | GNOME doesn't implement the virtual keyboard protocol it uses |

The extension inserts text like this:

1. **Input method** (`Main.inputMethod.commit`), the same path as GNOME's
   on-screen keyboard, when the focused app supports it (GTK, Qt, Firefox…):
   the text goes in as is, with accents, ñ and emoji, without touching the
   clipboard.
2. Otherwise (X11/XWayland apps, VS Code and Chromium without the Wayland
   IME): **clipboard + Ctrl+V** through a Clutter virtual keyboard
   (Ctrl+Shift+V in terminals), then the previous clipboard is **restored**
   (text only; a copied image is lost).

Either can be forced in the settings.

### Spanish and English in the same recording

Whisper transcribes in one language at a time: forced to Spanish, English
speech gets dropped or translated (and vice versa). Dictado splits each
recording at the pauses (Silero VAD), detects the language of every phrase
and transcribes each run of same-language phrases with its own language. So
«Hola, hay salas en cuatro idiomas. Hi professor, I'm Jose…» comes out right
in both languages.

### Echo with speakers

With headphones the microphone only hears you. With speakers it also picks up
the others, who are already in the «Others» channel. Two layers handle this:

1. **Text filter (always on):** each microphone phrase is compared with what
   the speakers played at that moment (±2.5 s). If most of its words are
   already there, it is echo and is dropped. That is why «Me» lines take a few
   extra seconds to be written.
2. **PipeWire echo cancellation (optional, recommended with speakers):**

   ```bash
   mkdir -p ~/.config/pipewire/pipewire.conf.d
   cp data/99-dictado-echo-cancel.conf ~/.config/pipewire/pipewire.conf.d/
   systemctl --user restart pipewire pipewire-pulse wireplumber
   ```

   and in `config.toml`: `mic_source = "echo-cancel-source"`. It subtracts the
   speaker sound from the microphone signal before transcribing.

### Speed (AMD Ryzen 5 7520U, CPU only, int8, 4 threads)

Measured with `dictado bench` on 60 s of speech, **with another program using
3 cores at the same time** (an idle machine is somewhat faster):

| Model | 60 s of audio | Factor | Load |
|---|---|---|---|
| tiny | 3.2 s | 0.05× | ~1 s |
| base | 9.7 s | 0.16× | ~1 s |
| small | 29 s | 0.49× | ~2 s |
| large-v3-turbo | — | ~4.6× on short clips | 37 s |

Whisper always processes 30 s windows, so a short dictation costs almost as
much as a 30 s one: with `small`, 3–5 s after you let go. For speed, set
`dictation_model = "base"` (~1–2 s, slightly less accurate). Language detection
uses `tiny` because detecting with the same model would cost another full
pass; if you only dictate in one language, set `languages = ["es"]` and skip
that step.

**faster-whisper** (CTranslate2) was chosen over whisper.cpp because it
installs with `pip` without compiling anything, has wheels for Python 3.14,
uses int8 on the CPU (fast and light on memory) and includes Silero VAD to
skip silence.

## D-Bus API

Session bus · name `dev.dictado.Dictado` · object `/dev/dictado/Dictado` ·
interface `dev.dictado.Dictado1` (full definition in
[`dictado/dev.dictado.Dictado1.xml`](dictado/dev.dictado.Dictado1.xml)).
Calling any method starts the service if it isn't running.

| Methods | |
|---|---|
| `StartDictation()`, `StopDictation()`, `CancelDictation()`, `Toggle()` | Dictation |
| `StartTranscription() → s path`, `StopTranscription() → s path`, `ToggleTranscription()` | Live transcript |
| `TranscribeFile(s path) → s output` | In the background; `FileDone` when finished |
| `GetStatus() → a{sv}` | All properties |

| Signals | |
|---|---|
| `StateChanged(s dictation, s transcription)` | `idle`/`recording`/`processing` and `idle`/`recording` |
| `DictationText(s text, s language)` | Dictation result (the extension types it) |
| `Level(d level)` | Microphone level 0..1, ~10/s while dictating (for a waveform in an island) |
| `TranscriptLine(s speaker, s text, x unix_ms)` | Each new live transcript line |
| `FileProgress(s path, d fraction)`, `FileDone(s path, s output)`, `Error(s message)` | |

Properties (with `PropertiesChanged`): `Dictation`, `Transcription`,
`TranscriptPath`, `TranscriptionStarted` (unix ms), `ModelReady`.

Example:

```bash
gdbus call --session -d dev.dictado.Dictado -o /dev/dictado/Dictado -m dev.dictado.Dictado1.Toggle
```

If another extension calls `Toggle`, Dictado's extension still types the text
(it listens for `DictationText`), so the other one only needs the button.

## Development

```bash
./install.sh --dev                  # editable install
~/.local/share/dictado/venv/bin/pip install pytest
~/.local/share/dictado/venv/bin/python -m pytest tests
tests/shell/smoke.sh                # loads the extension in an isolated GNOME Shell
journalctl --user -u dictado -f     # service log
```

## Privacy

All audio is processed on your computer and never saved: only the text is.
The only thing downloaded from the internet is the models (Hugging Face, once).
Live transcripts record other people: in many places you are required to tell
them and get their consent.

## License

MIT.
