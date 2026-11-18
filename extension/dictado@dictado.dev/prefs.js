import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

const METHODS = [
    ['auto', 'Automático (método de entrada o pegar)'],
    ['input-method', 'Solo método de entrada'],
    ['paste', 'Siempre portapapeles + Ctrl+V'],
];

export default class DictadoPrefs extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        const page = new Adw.PreferencesPage();
        window.add(page);

        const keys = new Adw.PreferencesGroup({
            title: 'Atajos',
            description: 'Formato GTK, p. ej. <Super>j o <Ctrl><Alt>space. ' +
                'Mantener el atajo = hablar mientras se mantiene; toque corto = empezar/terminar.',
        });
        page.add(keys);
        for (const [key, title] of [['dictation-shortcut', 'Dictado'],
            ['transcription-shortcut', 'Transcripción en vivo']]) {
            const row = new Adw.EntryRow({title, show_apply_button: true});
            row.text = settings.get_strv(key)[0] ?? '';
            row.connect('apply', () => {
                const accel = row.text.trim();
                const [ok] = Gtk.accelerator_parse(accel);
                if (accel && !ok) {
                    row.add_css_class('error');
                    return;
                }
                row.remove_css_class('error');
                settings.set_strv(key, accel ? [accel] : []);
            });
            keys.add(row);
        }

        const text = new Adw.PreferencesGroup({title: 'Texto'});
        page.add(text);
        const combo = new Adw.ComboRow({
            title: 'Cómo insertar',
            model: Gtk.StringList.new(METHODS.map(([, label]) => label)),
        });
        combo.selected = Math.max(0, METHODS.findIndex(([id]) => id === settings.get_string('insert-method')));
        combo.connect('notify::selected', () => settings.set_string('insert-method', METHODS[combo.selected][0]));
        text.add(combo);

        for (const [key, title, subtitle] of [
            ['restore-clipboard', 'Restaurar el portapapeles', 'Al pegar, se devuelve lo que había antes'],
            ['append-space', 'Espacio al final', 'Para encadenar dictados sin juntar palabras'],
            ['show-indicator', 'Icono en la barra superior', 'Durante la transcripción en vivo siempre se muestra'],
        ]) {
            const row = new Adw.SwitchRow({title, subtitle});
            settings.bind(key, row, 'active', Gio.SettingsBindFlags.DEFAULT);
            text.add(row);
        }
    }
}
