"""FloatTimer: compact, customisable, always-on-top countdown for Windows."""
import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPoint, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap, QPen, QBrush, QFontMetrics, QPainterPath
from PySide6.QtWidgets import (
    QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox,
    QColorDialog, QFontComboBox, QDialogButtonBox, QSystemTrayIcon, QMenu,
    QMessageBox, QScrollArea, QFrame, QStackedWidget
)

DEFAULT = {
    "presets": [1, 3, 5, 10, 15], "font": "Segoe UI", "font_size": 100,
    "text_color": "#FFFFFF", "background_color": "#101820",
    "accent_color": "#43E5AD", "opacity": 94, "always_on_top": True,
    "sound": True, "x": None, "y": None, "width": None, "height": None,
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


class IconButton(QPushButton):
    """Crisp, scalable icons drawn directly with Qt rather than font glyphs."""
    def __init__(self, kind, callback, name="control", size=42):
        super().__init__()
        self.kind = kind
        self.setObjectName(name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(size, size)
        self.clicked.connect(callback)
        if kind == "reset":
            # Native Qt text rendering: avoids the missing R caused by painting
            # a glyph over the button's style-engine rendering.
            self.setText("R")
            font = QFont("Arial", 24, QFont.Weight.Bold)
            font.setPixelSize(27)
            self.setFont(font)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.kind == "reset":
            return  # QPushButton renders its real text label reliably.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        scale = min(self.width(), self.height()) / 42
        painter.scale(scale, scale)
        window = self.window()
        color = QColor(getattr(window, "settings", {}).get("text_color", "#FFFFFF"))
        pen = QPen(color, 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        k = self.kind
        if k == "play":
            from PySide6.QtGui import QPolygonF
            from PySide6.QtCore import QPointF
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(QPolygonF([QPointF(-6,-11), QPointF(12,0), QPointF(-6,11)]))
        elif k == "pause":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRect(-9,-11,6,22)
            painter.drawRect(3,-11,6,22)
        elif k == "reset":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            letter = QFont("Arial", 28, QFont.Weight.Bold)
            letter.setPixelSize(28)
            painter.setFont(letter)
            from PySide6.QtCore import QRectF
            painter.drawText(QRectF(-20, -20, 40, 40), Qt.AlignmentFlag.AlignCenter, "R")
        elif k == "minus":
            painter.drawLine(-10,0,10,0)
        elif k == "plus":
            painter.drawLine(-10,0,10,0)
            painter.drawLine(0,-10,0,10)
        elif k == "dock":
            from PySide6.QtGui import QPolygonF
            from PySide6.QtCore import QPointF
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPolygon(QPolygonF([QPointF(0,-15),QPointF(-13,-2),QPointF(-5,-2),QPointF(-5,9),QPointF(5,9),QPointF(5,-2),QPointF(13,-2)]))
            painter.drawRect(-13,13,26,3)
        elif k == "settings":
            # A single even-odd fill path makes the hole truly transparent,
            # irrespective of the panel's background colour or opacity.
            from PySide6.QtCore import QRectF
            from PySide6.QtGui import QPainterPath, QPolygonF
            from PySide6.QtCore import QPointF
            import math
            path = QPainterPath()
            teeth = []
            for i in range(32):
                angle = 2 * math.pi * i / 32 - math.pi / 2
                radius = 14 if i % 4 in (0, 1) else 10.5
                teeth.append(QPointF(radius * math.cos(angle), radius * math.sin(angle)))
            path.addPolygon(QPolygonF(teeth))
            path.closeSubpath()
            path.addEllipse(QRectF(-4.5, -4.5, 9, 9))
            path.setFillRule(Qt.FillRule.OddEvenFill)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPath(path)
        elif k == "minimize":
            painter.drawLine(-10,6,10,6)
        elif k == "close":
            painter.drawLine(-9,-9,9,9)
            painter.drawLine(9,-9,-9,9)
        painter.end()


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


def show_front_warning(parent, title, message):
    """Application-modal, explicitly foregrounded alert above an always-on-top timer."""
    alert = QMessageBox(QMessageBox.Icon.Warning, title, message,
                        QMessageBox.StandardButton.Ok, parent)
    alert.setWindowFlags(alert.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    alert.setWindowModality(Qt.WindowModality.ApplicationModal)
    alert.show()
    alert.raise_()
    alert.activateWindow()
    return alert.exec()


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
            show_front_warning(self, "Invalid presets", "Enter 1–12 comma-separated whole numbers between 1 and 999.")
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
        self.previous_size = None
        self.setWindowTitle("FloatTimer")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.build_ui()
        self.setFixedSize(420, max(190, 58 + len(self.settings["presets"]) * 47))
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
        root.setContentsMargins(9, 9, 9, 9)
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
        bar_layout.addStretch()
        self.dock_button = IconButton("dock", self.toggle_dock, "topButton", 38)
        self.dock_button.setToolTip("Dock at top centre (click time to restore)")
        bar_layout.addWidget(self.dock_button)
        settings_button = IconButton("settings", self.open_settings, "topButton", 32)
        self.settings_button = settings_button
        settings_button.setToolTip("Settings")
        bar_layout.addWidget(settings_button)
        minimize_button = IconButton("minimize", self.hide, "topButton", 32)
        self.minimize_button = minimize_button
        minimize_button.setToolTip("Minimise to tray")
        bar_layout.addWidget(minimize_button)
        close_button = IconButton("close", self.quit_app, "topButton", 32)
        self.close_button = close_button
        close_button.setToolTip("Exit FloatTimer")
        bar_layout.addWidget(close_button)
        body.addWidget(bar)
        main = QHBoxLayout()
        main.setSpacing(10)
        left = QVBoxLayout()
        self.display_stack = QStackedWidget()
        self.display_stack.setMinimumWidth(210)
        self.display = QPushButton("05:00")
        self.display.setObjectName("display")
        self.display.setToolTip("Click to enter four digits as MMSS (e.g. 0530)")
        self.display.clicked.connect(self.edit_time)
        self.display_stack.addWidget(self.display)
        self.time_input = QLineEdit()
        self.time_input.setObjectName("timeInput")
        self.time_input.setInputMask("9999")
        self.time_input.setMaxLength(4)
        self.time_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_input.setToolTip("Type four digits MMSS, then Enter")
        self.time_input.returnPressed.connect(self.commit_time)
        self.time_input.editingFinished.connect(self.commit_time)
        self.display_stack.addWidget(self.time_input)
        left.addWidget(self.display_stack, stretch=1)
        controls = QHBoxLayout()
        controls.setSpacing(7)
        self.minus_button = IconButton("minus", lambda: self.adjust_seconds(-30))
        self.minus_button.setToolTip("Subtract 30 seconds")
        self.play_button = IconButton("play", self.toggle, "play", 50)
        self.play_button.setToolTip("Start / pause")
        self.reset_button = IconButton("reset", self.reset)
        self.reset_button.setToolTip("Reset")
        self.plus_button = IconButton("plus", lambda: self.adjust_seconds(30))
        self.plus_button.setToolTip("Add 30 seconds")
        controls.addStretch()
        for control in (self.minus_button, self.play_button, self.reset_button, self.plus_button):
            controls.addWidget(control)
        controls.addStretch()
        left.addLayout(controls)
        main.addLayout(left, stretch=1)
        self.preset_box = QVBoxLayout()
        self.preset_box.setSpacing(4)
        main.addLayout(self.preset_box)
        body.addLayout(main)
        # The complete interface is hidden in dock mode, leaving only a clickable time.
        self.dock_display = QPushButton("05:00")
        self.dock_display.setObjectName("dockDisplay")
        self.dock_display.setToolTip("Click to restore the full timer")
        self.dock_display.clicked.connect(self.toggle_dock)
        self.dock_display.hide()
        root.addWidget(self.dock_display)
        self.dock_display.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.dock_display.customContextMenuRequested.connect(lambda _: self.toggle_dock())

    def scale_clock(self):
        """Fit the main countdown without ever shrinking below its 100px layout."""
        if not hasattr(self, "display"):
            return
        size = int(self.settings["font_size"])
        font = QFont(self.settings["font"])
        font.setBold(True)
        font.setPixelSize(size)
        baseline = QFont(self.settings["font"])
        baseline.setBold(True)
        baseline.setPixelSize(100)
        needs_hours = max(self.settings["presets"]) >= 60 or self.duration >= 3600
        self._hours_layout = needs_hours
        template = "88:88:88" if needs_hours else "88:88"
        fm = QFontMetrics(font)
        base_fm = QFontMetrics(baseline)
        clock_width = max(fm.horizontalAdvance(template), base_fm.horizontalAdvance(template)) + 30
        clock_height = max(fm.height(), base_fm.height()) + 20
        self.display_stack.setFixedSize(clock_width, clock_height)
        self.display.setFont(font)
        self.time_input.setFont(font)
        # The controls must also fit at the baseline size, including their spacing.
        controls_width = 42 + 50 + 42 + 42 + 3 * 7 + 16
        left_width = max(clock_width, controls_width)
        presets_width = 76
        # outer margins 18, panel margins 28, column gap 10, plus spare padding.
        width = left_width + presets_width + 18 + 28 + 10 + 12
        height = max(190, 58 + len(self.settings["presets"]) * 47,
                     clock_height + 50 + 32 + 28)
        if not self.docked:
            self.setFixedSize(width, height)
        # Dock mode has its own constant font size, independent of this setting.
        dock_font = QFont(self.settings["font"])
        dock_font.setBold(True)
        dock_font.setPixelSize(48)
        self.dock_display.setFont(dock_font)
        dock_metrics = QFontMetrics(dock_font)
        self.dock_display.setFixedSize(dock_metrics.horizontalAdvance(template) + 24,
                                       dock_metrics.height() + 12)

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
        menu.addAction("Quit", self.quit_app)
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
            QLineEdit#timeInput {{ background: rgba(255,255,255,25); color: {s["text_color"]}; border: 2px solid {s["accent_color"]}; border-radius: 8px; }}
            QPushButton#display {{ background: transparent; padding: 0px; }}
            QPushButton#play {{ background: {s['accent_color']}; color: {s['text_color']}; font-weight: 700; }}
            QPushButton#presetSelected {{ background: {s['accent_color']}; color: #101820; font-weight: 700; }}
            QPushButton#topButton {{ background: transparent; padding: 0px; }}
        """)
        # Docked display is a sibling of panel, so style it independently.
        dock_bg = QColor(s["background_color"])
        dock_bg.setAlphaF(0.80)
        dock_rgba = f"rgba({dock_bg.red()}, {dock_bg.green()}, {dock_bg.blue()}, {dock_bg.alpha()})"
        self.dock_display.setStyleSheet(
            f"QPushButton {{ background-color: {dock_rgba}; color: {s['text_color']}; "
            "border: none; border-bottom-left-radius: 12px; "
            "border-bottom-right-radius: 12px; padding: 0px; }}"
        )
        for icon_button in (self.dock_button, self.play_button, self.reset_button,
                            self.minus_button, self.plus_button, self.settings_button,
                            self.minimize_button, self.close_button):
            icon_button.update()
        self.build_presets()
        self.scale_clock()
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
            font = QFont(self.settings["font"])
            font.setPixelSize(20)
            font.setBold(True)
            b.setFont(font)
            b.setMinimumWidth(76)
            b.setMinimumHeight(43)
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
        self.scale_clock()
        self.refresh()

    def edit_time(self):
        if self.docked:
            return
        seconds = max(0, int(self.remaining + 0.999))
        minutes, secs = divmod(seconds, 60)
        self.time_input.blockSignals(True)
        self.time_input.setInputMask("")
        self.time_input.setText(f"{min(minutes, 99):02}{secs:02}")
        self.time_input.blockSignals(False)
        self.display_stack.setCurrentWidget(self.time_input)
        self.time_input.setFocus()
        self.time_input.selectAll()

    def commit_time(self):
        if self.display_stack.currentWidget() != self.time_input:
            return
        value = self.time_input.text().strip()
        if len(value) != 4 or not value.isdigit() or int(value[2:]) > 59:
            show_front_warning(self, "Invalid time", "Enter four digits in MMSS format, e.g. 0530 for 5 minutes 30 seconds.")
            self.time_input.setFocus()
            return
        duration = int(value[:2]) * 60 + int(value[2:])
        self.running = False
        self.deadline = None
        self.finished = False
        self.duration = duration
        self.remaining = float(duration)
        self.display_stack.setCurrentWidget(self.display)
        self.scale_clock()
        self.refresh()

    def adjust_seconds(self, change):
        if self.running:
            self.remaining = max(0.0, self.deadline - time.monotonic())
        self.remaining = max(0.0, self.remaining + change)
        self.duration = max(0, int(self.remaining + 0.999))
        self.finished = False
        if (self.duration >= 3600) != (getattr(self, "_hours_layout", False)):
            self.scale_clock()
        if self.running:
            if self.remaining <= 0:
                self.running = False
                self.deadline = None
            else:
                self.deadline = time.monotonic() + self.remaining
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
        desired_icon = "pause" if self.running else "play"
        if self.play_button.kind != desired_icon:
            self.play_button.kind = desired_icon
            self.play_button.update()
        for minutes, b in getattr(self, "preset_buttons", []):
            b.setObjectName("presetSelected" if self.duration == minutes * 60 else "preset")
            b.style().unpolish(b)
            b.style().polish(b)
        self.setWindowTitle(f"{label} · FloatTimer")

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings = dialog.values
            save_settings(self.settings)
            self.apply_settings()

    def position_docked(self):
        # Use the screen containing the original window (not necessarily primary).
        screen = QApplication.screenAt(self.previous_position) if self.previous_position else None
        screen = screen or self.screen() or QApplication.primaryScreen()
        rect = screen.geometry()
        self.scale_clock()
        # No outer margin: docked background touches the very top of the screen.
        self.setFixedSize(self.dock_display.size())
        self.move(rect.x() + (rect.width() - self.width()) // 2, rect.y())

    def toggle_dock(self):
        if not self.docked:
            self.previous_position = self.pos()
            self.previous_size = self.size()
            self.docked = True
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self.panel.hide()
            self.layout().setContentsMargins(0, 0, 0, 0)
            self.dock_display.show()
            self.adjustSize()
            self.position_docked()
        else:
            self.docked = False
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self.dock_display.hide()
            self.layout().setContentsMargins(9, 9, 9, 9)
            self.panel.show()
            self.scale_clock()
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

    def quit_app(self):
        self.store_position()
        QApplication.instance().quit()

    def closeEvent(self, event):
        self.store_position()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    timer = FloatTimer()
    timer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
