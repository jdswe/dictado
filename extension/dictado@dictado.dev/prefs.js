import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

const METHODS = [
    ['auto', 'Automatic'],
    ['input-method', 'Input method only'],
    ['paste', 'Always paste (Ctrl+V)'],
];

export default class DictadoPrefs extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        const page = new Adw.PreferencesPage();
        window.add(page);

        const keys = new Adw.PreferencesGroup({
            title: 'Shortcuts',
            description: 'GTK format, e.g. <Super>j or <Ctrl><Alt>space. ' +
                'Hold to talk, or tap to start and tap again to stop.',
        });
        page.add(keys);
        for (const [key, title] of [['dictation-shortcut', 'Dictation'],
            ['transcription-shortcut', 'Live Transcript']]) {
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

        const text = new Adw.PreferencesGroup({title: 'Typing'});
        page.add(text);
        const combo = new Adw.ComboRow({
            title: 'Insert Text By',
            model: Gtk.StringList.new(METHODS.map(([, label]) => label)),
        });
        combo.selected = Math.max(0, METHODS.findIndex(([id]) => id === settings.get_string('insert-method')));
        combo.connect('notify::selected', () => settings.set_string('insert-method', METHODS[combo.selected][0]));
        text.add(combo);

        for (const [key, title, subtitle] of [
            ['restore-clipboard', 'Restore Clipboard', 'Put back what you had copied after pasting'],
            ['append-space', 'Trailing Space', 'Keeps consecutive dictations from running together'],
            ['show-indicator', 'Top Bar Icon', 'Always shown during a live transcript'],
        ]) {
            const row = new Adw.SwitchRow({title, subtitle});
            settings.bind(key, row, 'active', Gio.SettingsBindFlags.DEFAULT);
            text.add(row);
        }
    }
}
