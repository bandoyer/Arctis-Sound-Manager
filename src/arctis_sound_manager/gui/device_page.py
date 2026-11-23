# Copyright (C) 2026 loteran
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Device / Settings page — ArctisSonar GUI visual style.
Matches the ref_settingsPage.png design.
"""
import logging
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from arctis_sound_manager.gui.qt_widgets.no_wheel_combo import NoWheelComboBox
from arctis_sound_manager.gui.qt_widgets.q_dual_state import QDualState
from arctis_sound_manager.i18n import I18n
from arctis_sound_manager.gui.components import (
    DividerLine,
    SectionTitle,
)
from arctis_sound_manager.gui.headset_cards import SettingsCard
from arctis_sound_manager.gui.settings_widget import (
    _COMPACT_LABEL_WIDTH,
    QSettingsWidget,
    status_key_names,
)
from arctis_sound_manager.autostart import active_backend_name, autostart_enabled, set_autostart
log = logging.getLogger(__name__)

import arctis_sound_manager.gui.theme as _theme
from arctis_sound_manager.gui.theme import (
    ACCENT,
    BG_BUTTON,
    BG_BUTTON_HOVER,
    BG_MAIN,
    BORDER,
    TEXT_PRIMARY,
    THEMES,
    all_theme_labels, get_theme, get_theme_label, is_builtin,
    reload_user_themes,
    delete_user_theme,
)

_SERVICE = "arctis-manager.service"
_GUI_SERVICE = "arctis-gui.service"


def _autostart_enabled() -> bool:
    from arctis_sound_manager import service_control as sc
    return sc.is_enabled("arctis-manager")


_GUI_SERVICE_TEMPLATE = """\
[Unit]
Description=Arctis Sound Manager — System Tray
After=graphical-session.target arctis-manager.service
Wants=arctis-manager.service

[Service]
Type=simple
ExecStart={asm_gui} --systray
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
"""


def _ensure_gui_service() -> Path | None:
    """Create ~/.config/systemd/user/arctis-gui.service if missing. Returns path or None."""
    gui_service_path = Path.home() / ".config" / "systemd" / "user" / _GUI_SERVICE
    if gui_service_path.exists():
        return gui_service_path
    asm_gui = shutil.which("asm-gui")
    if not asm_gui:
        return None
    gui_service_path.parent.mkdir(parents=True, exist_ok=True)
    gui_service_path.write_text(_GUI_SERVICE_TEMPLATE.format(asm_gui=asm_gui))
    from arctis_sound_manager import service_control as sc
    sc.daemon_reload()
    return gui_service_path


def _set_autostart(enabled: bool) -> None:
    from arctis_sound_manager import service_control as sc
    from arctis_sound_manager.init_system import (
        detect_init, write_xdg_autostart, remove_xdg_autostart,
    )

    if enabled:
        sc.enable("arctis-manager")
    else:
        sc.disable("arctis-manager")

    # dinit has no GUI service — autostart is handled via XDG desktop file.
    if detect_init() == "dinit":
        if enabled:
            write_xdg_autostart()
        else:
            remove_xdg_autostart()
        return

    # systemd: enable/disable the GUI tray service too.
    gui_service_path = _ensure_gui_service() if enabled else (
        Path.home() / ".config" / "systemd" / "user" / _GUI_SERVICE
    )
    if gui_service_path and gui_service_path.exists():
        if enabled:
            sc.enable("arctis-gui")
        else:
            sc.disable("arctis-gui")


def _styled_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    btn.setFixedHeight(44)
    btn.setStyleSheet(
        f"""
        QPushButton {{
            background-color: {_theme.c('BG_BUTTON')};
            color: {_theme.c('TEXT_PRIMARY')};
            border: none;
            border-radius: 6px;
            font-size: 11pt;
            padding: 0 16px;
        }}
        QPushButton:hover {{
            background-color: {_theme.c('BG_BUTTON_HOVER')};
        }}
        """
    )
    return btn


# The "general" D-Bus section, split by topic. Keys not listed in any of these
# stay in the General group itself.
_INTERFACE_KEYS = ('systray_show_battery', 'systray_chatmix_osd', 'systray_master_osd', 'systray_icon_color')
_AUDIO_KEYS = (
    'redirect_audio_on_connect', 'redirect_audio_on_connect_channel',
    'redirect_audio_on_disconnect', 'redirect_audio_on_disconnect_device',
    'external_output_device', 'hrir_id', 'pipewire_quantum',
)
_MICRO_KEYS = ('micro_input_source', 'micro_alt_source', 'micro_autoswitch')
_GENERIC_KEYS = ('usb_transport', 'auto_usb_reset', 'generic_device_mode', 'generic_output_device', 'generic_input_device')


def _settings_panel_qss() -> str:
    return f"""
        QWidget {{ background-color: {_theme.c('BG_MAIN')}; color: {_theme.c('TEXT_PRIMARY')}; }}
        QLabel {{ background-color: transparent; color: {_theme.c('TEXT_PRIMARY')}; font-size: 11pt; }}
    """


class DevicePage(QWidget):
    """
    Settings page with:
    - Title "Arctis Sound Manager" bold + subtitle "Device Settings"
    - Theme selector chips
    - "General Settings" section title (gray ~20pt)
    - Settings form rows (labels + controls)
    - Horizontal divider
    - "Devices" section with a card showing connected headset
    """

    sig_theme_changed = Signal(str)
    sig_theme_create = Signal()
    sig_theme_edit = Signal(str)   # theme_id

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {BG_MAIN};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Scrollable content area ───────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background-color: {_theme.c('BG_MAIN')}; border: none; }}"
        )
        self._scroll = scroll

        content = QWidget()
        content.setStyleSheet(f"background-color: {_theme.c('BG_MAIN')};")
        self._content = content
        content_layout = QVBoxLayout(content)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        content_layout.setContentsMargins(28, 20, 28, 24)
        content_layout.setSpacing(8)
        self._settings_groups: list[QSettingsWidget] = []
        self._cards: list[SettingsCard] = []

        content_layout.addWidget(SectionTitle(I18n.translate("ui", "general_settings")))
        content_layout.addSpacing(4)

        # Every group is a card, the way the Headset page is laid out: a title,
        # then label/control rows sized to their content. The page used to be
        # one long column of oversized controls, wider than the window.

        # ── General ───────────────────────────────────────────────────────────
        general = self._add_card(content_layout, "settings_group_general")

        self._lang_combo = NoWheelComboBox()
        self._lang_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._lang_combo.setFixedHeight(30)
        self._lang_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {BG_BUTTON};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 10pt;
                min-width: 120px;
            }}
            QComboBox:hover {{
                background-color: {BG_BUTTON_HOVER};
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background-color: {BG_BUTTON};
                color: {TEXT_PRIMARY};
                selection-background-color: {ACCENT};
                selection-color: #ffffff;
                border: 1px solid {BORDER};
            }}
        """)
        self._lang_codes: list[str] = []
        for code, display in I18n.available_languages():
            self._lang_combo.addItem(display)
            self._lang_codes.append(code)
        self._lang_combo.currentIndexChanged.connect(self._on_lang_combo)
        self._refresh_lang_combo()
        self._add_row(general, I18n.translate("ui", "language"), self._lang_combo)

        self._startup_toggle = QDualState(
            off_text=I18n.translate("settings_values", "off"),
            on_text=I18n.translate("settings_values", "on"),
            init_state="right" if autostart_enabled() else "left",
            accent=True,
        )
        self._startup_toggle.setToolTip(f"Autostart via: {active_backend_name()}")
        self._startup_toggle.checkStateChanged.connect(self._on_autostart_toggled)
        self._add_row(general, I18n.translate("ui", "launch_at_startup"), self._startup_toggle)

        from arctis_sound_manager.telemetry import get_consent, set_consent

        consent = get_consent()
        self._telemetry_toggle = QDualState(
            off_text=I18n.translate("settings_values", "off"),
            on_text=I18n.translate("settings_values", "on"),
            init_state="right" if consent is True else "left",
            accent=True,
        )
        self._telemetry_toggle.checkStateChanged.connect(
            lambda state: set_consent(state == Qt.CheckState.Checked)
        )
        self._add_row(general, "Telemetry — share anonymous usage data", self._telemetry_toggle)

        # Whatever no other group claims lands here, so a setting added to
        # GeneralSettings shows up even before it is given a group.
        self._general_widget = self._add_settings_group(
            general, None, exclude=_INTERFACE_KEYS + _AUDIO_KEYS + _MICRO_KEYS + _GENERIC_KEYS)

        # ── Interface & tray: theme, then the tray settings ───────────────────
        interface = self._add_card(content_layout, "settings_group_interface")

        self._theme_combo = NoWheelComboBox()
        self._theme_combo.setMinimumWidth(200)
        self._theme_combo.setMaximumWidth(320)
        self._add_row(interface, I18n.translate("ui", "theme"), self._theme_combo)

        self._theme_create_btn = QPushButton(I18n.translate("ui", "theme_create"))
        self._theme_edit_btn = QPushButton(I18n.translate("ui", "theme_edit"))
        self._theme_delete_btn = QPushButton(I18n.translate("ui", "theme_delete"))
        self._theme_export_btn = QPushButton(I18n.translate("ui", "theme_export"))
        self._theme_import_btn = QPushButton(I18n.translate("ui", "theme_import"))
        theme_buttons = QWidget()
        theme_btn_row = QHBoxLayout(theme_buttons)
        theme_btn_row.setContentsMargins(0, 0, 0, 0)
        theme_btn_row.setSpacing(4)
        self._theme_buttons = (self._theme_create_btn, self._theme_edit_btn,
                               self._theme_delete_btn, self._theme_export_btn,
                               self._theme_import_btn)
        for btn in self._theme_buttons:
            theme_btn_row.addWidget(btn)
        self._add_row(interface, "", theme_buttons)

        # Connexions des widgets de thème
        self._theme_combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        self._theme_create_btn.clicked.connect(self.sig_theme_create.emit)
        self._theme_edit_btn.clicked.connect(lambda: self.sig_theme_edit.emit(self._theme_combo.currentData() or ""))
        self._theme_delete_btn.clicked.connect(self._on_theme_delete)
        self._theme_export_btn.clicked.connect(self._on_theme_export)
        self._theme_import_btn.clicked.connect(self._on_theme_import)

        self._add_settings_group(interface, _INTERFACE_KEYS)

        # The headset's own settings (sidetone, mic volume, noise cancelling…)
        # live on the Headset page, next to the headset they change. This page
        # keeps what belongs to the app.
        self._add_settings_group(self._add_card(content_layout, "settings_group_audio"), _AUDIO_KEYS)
        self._add_settings_group(self._add_card(content_layout, "settings_group_micro"), _MICRO_KEYS)
        self._add_settings_group(self._add_card(content_layout, "settings_group_generic"), _GENERIC_KEYS)

        content_layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

        # Populate theme combo with the currently-active theme.
        from arctis_sound_manager.settings import GeneralSettings
        current_theme = GeneralSettings.read_from_file().theme
        self.refresh_theme_combo(current_theme)

        # Apply the currently-active theme on first paint.
        self.apply_theme()

    def _add_card(self, layout: QVBoxLayout, title_key: str) -> QVBoxLayout:
        """A titled card on the page; returns the layout its rows go in."""
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(3)
        card = SettingsCard(I18n.translate("ui", title_key), body, self._content)
        layout.addWidget(card)
        self._cards.append(card)
        return body_layout

    def _add_row(self, layout: QVBoxLayout, label: str, control: QWidget) -> QWidget:
        """A label/control row lined up with the rows QSettingsWidget builds."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 4, 0, 4)
        text = QLabel(label)
        text.setFixedWidth(_COMPACT_LABEL_WIDTH)
        text.setWordWrap(True)
        row_layout.addWidget(text)
        row_layout.addWidget(control)
        row_layout.addStretch(1)
        layout.addWidget(row)
        return row

    def _add_settings_group(self, layout: QVBoxLayout, keys, exclude=()) -> QSettingsWidget:
        """One panel of "general" settings, inside a card."""
        widget = QSettingsWidget(None, None, "general", keys=keys, exclude=exclude, compact=True)
        layout.addWidget(widget)
        self._settings_groups.append(widget)
        return widget

    # ── Theme propagation ─────────────────────────────────────────────────────

    def apply_theme(self, t=None) -> None:
        """Restyle the device/settings page for the current active theme."""
        self.setStyleSheet(f"background-color: {_theme.c('BG_MAIN')};")
        self._scroll.setStyleSheet(f"QScrollArea {{ background-color: {_theme.c('BG_MAIN')}; border: none; }}")
        self._content.setStyleSheet(f"background-color: {_theme.c('BG_MAIN')};")

        # Cards restyle their own contents, settings panels included.
        for card in getattr(self, "_cards", []):
            card.apply_theme()
        for widget in getattr(self, "_settings_groups", []):
            widget.apply_theme()
        for btn in getattr(self, "_theme_buttons", ()):
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {_theme.c('BG_BUTTON')};
                    color: {_theme.c('TEXT_PRIMARY')};
                    border: 1px solid {_theme.c('BG_BUTTON_HOVER')};
                    border-radius: 6px;
                    padding: 4px 10px;
                    font-size: 9pt;
                }}
                QPushButton:hover {{ background-color: {_theme.c('BG_BUTTON_HOVER')}; }}
                QPushButton:disabled {{ color: {_theme.c('TEXT_SECONDARY')}; }}
            """)

        # Language combo
        if hasattr(self, "_lang_combo"):
            self._lang_combo.setStyleSheet(f"""
                QComboBox {{
                    background-color: {_theme.c('BG_BUTTON')};
                    color: {_theme.c('TEXT_PRIMARY')};
                    border: 1px solid {_theme.c('BORDER')};
                    border-radius: 6px;
                    padding: 4px 10px;
                    font-size: 10pt;
                    min-width: 120px;
                }}
                QComboBox:hover {{ background-color: {_theme.c('BG_BUTTON_HOVER')}; }}
                QComboBox::drop-down {{ border: none; }}
                QComboBox QAbstractItemView {{
                    background-color: {_theme.c('BG_BUTTON')};
                    color: {_theme.c('TEXT_PRIMARY')};
                    selection-background-color: {_theme.c('ACCENT')};
                    selection-color: #ffffff;
                    border: 1px solid {_theme.c('BORDER')};
                }}
            """)

        # Theme combo and buttons state are set via refresh_theme_combo / _update_theme_buttons_state.

    # ── Theme selector ────────────────────────────────────────────────────────

    def refresh_theme_combo(self, selected: str | None = None) -> None:
        self._theme_combo.blockSignals(True)
        self._theme_combo.clear()
        reload_user_themes()
        labels = all_theme_labels()
        for tid, label in labels.items():
            self._theme_combo.addItem(label, tid)
        if selected:
            idx = self._theme_combo.findData(selected)
            if idx >= 0:
                self._theme_combo.setCurrentIndex(idx)
        self._theme_combo.blockSignals(False)
        self._update_theme_buttons_state()

    def _update_theme_buttons_state(self) -> None:
        tid = self._theme_combo.currentData()
        user_theme = tid is not None and not is_builtin(tid)
        self._theme_edit_btn.setEnabled(user_theme)
        self._theme_delete_btn.setEnabled(user_theme)
        self._theme_export_btn.setEnabled(tid is not None)

    def _on_theme_combo_changed(self, index: int) -> None:
        tid = self._theme_combo.itemData(index)
        if tid:
            self._update_theme_buttons_state()
            self.sig_theme_changed.emit(tid)

    def _on_theme_delete(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        tid = self._theme_combo.currentData()
        if not tid or is_builtin(tid):
            return
        name = get_theme_label(tid)
        msg = I18n.translate("ui", "theme_delete_confirm").format(name=name)
        reply = QMessageBox.question(self, "", msg,
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            delete_user_theme(tid)
            self.refresh_theme_combo("steelseries")
            self.sig_theme_changed.emit("steelseries")

    def _on_theme_export(self) -> None:
        from arctis_sound_manager.gui.theme_export_dialog import ThemeExportDialog
        tid = self._theme_combo.currentData()
        if not tid:
            return
        ThemeExportDialog(get_theme_label(tid), dict(get_theme(tid)), self).exec()

    def _on_theme_import(self) -> None:
        from arctis_sound_manager.gui.theme_import_dialog import ThemeImportDialog
        dlg = ThemeImportDialog(self)
        if dlg.exec() and dlg.imported_theme_id:
            self.refresh_theme_combo(dlg.imported_theme_id)
            self.sig_theme_changed.emit(dlg.imported_theme_id)

    # ── Signal forwarding ─────────────────────────────────────────────────────

    @Slot(object)
    def update_status(self, status: dict):
        """Tell the settings widgets which live status keys the connected
        device is actually reporting.

        This is how a global BUTTON_GROUP setting like ``micro_autoswitch``
        (settings.py) knows whether an option backed by e.g. ``mic_status``
        can do anything on the currently active device profile — see
        ``option_requires_status`` there and
        ``QSettingsWidget._option_available``.
        """
        keys = status_key_names(status)
        for widget in self._settings_groups:
            widget.set_available_status_keys(keys)

    @Slot(object)
    def update_settings(self, settings: dict):
        for widget in self._settings_groups:
            widget.update_settings(settings)

    # ── Language ───────────────────────────────────────────────────────────────

    def _refresh_lang_combo(self):
        current = I18n.current_lang()
        if current in self._lang_codes:
            self._lang_combo.blockSignals(True)
            self._lang_combo.setCurrentIndex(self._lang_codes.index(current))
            self._lang_combo.blockSignals(False)

    @Slot()
    def rebuild_lang_combo(self) -> None:
        """Repopulate the combo after LangUpdateWorker downloads new files."""
        self._lang_combo.blockSignals(True)
        self._lang_combo.clear()
        self._lang_codes.clear()
        for code, display in I18n.available_languages():
            self._lang_combo.addItem(display)
            self._lang_codes.append(code)
        self._refresh_lang_combo()
        self._lang_combo.blockSignals(False)

    def _on_autostart_toggled(self, state: Qt.CheckState) -> None:
        set_autostart(state == Qt.CheckState.Checked)

    # ── Clips: install / uninstall ────────────────────────────────────────────
    #
    # This was a switch that opened the general dependency dialog when anything
    # was missing. That dialog lists *every* failing check in ASM, and one of
    # them — "pipewire-pulse running" — is remediated by restarting PipeWire and
    # pipewire-pulse. Pressing its Install-all button therefore tore down the
    # audio graph: the headset's card came back with its profile off, and
    # WirePlumber persisted that, so switching Clips on took the user's sound
    # away and kept it away. Reported as "the Clips button breaks it".
    #
    # Nothing here reaches that dialog any more. Clips owns its own packages,
    # installs and removes only those, and cannot touch a service.

    def _on_lang_combo(self, index: int):
        if index < 0 or index >= len(self._lang_codes):
            return
        code = self._lang_codes[index]
        if code == I18n.current_lang():
            return
        I18n.get_instance().set_language(code)
        msg = QMessageBox(self)
        msg.setWindowTitle("Language / Langue / Idioma")
        msg.setText(I18n.translate("ui", "language_changed"))
        msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()
