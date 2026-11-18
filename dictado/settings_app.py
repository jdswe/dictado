"""Dictado Settings: a small GTK 4 / libadwaita app with Dictado's own name and
icon (application id `dev.dictado.App`, matching its .desktop file).

The extension's preferences are hosted by GNOME's Extensions app, so the dock
showed the Extensions icon. This app edits the same GSettings (shortcuts,
typing) plus the service's config.toml (speech model, languages, saving).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from dictado import __version__, config  # noqa: E402

APP_ID = "dev.dictado.App"
SCHEMA_ID = "org.gnome.shell.extensions.dictado"
UUID = "dictado@dictado.dev"

INSERT_METHODS = [("auto", "Automatic"), ("input-method", "Input method only"),
                  ("paste", "Always paste (Ctrl+V)")]
MODELS = [("base", "Fast (base)"), ("small", "Balanced (small)"), ("medium", "Accurate (medium, slow)")]
LANGUAGES = [(["es", "en"], "Spanish and English"), (["es"], "Spanish only"), (["en"], "English only")]


def extension_settings() -> Gio.Settings | None:
    """The extension's GSettings; its schema lives in the extension folder."""
    dirs = [Path(GLib.get_user_data_dir()) / "gnome-shell/extensions" / UUID / "schemas",
            Path("/usr/share/gnome-shell/extensions") / UUID / "schemas"]
    for d in dirs:
        if (d / "gschemas.compiled").exists():
            source = Gio.SettingsSchemaSource.new_from_directory(
                str(d), Gio.SettingsSchemaSource.get_default(), False)
            schema = source.lookup(SCHEMA_ID, False)
            if schema:
                return Gio.Settings.new_full(schema, None, None)
    return None


def set_config_value(key: str, value: str, path: Path = config.CONFIG_FILE) -> None:
    """Replace `key = …` in config.toml (keeping comments), or append it."""
    config.write_default(path)
    text = path.read_text(encoding="utf-8")
    line = f"{key} = {value}"
    pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
    text = pattern.sub(line, text, count=1) if pattern.search(text) else text.rstrip("\n") + f"\n{line}\n"
    path.write_text(text, encoding="utf-8")


def toml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


class Window(Adw.PreferencesWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="Dictado", default_width=560, default_height=680,
                         search_enabled=False)
        self.set_icon_name("dev.dictado.Dictado")
        self.cfg = config.load()
        self.settings = extension_settings()
        self._restart_id = 0
        page = Adw.PreferencesPage(title="Dictado", icon_name="audio-input-microphone-symbolic")
        self.add(page)
        if self.settings:
            page.add(self._shortcuts())
            page.add(self._typing())
        else:
            missing = Adw.PreferencesGroup(
                title="Extension not installed",
                description="Install Dictado's GNOME Shell extension to set shortcuts and typing.")
            page.add(missing)
        page.add(self._speech())
        page.add(self._files())
        about = Adw.PreferencesGroup()
        about.add(Adw.ActionRow(title="Version", subtitle=__version__))
        page.add(about)

    # -- extension settings -------------------------------------------
    def _shortcuts(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Shortcuts",
            description="Hold to talk, or tap to start and tap again to stop. "
                        "GTK format, e.g. &lt;Super&gt;j or &lt;Ctrl&gt;&lt;Alt&gt;space.")
        for key, title in (("dictation-shortcut", "Dictation"), ("transcription-shortcut", "Live Transcript")):
            row = Adw.EntryRow(title=title, show_apply_button=True)
            row.set_text((self.settings.get_strv(key) or [""])[0])

            def apply(r, k=key):
                accel = r.get_text().strip()
                ok = not accel or Gtk.accelerator_parse(accel)[0]
                if not ok:
                    r.add_css_class("error")
                    return
                r.remove_css_class("error")
                self.settings.set_strv(k, [accel] if accel else [])
            row.connect("apply", apply)
            group.add(row)
        return group

    def _typing(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Typing")
        combo = Adw.ComboRow(title="Insert Text By",
                             model=Gtk.StringList.new([label for _, label in INSERT_METHODS]))
        current = self.settings.get_string("insert-method")
        combo.set_selected(next((i for i, (v, _) in enumerate(INSERT_METHODS) if v == current), 0))
        combo.connect("notify::selected",
                      lambda c, _p: self.settings.set_string("insert-method", INSERT_METHODS[c.get_selected()][0]))
        group.add(combo)
        for key, title, subtitle in (
            ("restore-clipboard", "Restore Clipboard", "Put back what you had copied after pasting"),
            ("append-space", "Trailing Space", "Keeps consecutive dictations from running together"),
            ("show-indicator", "Top Bar Icon", "Always shown during a live transcript"),
        ):
            row = Adw.SwitchRow(title=title, subtitle=subtitle)
            self.settings.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)
            group.add(row)
        return group

    # -- service settings (config.toml) ----------------------------------
    def _speech(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Speech",
                                     description="Everything runs on this computer.")
        model = Adw.ComboRow(title="Dictation Model",
                             subtitle="Larger is more accurate and slower",
                             model=Gtk.StringList.new([label for _, label in MODELS]))
        model.set_selected(next((i for i, (v, _) in enumerate(MODELS) if v == self.cfg.dictation_model), 1))
        model.connect("notify::selected",
                      lambda c, _p: self._save("dictation_model", toml_str(MODELS[c.get_selected()][0])))
        group.add(model)

        langs = Adw.ComboRow(title="Languages",
                             subtitle="Detected phrase by phrase, so you can mix them",
                             model=Gtk.StringList.new([label for _, label in LANGUAGES]))
        langs.set_selected(next((i for i, (v, _) in enumerate(LANGUAGES) if v == list(self.cfg.languages)), 0))
        langs.connect("notify::selected", lambda c, _p: self._save(
            "languages", "[" + ", ".join(toml_str(l) for l in LANGUAGES[c.get_selected()][0]) + "]"))
        group.add(langs)

        save = Adw.SwitchRow(title="Keep Dictations", subtitle="Save each dictation with its time",
                             active=self.cfg.save_dictations)
        save.connect("notify::active", lambda r, _p: self._save("save_dictations",
                                                                  "true" if r.get_active() else "false"))
        group.add(save)
        return group

    def _save(self, key: str, value: str) -> None:
        set_config_value(key, value)
        # Restart the service once, shortly after the last change.
        if self._restart_id:
            GLib.source_remove(self._restart_id)
        self._restart_id = GLib.timeout_add(800, self._restart_service)

    def _restart_service(self) -> bool:
        self._restart_id = 0
        subprocess.Popen(["systemctl", "--user", "try-restart", "dictado.service"])
        toast = Adw.Toast(title="Settings saved", timeout=2)
        self.add_toast(toast)
        return False

    # -- folders -----------------------------------------------------------
    def _files(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Saved Text")
        for title, path in (("Dictations", self.cfg.dictation_path), ("Transcripts", self.cfg.transcripts_path)):
            row = Adw.ActionRow(title=title, subtitle=str(path).replace(str(Path.home()), "~"),
                                activatable=True)
            row.add_suffix(Gtk.Image(icon_name="folder-open-symbolic"))
            row.connect("activated", lambda _r, p=path: self._open(p))
            group.add(row)
        return group

    def _open(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(str(path)).get_uri(), None)


def main() -> int:
    GLib.set_application_name("Dictado")
    app = Adw.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def activate(a):
        win = a.get_active_window() or Window(a)
        win.present()
        win.set_focus(None)  # don't open with the shortcut field selected
    app.connect("activate", activate)
    return app.run(sys.argv[:1])
