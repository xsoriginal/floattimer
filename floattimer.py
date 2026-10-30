"""FloatTimer: compact, customisable, always-on-top countdown for Windows."""
import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPoint, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap, QPen
from PySide6.QtWidgets import (
    QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox,
    QColorDialog, QFontComboBox, QDialogButtonBox, QSystemTrayIcon, QMenu,
    QMessageBox, QScrollArea, QFrame
)

DEFAULT = {
    "presets": [1, 3, 5, 10, 15], "font": "Segoe UI", "font_size": 100,
    "text_color": "#FFFFFF", "background_color": "#101820",
    "accent_color": "#43E5AD", "opacity": 94, "always_on_top": True,
    "sound": True, "x": None, "y": None,
}


def settings_file():
    import os
    root = Path(os.getenv("APPDATA", str(Path.home()))) / "FloatTimer"
    root.mkdir(parents=True, exist_ok=True)
    return root / "settings.json"


def load_settings():
    result = dict(DEFAULT)
    try:
        stored = json.loads(settings_file().read_text(encoding="utf-8"))
        if isinstance(stored, dict):
            result.update({k: v for k, v in stored.items() if k in DEFAULT})
    except (OSError, ValueError, TypeError):
        pass
    result["presets"] = [int(x) for x in result["presets"] if 0 < int(x) <= 999][:12] or [5]
    return result


def save_settings(settings):
    settings_file().write_text(json.dumps(settings, indent=2), encoding="utf-8")


def button(label, callback, name="control"):
    b = QPushButton(label)
    b.setObjectName(name)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.clicked.connect(callback)
    return b


class DragBar(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.origin = None
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.parent_window.move(event.globalPosition().toPoint() - self.origin)

    def mouseReleaseEvent(self, event):
        self.origin = None
        self.parent_window.store_position()


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FloatTimer settings")
        self.resize(490, 560)
        self.values = dict(settings)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(QLabel("Presets (minutes, one per line)"))
        self.presets = QLineEdit(", ".join(map(str, settings["presets"])))
        self.presets.setPlaceholderText("1, 3, 5, 10, 15")
        layout.addWidget(self.presets)
        layout.addWidget(QLabel("Separate preset durations with commas. Maximum 12."))
        form = QFormLayout()
        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont(settings["font"]))
        form.addRow("Countdown font", self.font)
        self.font_size = QSpinBox()
        self.font_size.setRange(36, 220)
        self.font_size.setValue(settings["font_size"])
        form.addRow("Number size", self.font_size)
        self.colors = {}
        for key, label in (("text_color", "Text colour"), ("background_color", "Background colour"), ("accent_color", "Accent colour")):
            b = QPushButton(settings[key])
            self.colors[key] = b
            b.clicked.connect(lambda _=False, k=key: self.choose_color(k))
            form.addRow(label, b)
        self.opacity = QSpinBox()
        self.opacity.setRange(20, 100)
        self.opacity.setSuffix("%")
        self.opacity.setValue(settings["opacity"])
        form.addRow("Background opacity", self.opacity)
        self.top = QCheckBox("Keep timer above other windows")
        self.top.setChecked(settings["always_on_top"])
        form.addRow(self.top)
        self.sound = QCheckBox("Play alert when finished")
        self.sound.setChecked(settings["sound"])
        form.addRow(self.sound)
        layout.addLayout(form)
        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def choose_color(self, key):
        color = QColorDialog.getColor(QColor(self.values[key]), self, "Choose colour")
        if color.isValid():
            self.values[key] = color.name()
            self.colors[key].setText(color.name())

    def accept(self):
        try:
            entries = [int(x.strip()) for x in self.presets.text().split(",") if x.strip()]
            if not entries or len(entries) > 12 or any(x < 1 or x > 999 for x in entries):
                raise ValueError()
        except ValueError:
            QMessageBox.warning(self, "Invalid presets", "Enter 1–12 comma-separated whole numbers between 1 and 999.")
            return
        self.values.update(presets=entries, font=self.font.currentFont().family(),
                           font_size=self.font_size.value(), opacity=self.opacity.value(),
                           always_on_top=self.top.isChecked(), sound=self.sound.isChecked())
        super().accept()


class FloatTimer(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.duration = self.settings["presets"][0] * 60
        self.remaining = float(self.duration)
        self.deadline = None
        self.running = False
        self.finished = False
        self.docked = False
        self.previous_position = None
        self.setWindowTitle("FloatTimer")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.build_ui()
        self.make_tray()
        self.apply_settings()
        if self.settings["x"] is not None and self.settings["y"] is not None:
            self.move(int(self.settings["x"]), int(self.settings["y"]))
        self.clock = QTimer(self)
        self.clock.setInterval(80)
        self.clock.timeout.connect(self.tick)
        self.clock.start()
        self.refresh()

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.panel = QFrame()
        self.panel.setObjectName("panel")
        root.addWidget(self.panel)
        body = QVBoxLayout(self.panel)
        body.setContentsMargins(14, 8, 14, 12)
        body.setSpacing(4)
        bar = DragBar(self)
        bar.setFixedHeight(32)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(5, 0, 0, 0)
        drag_label = QLabel("⠿  FloatTimer")
        drag_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bar_layout.addWidget(drag_label)
        bar_layout.addStretch()
        self.dock_button = button("⇧", self.toggle_dock, "topButton")
        self.dock_button.setToolTip("Show time only at top centre of screen")
        bar_layout.addWidget(self.dock_button)
        bar_layout.addWidget(button("⚙", self.open_settings, "topButton"))
        bar_layout.addWidget(button("—", self.hide, "topButton"))
        bar_layout.addWidget(button("×", self.hide, "topButton"))
        body.addWidget(bar)
        main = QHBoxLayout()
        main.setSpacing(10)
        left = QVBoxLayout()
        self.display = QPushButton("05:00")
        self.display.setObjectName("display")
        self.display.setToolTip("Click to enter a custom duration")
        self.display.clicked.connect(self.edit_time)
        left.addWidget(self.display, stretch=1)
        controls = QHBoxLayout()
        self.play_button = button("▶ Start", self.toggle, "play")
        self.reset_button = button("↺ Reset", self.reset)
        controls.addStretch()
        controls.addWidget(self.play_button)
        controls.addWidget(self.reset_button)
        controls.addStretch()
        left.addLayout(controls)
        main.addLayout(left, stretch=1)
        self.preset_box = QVBoxLayout()
        self.preset_box.setSpacing(4)
        main.addLayout(self.preset_box)
        body.addLayout(main)
        self.main_controls = QWidget()
        # The complete interface is hidden in dock mode, leaving only a clickable time.
        self.dock_display = QPushButton("05:00")
        self.dock_display.setObjectName("dockDisplay")
        self.dock_display.setToolTip("Click to restore the full timer")
        self.dock_display.clicked.connect(self.toggle_dock)
        self.dock_display.hide()
        root.addWidget(self.dock_display)
        self.dock_display.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.dock_display.customContextMenuRequested.connect(lambda _: self.toggle_dock())

    def make_tray(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#43E5AD"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(4, 4, 56, 56)
        painter.setPen(QPen(QColor("#101820"), 5))
        painter.drawLine(32, 13, 32, 32)
        painter.drawLine(32, 32, 45, 39)
        painter.end()
        self.tray = QSystemTrayIcon(QIcon(pixmap), self)
        menu = QMenu()
        menu.addAction("Show FloatTimer", self.show_normal)
        menu.addAction("Dock / restore", self.toggle_dock)
        menu.addAction("Start / pause", self.toggle)
        menu.addAction("Reset", self.reset)
        menu.addAction("Settings", self.open_settings)
        menu.addSeparator()
        menu.addAction("Quit", QApplication.instance().quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_normal() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def apply_settings(self):
        s = self.settings
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if s["always_on_top"]:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        bg = QColor(s["background_color"])
        bg.setAlphaF(s["opacity"] / 100)
        rgba = f"rgba({bg.red()}, {bg.green()}, {bg.blue()}, {bg.alpha()})"
        self.panel.setStyleSheet(f"""
            QFrame#panel {{ background: {rgba}; border-radius: 18px; }}
            QLabel {{ color: {s['text_color']}; }}
            QPushButton {{ background: rgba(130,150,175,45); color: {s['text_color']};
                          border: none; border-radius: 9px; padding: 7px 11px; }}
            QPushButton:hover {{ background: rgba(130,150,175,95); }}
            QPushButton#dockDisplay {{ background: {rgba}; color: {s["text_color"]}; border-radius: 12px; font-family: '{s["font"]}'; font-size: {s["font_size"]}px; font-weight: 700; padding: 2px 12px; }}
            QPushButton#display {{ background: transparent; font-family: '{s['font']}';
                          font-size: {s['font_size']}px; font-weight: 700; padding: 0px; }}
            QPushButton#play {{ background: {s['accent_color']}; color: #101820; font-weight: 700; }}
            QPushButton#presetSelected {{ background: {s['accent_color']}; color: #101820; font-weight: 700; }}
            QPushButton#topButton {{ background: transparent; font-size: 18px; padding: 3px 8px; }}
        """)
        self.build_presets()
        self.adjustSize()
        if self.docked:
            self.position_docked()
        if was_visible:
            self.show()

    def build_presets(self):
        while self.preset_box.count():
            item = self.preset_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.preset_buttons = []
        for minutes in self.settings["presets"]:
            b = button(f"{minutes}m", lambda _=False, m=minutes: self.select_preset(m), "preset")
            b.setMinimumWidth(57)
            self.preset_box.addWidget(b)
            self.preset_buttons.append((minutes, b))
        self.preset_box.addStretch()
        self.refresh()

    def select_preset(self, minutes):
        self.running = False
        self.deadline = None
        self.finished = False
        self.duration = minutes * 60
        self.remaining = float(self.duration)
        self.refresh()

    def edit_time(self):
        from PySide6.QtWidgets import QInputDialog
        value, ok = QInputDialog.getText(self, "Custom countdown", "Enter MM:SS or minutes:", text=self.format_time())
        if not ok:
            return
        try:
            if ":" in value:
                m, sec = map(int, value.strip().split(":"))
                if sec < 0 or sec > 59:
                    raise ValueError()
                duration = m * 60 + sec
            else:
                duration = int(value.strip()) * 60
            if duration < 1 or duration > 359999:
                raise ValueError()
        except ValueError:
            QMessageBox.warning(self, "Invalid time", "Enter a positive number of minutes or MM:SS (up to 99:59:59).")
            return
        self.running = False
        self.deadline = None
        self.finished = False
        self.duration = duration
        self.remaining = float(duration)
        self.refresh()

    def format_time(self):
        seconds = max(0, int(self.remaining + 0.999))
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        return f"{hours:02}:{minutes:02}:{secs:02}" if hours else f"{minutes:02}:{secs:02}"

    def toggle(self):
        if self.running:
            self.remaining = max(0.0, self.deadline - time.monotonic())
            self.running = False
            self.deadline = None
        else:
            if self.remaining <= 0:
                self.remaining = float(self.duration)
                self.finished = False
            self.deadline = time.monotonic() + self.remaining
            self.running = True
        self.refresh()

    def reset(self):
        self.running = False
        self.deadline = None
        self.remaining = float(self.duration)
        self.finished = False
        self.refresh()

    def tick(self):
        if not self.running:
            return
        self.remaining = max(0.0, self.deadline - time.monotonic())
        if self.remaining <= 0:
            self.running = False
            self.deadline = None
            self.finished = True
            if self.settings["sound"]:
                QApplication.beep()
            if self.tray.isVisible():
                self.tray.showMessage("FloatTimer", "Time's up!", QSystemTrayIcon.MessageIcon.Information, 4000)
        self.refresh()

    def refresh(self):
        if not hasattr(self, "display"):
            return
        label = self.format_time()
        if self.display.text() != label:
            self.display.setText(label)
        self.dock_display.setText(label)
        self.play_button.setText("Ⅱ Pause" if self.running else "▶ Start")
        for minutes, b in getattr(self, "preset_buttons", []):
            b.setObjectName("presetSelected" if self.duration == minutes * 60 else "preset")
            b.style().unpolish(b)
            b.style().polish(b)
        self.setWindowTitle(f"{label} · FloatTimer")

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings = dialog.values
            save_settings(self.settings)
            self.apply_settings()

    def position_docked(self):
        # Use the screen containing the original window (not necessarily primary).
        screen = QApplication.screenAt(self.previous_position) if self.previous_position else None
        screen = screen or self.screen() or QApplication.primaryScreen()
        rect = screen.availableGeometry()
        self.adjustSize()
        self.move(rect.x() + (rect.width() - self.width()) // 2, rect.y() + 8)

    def toggle_dock(self):
        if not self.docked:
            self.previous_position = self.pos()
            self.docked = True
            self.panel.hide()
            self.dock_display.show()
            self.adjustSize()
            self.position_docked()
        else:
            self.docked = False
            self.dock_display.hide()
            self.panel.show()
            self.adjustSize()
            if self.previous_position is not None:
                self.move(self.previous_position)
            self.store_position()
        self.refresh()

    def store_position(self):
        if self.docked:
            return
        self.settings["x"] = self.x()
        self.settings["y"] = self.y()
        save_settings(self.settings)

    def show_normal(self):
        if self.docked:
            self.toggle_dock()
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        self.store_position()
        if self.tray.isVisible():
            event.ignore()
            self.hide()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    timer = FloatTimer()
    timer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
