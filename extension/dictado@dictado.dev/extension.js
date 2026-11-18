// Dictado — extensión de GNOME Shell.
//
// No contiene nada de audio ni de Whisper: habla con el servicio
// `dev.dictado.Dictado` por D-Bus. Se encarga de lo que en Wayland solo puede
// hacer el propio compositor:
//   · el atajo global (mantener = hablar, toque = empezar/terminar),
//   · escribir el texto donde está el cursor en cualquier app,
//   · el indicador de grabación en la barra superior y la píldora flotante.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'dev.dictado.Dictado';
const OBJECT_PATH = '/dev/dictado/Dictado';

const IFACE = `
<node>
  <interface name="dev.dictado.Dictado1">
    <method name="StartDictation"/>
    <method name="StopDictation"/>
    <method name="CancelDictation"/>
    <method name="Toggle"/>
    <method name="StartTranscription"><arg type="s" direction="out"/></method>
    <method name="StopTranscription"><arg type="s" direction="out"/></method>
    <method name="ToggleTranscription"/>
    <method name="TranscribeFile"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
    <property name="Dictation" type="s" access="read"/>
    <property name="Transcription" type="s" access="read"/>
    <property name="TranscriptPath" type="s" access="read"/>
    <property name="TranscriptionStarted" type="x" access="read"/>
    <signal name="StateChanged"><arg type="s"/><arg type="s"/></signal>
    <signal name="DictationText"><arg type="s"/><arg type="s"/></signal>
    <signal name="Level"><arg type="d"/></signal>
    <signal name="Error"><arg type="s"/></signal>
  </interface>
</node>`;
const DictadoProxy = Gio.DBusProxy.makeProxyWrapper(IFACE);

const TERMINALS = /terminal|ptyxis|kgx|konsole|tilix|alacritty|kitty|wezterm|xterm|console|foot|ghostty|blackbox/i;
const MODS = Clutter.ModifierType.SUPER_MASK | Clutter.ModifierType.MOD4_MASK |
    Clutter.ModifierType.SHIFT_MASK | Clutter.ModifierType.CONTROL_MASK |
    Clutter.ModifierType.MOD1_MASK;
const BARS = 5;

function fmtElapsed(ms) {
    const s = Math.max(0, Math.floor(ms / 1000));
    const h = Math.floor(s / 3600);
    const m = String(Math.floor(s % 3600 / 60)).padStart(2, '0');
    const ss = String(s % 60).padStart(2, '0');
    return h ? `${h}:${m}:${ss}` : `${m}:${ss}`;
}

// Píldora flotante abajo al centro: «● Escuchando ▮▮▮» / «Transcribiendo…».
const Pill = GObject.registerClass(
class DictadoPill extends St.BoxLayout {
    _init() {
        super._init({style_class: 'dictado-pill', reactive: false, visible: false});
        this._dot = new St.Label({text: '●', style_class: 'dictado-pill-dot',
            y_align: Clutter.ActorAlign.CENTER});
        this._label = new St.Label({text: 'Escuchando', style_class: 'dictado-pill-label',
            y_align: Clutter.ActorAlign.CENTER});
        this._bars = new St.BoxLayout({style_class: 'dictado-bars', y_align: Clutter.ActorAlign.CENTER});
        this._barActors = [];
        for (let i = 0; i < BARS; i++) {
            const bar = new St.Widget({style_class: 'dictado-bar', height: 4,
                y_align: Clutter.ActorAlign.CENTER});
            this._barActors.push(bar);
            this._bars.add_child(bar);
        }
        this.add_child(this._dot);
        this.add_child(this._label);
        this.add_child(this._bars);
        this._levels = new Array(BARS).fill(0);
        Main.layoutManager.addTopChrome(this);
    }

    showState(state) {
        if (state === 'recording') {
            this._label.text = 'Escuchando';
            this._dot.show();
            this.remove_style_class_name('dictado-pill-processing');
        } else if (state === 'processing') {
            this._label.text = 'Transcribiendo…';
            this._dot.hide();
            this.add_style_class_name('dictado-pill-processing');
            this.setLevel(0.15);
        } else {
            this.hide();
            return;
        }
        this.show();
        this._reposition();
    }

    setLevel(level) {
        this._levels.shift();
        this._levels.push(level);
        const scale = St.ThemeContext.get_for_stage(global.stage).scale_factor;
        this._barActors.forEach((bar, i) => {
            bar.height = Math.round((4 + 18 * this._levels[i]) * scale);
        });
    }

    _reposition() {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;
        const [, natW] = this.get_preferred_width(-1);
        const [, natH] = this.get_preferred_height(-1);
        this.set_position(
            Math.round(monitor.x + (monitor.width - natW) / 2),
            Math.round(monitor.y + monitor.height - natH - monitor.height * 0.08));
    }
});

const Indicator = GObject.registerClass(
class DictadoIndicator extends PanelMenu.Button {
    _init(ext) {
        super._init(0.5, 'Dictado');
        this._ext = ext;
        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        this._icon = new St.Icon({icon_name: 'audio-input-microphone-symbolic',
            style_class: 'system-status-icon'});
        this._rec = new St.Label({style_class: 'dictado-rec-label', visible: false,
            y_align: Clutter.ActorAlign.CENTER});
        box.add_child(this._icon);
        box.add_child(this._rec);
        this.add_child(box);

        this._dictItem = this.menu.addAction('Dictar', () => ext.toggleDictation());
        this._liveItem = this.menu.addAction('Iniciar transcripción (tú + sistema)',
            () => ext.toggleTranscription());
        this._fileItem = this.menu.addAction('Transcribir un archivo…', () => ext.spawn(['pick']));
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this.menu.addAction('Abrir transcripciones', () => ext.openFolder('Transcripciones'));
        this.menu.addAction('Abrir dictados', () => ext.openFolder('Dictados'));
        this.menu.addAction('Preferencias', () => ext.openPreferences());
    }

    update(dictation, transcription, started) {
        const live = transcription === 'recording';
        const busy = dictation !== 'idle';
        this._icon.icon_name = live ? 'media-record-symbolic'
            : busy ? 'microphone-sensitivity-high-symbolic' : 'audio-input-microphone-symbolic';
        if (live || dictation === 'recording')
            this.add_style_class_name('dictado-indicator-recording');
        else
            this.remove_style_class_name('dictado-indicator-recording');
        this._dictItem.label.text = dictation === 'recording' ? 'Terminar dictado'
            : dictation === 'processing' ? 'Transcribiendo dictado…' : 'Dictar';
        this._liveItem.label.text = live ? 'Detener transcripción'
            : 'Iniciar transcripción (tú + sistema)';
        this._started = started;
        this._rec.visible = live;
        this._tick();
    }

    _tick() {
        if (this._rec.visible)
            this._rec.text = `REC ${fmtElapsed(Date.now() - this._started)}`;
    }
});

export default class DictadoExtension extends Extension {
    enable() {
        this._settings = this.getSettings();
        this._dictation = 'idle';
        this._transcription = 'idle';
        this._started = 0;
        this._pressedAt = 0;
        this._holdPoll = 0;

        this._pill = new Pill();
        this._indicator = new Indicator(this);
        Main.panel.addToStatusArea(this.uuid, this._indicator);
        this._indicator.visible = this._settings.get_boolean('show-indicator');
        this._settings.connectObject('changed::show-indicator', () => {
            this._indicator.visible = this._settings.get_boolean('show-indicator') ||
                this._transcription === 'recording';
        }, this);

        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
            this._indicator?._tick();
            return GLib.SOURCE_CONTINUE;
        });

        const mode = Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW | Shell.ActionMode.POPUP;
        Main.wm.addKeybinding('dictation-shortcut', this._settings,
            Meta.KeyBindingFlags.IGNORE_AUTOREPEAT, mode, () => this._onDictationKey());
        Main.wm.addKeybinding('transcription-shortcut', this._settings,
            Meta.KeyBindingFlags.IGNORE_AUTOREPEAT, mode, () => this.toggleTranscription());

        this._cancellable = new Gio.Cancellable();
        this._proxy = null;
        new DictadoProxy(Gio.DBus.session, BUS_NAME, OBJECT_PATH, (proxy, error) => {
            if (error) {
                if (!error.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                    console.error(`Dictado: ${error.message}`);
                return;
            }
            this._proxy = proxy;
            this._signals = [
                proxy.connectSignal('StateChanged', (_p, _s, [d, t]) => this._onState(d, t)),
                proxy.connectSignal('DictationText', (_p, _s, [text]) => this._insert(text)),
                proxy.connectSignal('Level', (_p, _s, [level]) => this._pill.setLevel(level)),
                proxy.connectSignal('Error', (_p, _s, [msg]) => Main.notifyError('Dictado', msg)),
            ];
            proxy.connectObject('notify::g-name-owner', () => {
                if (!proxy.g_name_owner)
                    this._onState('idle', 'idle');
            }, this);
            this._syncFromProperties();
        }, this._cancellable, Gio.DBusProxyFlags.DO_NOT_AUTO_START_AT_CONSTRUCTION);
    }

    disable() {
        this._cancellable?.cancel();
        Main.wm.removeKeybinding('dictation-shortcut');
        Main.wm.removeKeybinding('transcription-shortcut');
        if (this._holdPoll)
            GLib.source_remove(this._holdPoll);
        if (this._timer)
            GLib.source_remove(this._timer);
        for (const id of [this._restoreId, this._pasteId]) {
            if (id)
                GLib.source_remove(id);
        }
        if (this._proxy) {
            for (const id of this._signals ?? [])
                this._proxy.disconnectSignal(id);
            this._proxy.disconnectObject(this);
        }
        this._settings.disconnectObject(this);
        this._indicator?.destroy();
        this._pill?.destroy();
        this._device?.run_dispose();
        this._device = null;
        this._indicator = this._pill = this._proxy = this._settings = null;
        this._holdPoll = this._timer = this._restoreId = this._pasteId = 0;
    }

    // -- estado ---------------------------------------------------------
    _syncFromProperties() {
        const d = this._proxy.Dictation ?? 'idle';
        const t = this._proxy.Transcription ?? 'idle';
        this._started = Number(this._proxy.TranscriptionStarted ?? 0);
        this._onState(d, t);
    }

    _onState(dictation, transcription) {
        if (transcription === 'recording' && this._transcription !== 'recording')
            this._started = Number(this._proxy?.TranscriptionStarted || 0) || Date.now();
        this._dictation = dictation;
        this._transcription = transcription;
        this._pill.showState(dictation);
        this._indicator.visible = this._settings.get_boolean('show-indicator') ||
            transcription === 'recording';
        this._indicator.update(dictation, transcription, this._started);
    }

    _call(method, ...args) {
        // Las llamadas arrancan el servicio si no está en marcha (activación D-Bus).
        const run = proxy => proxy[`${method}Async`](...args).catch(e => {
            console.error(`Dictado ${method}: ${e.message}`);
            Main.notifyError('Dictado', `No se pudo contactar con el servicio: ${e.message}`);
        });
        if (this._proxy)
            return run(this._proxy);
        return Promise.resolve();
    }

    // -- atajos ---------------------------------------------------------
    toggleDictation() {
        if (this._dictation === 'recording')
            this._call('StopDictation');
        else if (this._dictation === 'idle')
            this._startDictation();
    }

    _startDictation() {
        this._dictation = 'recording';
        this._pill.showState('recording');
        this._call('StartDictation');
    }

    _onDictationKey() {
        if (this._dictation === 'recording') {
            this._call('StopDictation');
            return;
        }
        if (this._dictation !== 'idle')
            return;
        this._startDictation();
        // Si el atajo se mantiene pulsado, se para al soltarlo (pulsar para
        // hablar). Si fue un toque corto, sigue grabando hasta el próximo toque.
        this._pressedAt = GLib.get_monotonic_time();
        if (this._holdPoll)
            GLib.source_remove(this._holdPoll);
        this._holdPoll = GLib.timeout_add(GLib.PRIORITY_HIGH, 30, () => {
            const [, , mods] = global.get_pointer();
            if (mods & MODS)
                return GLib.SOURCE_CONTINUE;
            this._holdPoll = 0;
            const held = (GLib.get_monotonic_time() - this._pressedAt) / 1000;
            if (held >= this._settings.get_int('hold-threshold') && this._dictation === 'recording')
                this._call('StopDictation');
            return GLib.SOURCE_REMOVE;
        });
    }

    toggleTranscription() {
        if (this._transcription === 'recording')
            this._call('StopTranscription');
        else
            this._call('StartTranscription');
    }

    // -- escribir el texto ----------------------------------------------
    _insert(text) {
        if (!text)
            return;
        if (this._settings.get_boolean('append-space'))
            text += ' ';
        const method = this._settings.get_string('insert-method');
        const im = Main.inputMethod;
        // Apps con text-input (GTK, Qt, Firefox…): el texto entra por el
        // método de entrada, sin tocar el portapapeles ni simular teclas.
        if (method === 'input-method' || (method === 'auto' && im?.currentFocus)) {
            im.commit(text);
            return;
        }
        this._paste(text);
    }

    _paste(text) {
        // Apps X11 (XWayland) o Electron/Chromium sin IME de Wayland:
        // portapapeles + Ctrl+V (Ctrl+Shift+V en terminales) con un teclado
        // virtual de Clutter, y luego se restaura el portapapeles.
        const clipboard = St.Clipboard.get_default();
        clipboard.get_text(St.ClipboardType.CLIPBOARD, (_c, previous) => {
            clipboard.set_text(St.ClipboardType.CLIPBOARD, text);
            this._pasteId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 60, () => {
                this._pasteId = 0;
                this._sendPaste();
                if (this._settings.get_boolean('restore-clipboard') && previous !== null) {
                    this._restoreId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 800, () => {
                        this._restoreId = 0;
                        clipboard.set_text(St.ClipboardType.CLIPBOARD, previous);
                        return GLib.SOURCE_REMOVE;
                    });
                }
                return GLib.SOURCE_REMOVE;
            });
        });
    }

    _sendPaste() {
        const window = global.display.focus_window;
        const terminal = TERMINALS.test(window?.get_wm_class() ?? '');
        this._device ??= Clutter.get_default_backend().get_default_seat()
            .create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);
        const keys = terminal ? [Clutter.KEY_Control_L, Clutter.KEY_Shift_L, Clutter.KEY_v]
            : [Clutter.KEY_Control_L, Clutter.KEY_v];
        const press = (key, state) => this._device.notify_keyval(GLib.get_monotonic_time(), key, state);
        keys.forEach(key => press(key, Clutter.KeyState.PRESSED));
        [...keys].reverse().forEach(key => press(key, Clutter.KeyState.RELEASED));
    }

    // -- utilidades del menú ---------------------------------------------
    spawn(args) {
        const bin = GLib.find_program_in_path('dictado') ??
            GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'dictado']);
        try {
            Gio.Subprocess.new([bin, ...args], Gio.SubprocessFlags.NONE);
        } catch (e) {
            Main.notifyError('Dictado', e.message);
        }
    }

    openFolder(name) {
        // Mismas carpetas que los valores por defecto de ~/.config/dictado/config.toml
        const dir = Gio.File.new_for_path(GLib.build_filenamev([GLib.get_home_dir(), 'Documents', name]));
        try {
            dir.make_directory_with_parents(null);
        } catch {}
        Gio.AppInfo.launch_default_for_uri(dir.get_uri(), null);
    }
}
