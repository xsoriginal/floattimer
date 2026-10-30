"""Teacher Timer: compact, customisable, always-on-top countdown for Windows."""
import json
import os
import ctypes
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPoint, QSize, Signal, QPropertyAnimation, QEasingCurve, QEvent
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap, QPen, QBrush, QFontMetrics, QPainterPath, QLinearGradient, QCursor
from PySide6.QtWidgets import (
    QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox,
    QColorDialog, QFontComboBox, QComboBox, QDialogButtonBox, QSystemTrayIcon, QMenu,
    QMessageBox, QScrollArea, QFrame, QStackedWidget, QSizePolicy, QGraphicsOpacityEffect, QPlainTextEdit
)

DEFAULT = {
    "presets": [30, 60, 120, 300, 600], "preset_format": 2, "font": "Segoe UI", "font_size": 100,
    "text_color": "#FFFFFF", "background_color": "#101820",
    "accent_color": "#43E5AD", "opacity": 90, "always_on_top": True,
    "sound": True, "start_with_windows": False, "x": None, "y": None, "width": None, "height": None,
}


def resource_path(filename):
    """Resolve resources in source checkout and PyInstaller onedir/onefile."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / filename


def settings_file():
    """Save settings.json alongside the executable (or source script).

    Never import settings from earlier installations or AppData.
    PyInstaller's _MEIPASS points into _internal, so use sys.executable.
    """
    if getattr(sys, "frozen", False):
        folder = Path(sys.executable).resolve().parent
    else:
        folder = Path(__file__).resolve().parent
    return folder / "settings.json"



def instructions_file():
    """Editable classroom instructions beside the executable."""
    return settings_file().with_name("instructions.txt")


def clear_instructions_file():
    try:
        instructions_file().write_text("", encoding="utf-8")
    except OSError:
        pass


def load_instructions():
    try:
        return instructions_file().read_text(encoding="utf-8")
    except OSError:
        return ""


def load_settings():
    result = dict(DEFAULT)
    try:
        stored = json.loads(settings_file().read_text(encoding="utf-8"))
        if isinstance(stored, dict):
            result.update({k: v for k, v in stored.items() if k in DEFAULT})
    except (OSError, ValueError, TypeError):
        pass
    # Old settings stored whole minutes. Convert once in memory, then persist
    # the new seconds-based format when settings are next saved.
    try:
        values = result["presets"]
        if not isinstance(values, list):
            raise ValueError()
        values = [int(x) for x in values]
        if result.get("preset_format") != 2:
            values = [x * 60 for x in values]
        result["presets"] = [x for x in values if 1 <= x <= 59940][:5] or list(DEFAULT["presets"])
    except (ValueError, TypeError):
        result["presets"] = list(DEFAULT["presets"])
    result["preset_format"] = 2
    return result


def themed_button_colours(background):
    """Opaque, background-derived button fills with progressively darker hover."""
    base = QColor(background)
    def darken(factor):
        return QColor.fromRgbF(
            max(0.0, base.redF() * factor),
            max(0.0, base.greenF() * factor),
            max(0.0, base.blueF() * factor),
        ).name()
    return darken(0.82), darken(0.65)


def preset_label(seconds):
    """Use a short label that is unambiguous for second-based presets."""
    return f"{seconds // 60}m" if seconds % 60 == 0 else f"{seconds}s" if seconds < 60 else f"{seconds // 60}m {seconds % 60}s"


def save_settings(settings):
    settings_file().write_text(json.dumps(settings, indent=2), encoding="utf-8")



STARTUP_REGISTRY_NAME = "Teacher Timer"


def startup_command():
    """Use the stable, extracted EXE path; never a PyInstaller temp directory."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    return None


def is_windows_startup_enabled():
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            value, _ = winreg.QueryValueEx(key, STARTUP_REGISTRY_NAME)
            return value == startup_command()
    except OSError:
        return False


def set_windows_startup(enabled):
    """Manage only this user's startup entry; administrator rights aren't needed."""
    if sys.platform != "win32":
        return
    import winreg
    command = startup_command()
    if enabled and not command:
        raise OSError("Windows startup requires the packaged TeacherTimer.exe")
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, STARTUP_REGISTRY_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, STARTUP_REGISTRY_NAME)
            except FileNotFoundError:
                pass


def tray_icon():
    """Load the dedicated tray artwork, never the EXE's embedded icon."""
    path = resource_path("TeacherTimer-Tray.ico")
    icon = QIcon(str(path))
    if icon.isNull():
        raise FileNotFoundError(f"Teacher Timer tray icon is missing: {path}")
    return icon

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

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        scale = min(self.width(), self.height()) / 42
        painter.scale(scale, scale)
        window = self.window()
        color = QColor('#ffffff' if getattr(window, 'alert_active', False)
                       else getattr(window, "settings", {}).get("text_color", "#FFFFFF"))
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
            # Qt angles are in sixteenths of a degree. The 50-degree opening
            # remains centred at 9 o'clock; the arrowhead is two OPEN strokes.
            from PySide6.QtCore import QRectF, QPointF
            painter.drawArc(QRectF(-11, -11, 22, 22), 205 * 16, 310 * 16)
            # The arc ends at 155 degrees, near (-9.97, -4.65).
            # Draw the two arms into that endpoint, without a filled triangle.
            tip = QPointF(-9.97, -4.65)
            # A square, 90-degree arrowhead: one arm points straight up,
            # and the other points straight right from the arc endpoint.
            painter.drawLine(QPointF(tip.x(), tip.y() - 6.5), tip)
            painter.drawLine(tip, QPointF(tip.x() + 6.5, tip.y()))
        elif k in ("fullscreen", "exit_fullscreen"):
            # Four diagonal arrows, outwards to enter Full and inwards to exit.
            from PySide6.QtCore import QPointF
            for sx in (-1, 1):
                for sy in (-1, 1):
                    if k == "fullscreen":
                        start, tip = QPointF(sx * 5, sy * 5), QPointF(sx * 15, sy * 15)
                        painter.drawLine(start, tip)
                        painter.drawLine(QPointF(sx * 8, sy * 15), tip)
                        painter.drawLine(QPointF(sx * 15, sy * 8), tip)
                    else:
                        start, tip = QPointF(sx * 15, sy * 15), QPointF(sx * 5, sy * 5)
                        painter.drawLine(start, tip)
                        painter.drawLine(QPointF(sx * 12, sy * 5), tip)
                        painter.drawLine(QPointF(sx * 5, sy * 12), tip)
        elif k == "textbox":
            from PySide6.QtCore import QRectF
            painter.drawRoundedRect(QRectF(-14, -11, 28, 22), 2, 2)
            painter.drawLine(-8, -4, 8, -4)
            painter.drawLine(-8, 3, 5, 3)
        elif k == "trash":
            from PySide6.QtCore import QRectF
            painter.drawLine(-10, -9, 10, -9)
            painter.drawLine(-4, -13, 4, -13)
            painter.drawRoundedRect(QRectF(-8, -6, 16, 19), 1, 1)
            painter.drawLine(-3, -2, -3, 8)
            painter.drawLine(3, -2, 3, 8)
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
    """Keep validation dialogs in front of the timer, including on Windows."""
    # Use a real parent-owned dialog, not an independent top-level window.
    # Temporarily remove the owner's always-on-top status while the dialog
    # is open: a topmost Qt.Tool can otherwise cover a separate message box.
    owner = parent.window() if parent is not None else None
    was_topmost = bool(owner.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) if owner else False
    if owner and was_topmost:
        owner.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        owner.show()

    try:
        alert = QMessageBox(QMessageBox.Icon.Warning, title, message,
                            QMessageBox.StandardButton.Ok, owner)
        alert.setWindowModality(Qt.WindowModality.ApplicationModal)
        alert.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        alert.adjustSize()
        if owner is not None:
            centre = owner.frameGeometry().center()
            alert.move(centre.x() - alert.width() // 2,
                       centre.y() - alert.height() // 2)

        alert.show()
        alert.raise_()
        alert.activateWindow()
        if sys.platform == "win32":
            HWND_TOPMOST = -1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_SHOWWINDOW = 0x0040
            ctypes.windll.user32.SetWindowPos(
                int(alert.winId()), HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
            )
        return alert.exec()
    finally:
        if owner and was_topmost:
            owner.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            owner.show()
            owner.raise_()


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Teacher Timer settings")
        self.resize(490, 588)
        self.values = dict(settings)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(QLabel("Countdown presets"))
        layout.addWidget(QLabel("Choose a duration and unit for each of the five buttons."))
        self.preset_inputs = []
        for index, seconds in enumerate(settings["presets"][:5]):
            preset_row = QHBoxLayout()
            preset_row.addWidget(QLabel(f"Preset {index + 1}"))
            value = QSpinBox()
            value.setRange(1, 999)
            unit = QComboBox()
            unit.addItems(["Seconds", "Minutes"])
            if seconds % 60 == 0:
                unit.setCurrentIndex(1)
                value.setValue(seconds // 60)
            else:
                unit.setCurrentIndex(0)
                value.setValue(seconds)
            preset_row.addWidget(value, 1)
            preset_row.addWidget(unit, 1)
            layout.addLayout(preset_row)
            self.preset_inputs.append((value, unit))
        # All normal settings have five entries, but fill any older partial list.
        for index in range(len(self.preset_inputs), 5):
            preset_row = QHBoxLayout()
            preset_row.addWidget(QLabel(f"Preset {index + 1}"))
            value = QSpinBox()
            value.setRange(1, 999)
            value.setValue(DEFAULT["presets"][index] // 60 if DEFAULT["presets"][index] % 60 == 0 else DEFAULT["presets"][index])
            unit = QComboBox()
            unit.addItems(["Seconds", "Minutes"])
            unit.setCurrentIndex(1 if DEFAULT["presets"][index] % 60 == 0 else 0)
            preset_row.addWidget(value, 1)
            preset_row.addWidget(unit, 1)
            layout.addLayout(preset_row)
            self.preset_inputs.append((value, unit))
        form = QFormLayout()
        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont(settings["font"]))
        form.addRow("Countdown font", self.font)
        self.colors = {}
        self.color_previews = {}
        for key, label in (("text_color", "Text colour"), ("background_color", "Background colour"), ("accent_color", "Accent colour")):
            color_row = QHBoxLayout()
            color_row.setContentsMargins(0, 0, 0, 0)
            color_row.setSpacing(8)
            button = QPushButton(self.values[key])
            button.clicked.connect(lambda _=False, k=key: self.choose_color(k))
            color_row.addWidget(button, 1)
            preview = QPushButton()
            preview.setFixedSize(32, 28)
            preview.setToolTip(f"Choose {label.lower()}")
            preview.setAccessibleName(f"Choose {label.lower()} from colour preview")
            preview.clicked.connect(lambda _=False, k=key: self.choose_color(k))
            color_row.addWidget(preview)
            self.colors[key] = button
            self.color_previews[key] = preview
            self.update_color_preview(key)
            form.addRow(label, color_row)
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
        self.startup = QCheckBox("Start Teacher Timer when I sign in to Windows")
        self.startup.setChecked(is_windows_startup_enabled() if sys.platform == "win32" else False)
        self.startup.setEnabled(sys.platform == "win32" and startup_command() is not None)
        form.addRow(self.startup)
        layout.addLayout(form)
        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        copyright_note = QLabel(
            "© 2026 Todd Beamish\n"
            "Free to share within Pate's Grammar School."
        )
        copyright_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        copyright_note.setWordWrap(True)
        copyright_note.setStyleSheet("color: #777777; font-size: 11px; padding: 8px 4px 2px;")
        outer.addWidget(copyright_note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def update_color_preview(self, key):
        colour = QColor(self.values[key])
        if not colour.isValid():
            return
        self.color_previews[key].setStyleSheet(
            "QPushButton { background-color: " + colour.name() + "; "
            "border: 1px solid #888; border-radius: 4px; } "
            "QPushButton:hover { border: 2px solid #dddddd; }"
        )

    def choose_color(self, key):
        color = QColorDialog.getColor(QColor(self.values[key]), self, "Choose colour")
        if color.isValid():
            self.values[key] = color.name()
            self.colors[key].setText(color.name())
            self.update_color_preview(key)

    def accept(self):
        entries = [value.value() * (60 if unit.currentIndex() == 1 else 1)
                   for value, unit in self.preset_inputs]
        self.values.update(presets=entries, preset_format=2, font=self.font.currentFont().family(),
                           opacity=self.opacity.value(),
                           always_on_top=self.top.isChecked(), sound=self.sound.isChecked(),
                           start_with_windows=self.startup.isChecked())
        super().accept()


class ProgressStrip(QWidget):
    """Full-width countdown progress; height matches the fullscreen play button."""
    def __init__(self, timer):
        super().__init__()
        self.timer = timer
        self.setFixedHeight(84)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        if not self.timer.progress_started or self.timer.remaining <= 0:
            return
        maximum = max(0.001, self.timer.progress_max)
        ratio = min(1.0, max(0.0, self.timer.remaining / maximum))
        seconds = self.timer.remaining
        colour = '#e5404b' if seconds <= 10 else '#e5e540' if seconds < 30 else '#43E5AD'
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Dark, translucent track keeps empty progress legible on any theme.
        painter.fillRect(self.rect(), QColor(0, 0, 0, 95))
        painter.fillRect(0, 0, round(self.width() * ratio), self.height(), QColor(colour))
        # A narrow dark edge defines the bar even against similarly coloured
        # backgrounds; the lower gradient reads as a subtle inset shadow.
        painter.setPen(QPen(QColor(0, 0, 0, 115), 2))
        painter.drawLine(0, 0, self.width(), 0)
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        shadow = QLinearGradient(0, self.height() - 14, 0, self.height())
        shadow.setColorAt(0.0, QColor(0, 0, 0, 0))
        shadow.setColorAt(1.0, QColor(0, 0, 0, 85))
        painter.fillRect(0, self.height() - 14, self.width(), 14, shadow)
        painter.end()


class FixedSlotClock(QPushButton):
    """Draw every digit in an equal-width cell; colons have their own fixed cells."""
    def __init__(self, label=''):
        super().__init__(label)
        self.clock_colour = QColor('#ffffff')

    def set_clock_colour(self, colour):
        self.clock_colour = QColor(colour)
        self.update()

    @staticmethod
    def slot_widths(font, label):
        metrics = QFontMetrics(font)
        digit = max(metrics.horizontalAdvance(str(n)) for n in range(10))
        colon = metrics.horizontalAdvance(':')
        return [digit if char != ':' else colon for char in label]

    @classmethod
    def text_width(cls, font, label):
        return sum(cls.slot_widths(font, label))

    def paintEvent(self, event):
        # Don't let QPushButton centre a proportional text string as a whole.
        # Every character's centre is independent of its glyph's actual width.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self.font())
        painter.setPen(self.clock_colour)
        label = self.text()
        widths = self.slot_widths(self.font(), label)
        left = (self.width() - sum(widths)) / 2
        for char, cell in zip(label, widths):
            painter.drawText(QRectF(left, 0, cell, self.height()),
                             Qt.AlignmentFlag.AlignCenter, char)
            left += cell
        painter.end()


class FlexibleClockStack(QStackedWidget):
    """Do not let the large countdown font dictate the window's minimum width."""
    def minimumSizeHint(self):
        return QSize(0, 0)

    def sizeHint(self):
        return QSize(0, 0)


class PresentationWindow(QWidget):
    """Fullscreen view sharing countdown state and the main window's icons."""
    def __init__(self, timer):
        super().__init__()
        self.timer = timer
        self.settings = timer.settings
        # Only a countdown finishing while fullscreen is open triggers the red alert.
        # Opening fullscreen at 00:00 must retain the normal background.
        self.alert_active = False
        self.setWindowTitle('Teacher Timer · Presentation Mode')
        self.setWindowIcon(timer.windowIcon())
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 28)
        layout.setSpacing(0)

        self.progress = ProgressStrip(timer)
        self.progress_effect = QGraphicsOpacityEffect(self.progress)
        self.progress.setGraphicsEffect(self.progress_effect)
        self.progress_effect.setOpacity(1.0 if timer.progress_started and timer.remaining > 0 else 0.0)
        self.progress_animation = QPropertyAnimation(self.progress_effect, b'opacity', self)
        self.progress_animation.setDuration(450)
        self.progress_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        layout.addWidget(self.progress)

        top = QHBoxLayout()
        top.setContentsMargins(30, 10, 30, 0)
        top.addStretch()
        self.instructions_toggle = IconButton('textbox', self.toggle_instructions, 'topButton', 32)
        self.instructions_toggle.setToolTip('Show or hide student instructions')
        top.addWidget(self.instructions_toggle)
        self.exit_button = IconButton('exit_fullscreen', timer.exit_presentation, 'topButton', 32)
        self.exit_button.setToolTip('Exit fullscreen (Esc or F11)')
        top.addWidget(self.exit_button)
        layout.addLayout(top)
        # Keep the instructions panel tall, between the top toolbar and bottom controls.
        layout.addSpacing(14)

        self.content_row = QHBoxLayout()
        self.content_row.setContentsMargins(32, 0, 24, 0)
        self.content_row.setSpacing(24)
        self.display_stack = FlexibleClockStack()
        self.display = FixedSlotClock()
        self.display.setObjectName('fullscreenDisplay')
        self.display.setCursor(Qt.CursorShape.PointingHandCursor)
        self.display.setToolTip('Click to enter a time as MMSS')
        self.display.clicked.connect(self.edit_time)
        self.display.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.display.setMinimumSize(0, 0)
        self.display_stack.addWidget(self.display)
        self.time_input = QLineEdit()
        self.time_input.setObjectName('fullscreenTimeInput')
        self.time_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_input.setMaxLength(4)
        self.time_input.setToolTip('Type four digits MMSS, then Enter')
        self.time_input.returnPressed.connect(self.commit_time)
        self.time_input.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.time_input.setMinimumSize(0, 0)
        self.display_stack.addWidget(self.time_input)
        self.display_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # The clock must yield space to the protected instructions column.
        self.display_stack.setMinimumWidth(0)
        self.content_row.addWidget(self.display_stack, 1)

        self.instructions_panel = QFrame()
        self.instructions_panel.setObjectName('instructionsPanel')
        panel_layout = QVBoxLayout(self.instructions_panel)
        panel_layout.setContentsMargins(16, 16, 16, 12)
        panel_layout.setSpacing(12)
        self.instructions_editor = QPlainTextEdit()
        self.instructions_editor.setObjectName('instructionsEditor')
        self.instructions_editor.setPlaceholderText('Intructions...')
        self.instructions_editor.setPlainText(load_instructions())
        self.instructions_font_size = 26  # One step above the 22px preset font.
        self.apply_instructions_font()
        self.instructions_editor.textChanged.connect(self.save_instructions)
        panel_layout.addWidget(self.instructions_editor, 1)
        tools = QHBoxLayout()
        tools.addStretch()
        self.text_smaller = IconButton('minus', lambda: self.resize_instructions(-2), size=44)
        self.text_larger = IconButton('plus', lambda: self.resize_instructions(2), size=44)
        self.text_clear = IconButton('trash', self.clear_instructions, size=44)
        for control in (self.text_smaller, self.text_larger, self.text_clear):
            tools.addWidget(control)
        self.text_smaller.setToolTip('Decrease instruction text size')
        self.text_larger.setToolTip('Increase instruction text size')
        self.text_clear.setToolTip('Clear instructions')
        panel_layout.addLayout(tools)
        self.instructions_panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.content_row.addWidget(self.instructions_panel, 0)
        # No fixed widths before the fullscreen geometry is established.
        self.instructions_panel.hide()
        layout.addLayout(self.content_row, 1)
        layout.addSpacing(18)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(36, 0, 36, 0)
        bottom.setSpacing(18)
        self.minus_button = IconButton('minus', lambda: timer.adjust_seconds(-30), size=72)
        self.play_button = IconButton('play', timer.toggle, 'play', 84)
        self.reset_button = IconButton('reset', timer.reset, size=72)
        self.plus_button = IconButton('plus', lambda: timer.adjust_seconds(30), size=72)
        for control in (self.minus_button, self.play_button, self.reset_button, self.plus_button):
            bottom.addWidget(control)
        bottom.addStretch(1)
        self.preset_buttons = []
        for seconds in timer.settings['presets'][:5]:
            preset = button(preset_label(seconds), lambda checked=False, s=seconds: timer.select_preset(s), 'fullscreenPreset')
            preset.setFixedHeight(64)
            preset.setMinimumWidth(0)
            preset.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            font = QFont(timer.settings['font'])
            font.setPixelSize(22)
            font.setBold(True)
            preset.setFont(font)
            bottom.addWidget(preset, 1)
            self.preset_buttons.append(preset)
        layout.addLayout(bottom)
        self.apply_theme()
        QApplication.instance().installEventFilter(self)

    def update_button_visibility(self):
        cursor = QCursor.pos()
        hovered = self.isVisible() and self.rect().contains(self.mapFromGlobal(cursor))
        controls = [self.instructions_toggle, self.exit_button, self.minus_button,
                    self.play_button, self.reset_button, self.plus_button]
        controls.extend(self.preset_buttons)
        controls.extend([self.text_smaller, self.text_larger, self.text_clear])
        set_hover_controls(self, controls, hovered)

    def update_content_widths(self):
        """Reserve the right quarter without allowing the clock to enlarge the window."""
        self.display_stack.setMinimumWidth(0)
        self.display_stack.setMaximumWidth(16777215)
        if self.instructions_panel.isVisible():
            margins = self.content_row.contentsMargins()
            usable = max(0, self.width() - margins.left() - margins.right()
                         - self.content_row.spacing())
            notes_width = max(0, usable // 4)
            self.instructions_panel.setFixedWidth(notes_width)
        # The remaining space is allocated to the clock by the layout.
        # Never set a fixed width on the clock: its large text must shrink to fit.

    def toggle_instructions(self):
        self.instructions_panel.setVisible(not self.instructions_panel.isVisible())
        self.update_content_widths()
        # Reflow the layout before measuring the clock's available width.
        # The timer may be stopped at 00:00, so no subsequent tick can be
        # relied on to recalculate its font after the notes panel closes.
        self.content_row.invalidate()
        self.layout().activate()
        self.fit_clock_font()
        QTimer.singleShot(0, self.fit_clock_font)

    def apply_instructions_font(self):
        font = QFont(self.timer.settings['font'])
        font.setPixelSize(self.instructions_font_size)
        self.instructions_editor.setFont(font)

    def resize_instructions(self, amount):
        self.instructions_font_size = max(14, min(72, self.instructions_font_size + amount))
        self.apply_instructions_font()

    def save_instructions(self):
        try:
            instructions_file().write_text(self.instructions_editor.toPlainText(), encoding='utf-8')
        except OSError:
            pass

    def clear_instructions(self):
        self.instructions_editor.clear()

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.MouseButtonPress
                and self.display_stack.currentWidget() is self.time_input
                and isinstance(obj, QWidget)
                and (obj is self or self.isAncestorOf(obj))
                and obj is not self.time_input):
            self.cancel_time_entry()
        if self.alert_active and event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress):
            if isinstance(obj, QWidget) and (obj is self or self.isAncestorOf(obj)):
                self.clear_alert()
        return super().eventFilter(obj, event)

    def clear_alert(self):
        if self.alert_active:
            self.alert_active = False
            self.apply_theme()

    def set_finished_alert(self):
        if not self.alert_active:
            self.alert_active = True
            self.apply_theme()

    def show_progress(self):
        if self.timer.remaining <= 0:
            return
        self.progress_animation.stop()
        self.progress_animation.setStartValue(self.progress_effect.opacity())
        self.progress_animation.setEndValue(1.0)
        self.progress_animation.start()
        self.progress.update()

    def hide_progress(self):
        self.progress_animation.stop()
        self.progress_effect.setOpacity(0.0)
        self.progress.update()

    def edit_time(self):
        self.clear_alert()
        seconds = max(0, int(self.timer.remaining + .999))
        minutes, secs = divmod(seconds, 60)
        self.time_input.setText(f'{min(minutes, 99):02}{secs:02}')
        self.display_stack.setCurrentWidget(self.time_input)
        self.time_input.setFocus()
        self.time_input.selectAll()

    def cancel_time_entry(self):
        if self.display_stack.currentWidget() is self.time_input:
            self.display_stack.setCurrentWidget(self.display)
            self.update_clock()

    def commit_time(self):
        if self.display_stack.currentWidget() != self.time_input:
            return
        value = self.time_input.text().strip()
        if len(value) != 4 or not value.isdigit() or int(value[2:]) > 59:
            show_front_warning(self, 'Invalid time', 'Enter four digits in MMSS format, e.g. 0530.')
            self.time_input.setFocus()
            return
        self.timer.set_time_seconds(int(value[:2]) * 60 + int(value[2:]))
        self.display_stack.setCurrentWidget(self.display)
        self.update_clock()

    def apply_theme(self):
        self.settings = self.timer.settings
        s = self.settings
        background = '#e5404b' if self.alert_active else s['background_color']
        foreground = '#ffffff' if self.alert_active else s['text_color']
        button_bg, button_hover = themed_button_colours(background)
        play_bg = button_bg
        top_bg = 'transparent'
        self.setStyleSheet(f"""
            PresentationWindow {{ background: {background}; }}
            QLabel, QPushButton#fullscreenDisplay {{ color: {foreground}; background: transparent; border: none; }}
            QPushButton {{ background: {button_bg}; border: none; border-radius: 14px; }}
            QPushButton:hover {{ background: {button_hover}; }}
            QPushButton#play {{ background: {play_bg}; }}
            QPushButton#play:hover {{ background: {button_hover}; }}
            QPushButton#topButton, QPushButton#topButton:hover {{ background: {top_bg}; }}
            QLineEdit#fullscreenTimeInput {{ background: rgba(255,255,255,25); color: {foreground}; border: 2px solid {s['accent_color']}; border-radius: 12px; }}
            QPushButton#fullscreenPreset {{ color: {foreground}; }}
            QFrame#instructionsPanel {{ border: 2px solid rgba(255,255,255,160); border-radius: 12px; background: transparent; }}
            QPlainTextEdit#instructionsEditor {{ color: {foreground}; background: transparent; border: none; selection-background-color: {s['accent_color']}; }}

        """)
        self.display.set_clock_colour(foreground)
        self.apply_instructions_font()
        self.fit_clock_font()
        self.update_clock()
        self.update()
        for control in (self.instructions_toggle, self.text_smaller, self.text_larger, self.text_clear,
                        self.minus_button, self.play_button, self.reset_button,
                        self.plus_button, self.exit_button):
            control.update()

    def fit_clock_font(self):
        """Size once for the widest possible clock, not the current digits."""
        font = QFont(self.settings['font'])
        font.setBold(True)
        available_width = max(100, self.display_stack.width() - 64)
        available_height = max(100, self.display_stack.height() * .8)
        size = max(30, min(int(available_height), 500))
        # Each digit position is allocated the width of the widest numeral.
        # This avoids changes in font size when, e.g., 11 becomes 10.
        groups = 3 if max(self.timer.duration, self.timer.remaining) >= 3600 else 2
        while size > 30:
            font.setPixelSize(size)
            metrics = QFontMetrics(font)
            widest_digit = max(metrics.horizontalAdvance(str(i)) for i in range(10))
            worst_width = FixedSlotClock.text_width(font, '88:88:88' if groups == 3 else '88:88')
            if worst_width <= available_width:
                break
            size -= 4
        font.setPixelSize(size)
        self.display.setFont(font)
        self.time_input.setFont(font)

    def update_clock(self):
        label = self.timer.format_time()
        if label.count(':') != self.display.text().count(':'):
            self.fit_clock_font()
        self.display.setText(label)
        self.play_button.kind = 'pause' if self.timer.running else 'play'
        self.play_button.update()
        self.progress.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_content_widths()
        self.fit_clock_font()
        self.update_clock()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F11):
            if self.display_stack.currentWidget() == self.time_input and event.key() == Qt.Key.Key_Escape:
                self.display_stack.setCurrentWidget(self.display)
            else:
                self.timer.exit_presentation()
        elif event.key() == Qt.Key.Key_Space and self.display_stack.currentWidget() != self.time_input:
            self.timer.toggle()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        if self.timer.presentation is self:
            event.ignore()
            self.timer.exit_presentation()
        else:
            event.accept()


def set_hover_controls(window, controls, show):
    """Keep button geometry reserved while hiding their artwork and hit targets."""
    for control in controls:
        if control is None:
            continue
        effect = control.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(control)
            control.setGraphicsEffect(effect)
        effect.setOpacity(1.0 if show else 0.0)
        control.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not show)


class TeacherTimer(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.duration = self.settings["presets"][0]
        self.remaining = float(self.duration)
        self.deadline = None
        self.running = False
        self.finished = False
        self.alert_active = False
        self.progress_max = 0.0
        self.progress_started = False
        self.progress_needs_initialising = True
        self.docked = False
        self.presentation = None
        self.previous_position = None
        self.previous_size = None
        self.setWindowTitle("Teacher Timer")
        self.setWindowIcon(QIcon(str(resource_path("TeacherTimer.ico"))))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.build_ui()
        QApplication.instance().installEventFilter(self)
        self.setFixedSize(420, max(190, 58 + len(self.settings["presets"]) * 47))
        self.make_tray()
        self.apply_settings()
        if self.settings["x"] is not None and self.settings["y"] is not None:
            self.move(int(self.settings["x"]), int(self.settings["y"]))
        self.clock = QTimer(self)
        self.clock.setInterval(80)
        self.clock.timeout.connect(self.tick)
        self.clock.timeout.connect(self.update_button_visibility)
        self.clock.start()
        self.refresh()
        self.update_button_visibility()

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
        self.fullscreen_button = IconButton("fullscreen", self.enter_presentation, "topButton", 32)
        self.fullscreen_button.setToolTip("Presentation Mode (F11)")
        bar_layout.addWidget(self.fullscreen_button)
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
        close_button.setToolTip("Exit Teacher Timer")
        bar_layout.addWidget(close_button)
        body.addWidget(bar)
        main = QHBoxLayout()
        main.setSpacing(10)
        left = QVBoxLayout()
        self.display_stack = QStackedWidget()
        self.display_stack.setMinimumWidth(210)
        self.display = FixedSlotClock("05:00")
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
        self._invalid_time_value = None
        self.time_input.textEdited.connect(lambda _: setattr(self, "_invalid_time_value", None))
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
        body.addLayout(main)
        self.preset_box = QHBoxLayout()
        self.preset_box.setSpacing(6)
        body.addLayout(self.preset_box)
        # The complete interface is hidden in dock mode, leaving only a clickable time.
        self.dock_display = FixedSlotClock("05:00")
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
        needs_hours = max(self.settings["presets"]) >= 3600 or self.duration >= 3600
        self._hours_layout = needs_hours
        template = "88:88:88" if needs_hours else "88:88"
        fm = QFontMetrics(font)
        base_fm = QFontMetrics(baseline)
        clock_width = max(FixedSlotClock.text_width(font, template), FixedSlotClock.text_width(baseline, template)) + 30
        clock_height = max(fm.height(), base_fm.height()) + 20
        self.display_stack.setFixedSize(clock_width, clock_height)
        self.display.setFont(font)
        self.time_input.setFont(font)
        # The controls must also fit at the baseline size, including their spacing.
        controls_width = 42 + 50 + 42 + 42 + 3 * 7 + 16
        left_width = max(clock_width, controls_width)
        presets_width = len(self.settings["presets"]) * 60 + max(0, len(self.settings["presets"]) - 1) * 6
        width = max(left_width, presets_width) + 18 + 28 + 24
        height = max(190, clock_height + 50 + 43 + 32 + 32)
        if not self.docked:
            self.setFixedSize(width, height)
        # Dock mode has its own constant font size, independent of this setting.
        dock_font = QFont(self.settings["font"])
        dock_font.setBold(True)
        dock_font.setPixelSize(48)
        self.dock_display.setFont(dock_font)
        dock_metrics = QFontMetrics(dock_font)
        self.dock_display.setFixedSize(FixedSlotClock.text_width(dock_font, template) + 24,
                                       dock_metrics.height() + 12)

    def make_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(tray_icon())
        self.tray.setToolTip("Teacher Timer")
        self.tray_menu = QMenu()
        self.rebuild_tray_menu()
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(
            lambda reason: self.show_normal()
            if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                          QSystemTrayIcon.ActivationReason.DoubleClick) else None
        )
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
            self.tray.setIcon(tray_icon())

    def rebuild_tray_menu(self):
        """Refresh the tray choices from the current configured presets."""
        self.tray_menu.clear()
        for seconds in self.settings["presets"]:
            self.tray_menu.addAction(
                preset_label(seconds),
                lambda checked=False, s=seconds: self.start_tray_preset(s)
            )

    def start_tray_preset(self, seconds):
        """Open the main window and start the selected countdown immediately."""
        if self.presentation is not None:
            self.exit_presentation()
        self.select_preset(seconds)
        self.show_normal()
        self.toggle()

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.MouseButtonPress
                and self.display_stack.currentWidget() is self.time_input
                and isinstance(obj, QWidget)
                and (obj is self or self.isAncestorOf(obj))
                and obj is not self.time_input):
            self.cancel_time_entry()
        if (self.alert_active
                and event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress)
                and isinstance(obj, QWidget)
                and (obj is self or self.isAncestorOf(obj))):
            self.clear_alert()
        return super().eventFilter(obj, event)

    def update_button_visibility(self):
        if self.docked:
            return
        cursor = QCursor.pos()
        local = self.mapFromGlobal(cursor)
        hovered = self.isVisible() and self.rect().contains(local)
        controls = [self.dock_button, self.fullscreen_button, self.settings_button,
                    self.minimize_button, self.close_button, self.minus_button,
                    self.play_button, self.reset_button, self.plus_button]
        controls.extend(b for _, b in getattr(self, 'preset_buttons', []))
        set_hover_controls(self, controls, hovered)

    def clear_alert(self):
        if self.alert_active:
            self.alert_active = False
            self.apply_settings()

    def apply_settings(self):
        s = self.settings
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if s["always_on_top"]:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        bg = QColor("#e5404b" if self.alert_active else s["background_color"])
        bg.setAlphaF(s["opacity"] / 100)
        rgba = f"rgba({bg.red()}, {bg.green()}, {bg.blue()}, {bg.alpha()})"
        foreground = "#ffffff" if self.alert_active else s["text_color"]
        button_bg, button_hover = themed_button_colours('#e5404b' if self.alert_active else s['background_color'])
        play_bg = button_bg
        top_bg = 'transparent'
        self.panel.setStyleSheet(f"""
            QFrame#panel {{ background: {rgba}; border-radius: 18px; }}
            QLabel {{ color: {foreground}; }}
            QPushButton {{ background: {button_bg}; color: {foreground};
                          border: none; border-radius: 9px; padding: 7px 11px; }}
            QPushButton:hover {{ background: {button_hover}; }}
            QLineEdit#timeInput {{ background: rgba(255,255,255,25); color: {foreground}; border: 2px solid {s["accent_color"]}; border-radius: 8px; }}
            QPushButton#display {{ background: transparent; padding: 0px; }}
            QPushButton#play {{ background: {play_bg}; color: {foreground}; font-weight: 700; }}
            QPushButton#play:hover {{ background: {button_hover}; }}
            QPushButton#topButton, QPushButton#topButton:hover {{ background: {top_bg}; padding: 0px; }}
        """)
        self.display.set_clock_colour(foreground)
        self.dock_display.set_clock_colour(foreground)
        # Docked display is a sibling of panel, so style it independently.
        dock_bg = QColor("#e5404b" if self.alert_active else s["background_color"])
        dock_bg.setAlphaF(0.80)
        dock_rgba = f"rgba({dock_bg.red()}, {dock_bg.green()}, {dock_bg.blue()}, {dock_bg.alpha()})"
        self.dock_display.setStyleSheet(
            f"QPushButton {{ background-color: {dock_rgba}; color: {foreground}; "
            "border: none; border-bottom-left-radius: 12px; "
            "border-bottom-right-radius: 12px; padding: 0px; }}"
        )
        for icon_button in (self.dock_button, self.play_button, self.reset_button,
                            self.minus_button, self.plus_button, self.settings_button,
                            self.minimize_button, self.close_button, self.fullscreen_button):
            icon_button.update()
        self.build_presets()
        self.rebuild_tray_menu()
        self.scale_clock()
        if self.presentation is not None:
            self.presentation.apply_theme()
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
        for seconds in self.settings["presets"]:
            b = button(preset_label(seconds), lambda _=False, s=seconds: self.select_preset(s), "preset")
            font = QFont(self.settings["font"])
            font.setPixelSize(20)
            font.setBold(True)
            b.setFont(font)
            b.setMinimumWidth(0)
            b.setMinimumHeight(43)
            self.preset_box.addWidget(b, 1)
            self.preset_buttons.append((seconds, b))
        self.refresh()
        self.update_button_visibility()

    def select_preset(self, seconds):
        self.running = False
        self.deadline = None
        self.finished = False
        self.mark_new_time()
        self.duration = seconds
        self.remaining = float(self.duration)
        self.scale_clock()
        self.refresh()

    def edit_time(self):
        if self.docked:
            return
        self._invalid_time_value = None
        seconds = max(0, int(self.remaining + 0.999))
        minutes, secs = divmod(seconds, 60)
        self.time_input.blockSignals(True)
        self.time_input.setInputMask("")
        self.time_input.setText(f"{min(minutes, 99):02}{secs:02}")
        self.time_input.blockSignals(False)
        self.display_stack.setCurrentWidget(self.time_input)
        self.time_input.setFocus()
        self.time_input.selectAll()

    def cancel_time_entry(self):
        if self.display_stack.currentWidget() is self.time_input:
            # Suppress editingFinished: clicking outside must discard, not save.
            self.time_input.blockSignals(True)
            self.display_stack.setCurrentWidget(self.display)
            self.time_input.blockSignals(False)
            self.refresh()

    def commit_time(self):
        if self.display_stack.currentWidget() != self.time_input:
            return
        value = self.time_input.text().strip()
        if len(value) != 4 or not value.isdigit() or int(value[2:]) > 59:
            # Return/Enter and focus loss can both trigger commit_time.
            # Show one warning per invalid input, even across the modal event loop.
            if self._invalid_time_value == value:
                return
            self._invalid_time_value = value
            show_front_warning(self, "Invalid time", "Enter four digits in MMSS format, e.g. 0530 for 5 minutes 30 seconds.")
            self.time_input.setFocus()
            return
        self._invalid_time_value = None
        self.set_time_seconds(int(value[:2]) * 60 + int(value[2:]))
        self.display_stack.setCurrentWidget(self.display)

    def mark_new_time(self):
        """The next Play establishes a new progress maximum."""
        self.clear_alert()
        self.progress_needs_initialising = True
        self.progress_started = False
        if self.presentation is not None:
            self.presentation.hide_progress()
            self.presentation.clear_alert()

    def set_time_seconds(self, seconds):
        self.running = False
        self.deadline = None
        self.finished = False
        self.duration = max(0, int(seconds))
        self.remaining = float(self.duration)
        self.mark_new_time()
        self.scale_clock()
        self.refresh()

    def adjust_seconds(self, change):
        was_running = self.running
        if not was_running:
            self.mark_new_time()
        if self.running:
            self.remaining = max(0.0, self.deadline - time.monotonic())
        self.remaining = max(0.0, self.remaining + change)
        self.duration = max(0, int(self.remaining + 0.999))
        self.finished = False
        if was_running and self.progress_started and self.remaining > self.progress_max:
            self.progress_max = self.remaining
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
        return f"{hours:02}:{minutes:02}:{secs:02}" if (hours or self.duration >= 3600) else f"{minutes:02}:{secs:02}"

    def toggle(self):
        if self.running:
            self.remaining = max(0.0, self.deadline - time.monotonic())
            self.running = False
            self.deadline = None
        else:
            if self.remaining <= 0:
                # A completed countdown starts a fresh run, not a paused run.
                # Re-arm the fullscreen progress strip as well as the timer.
                self.remaining = float(self.duration)
                self.finished = False
                self.progress_needs_initialising = True
                self.progress_started = False
            if self.progress_needs_initialising:
                self.progress_max = max(0.001, self.remaining)
                self.progress_needs_initialising = False
                self.progress_started = self.remaining > 0
                if self.presentation is not None:
                    self.presentation.show_progress()
            self.deadline = time.monotonic() + self.remaining
            self.running = True
        self.refresh()

    def reset(self):
        self.running = False
        self.deadline = None
        self.remaining = float(self.duration)
        self.finished = False
        self.mark_new_time()
        self.refresh()

    def tick(self):
        if not self.running:
            return
        self.remaining = max(0.0, self.deadline - time.monotonic())
        if self.remaining <= 0:
            self.running = False
            self.deadline = None
            self.finished = True
            self.progress_started = False
            if self.presentation is not None:
                self.presentation.hide_progress()
                self.presentation.set_finished_alert()
            else:
                self.alert_active = True
                self.apply_settings()
            if self.settings["sound"]:
                QApplication.beep()
            if self.tray.isVisible():
                self.tray.showMessage("Teacher Timer", "Time's up!", QSystemTrayIcon.MessageIcon.Information, 4000)
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
        self.setWindowTitle(f"{label} · Teacher Timer")
        if self.presentation is not None:
            self.presentation.update_clock()
            self.presentation.update_button_visibility()

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                set_windows_startup(dialog.values["start_with_windows"])
            except OSError as exc:
                show_front_warning(self, "Windows startup", f"Could not update startup setting: {exc}")
                return
            self.settings = dialog.values
            save_settings(self.settings)
            self.apply_settings()

    def enter_presentation(self):
        self.clear_alert()
        if self.presentation is not None:
            return
        if self.docked:
            self.toggle_dock()
        screen = self.screen() or QApplication.primaryScreen()
        self.presentation = PresentationWindow(self)
        self.hide()
        self.presentation.setGeometry(screen.geometry())
        self.presentation.showFullScreen()
        self.presentation.raise_()
        self.presentation.activateWindow()

    def exit_presentation(self):
        if self.presentation is None:
            return
        presentation = self.presentation
        self.presentation = None
        QApplication.instance().removeEventFilter(presentation)
        presentation.hide()
        presentation.deleteLater()
        self.show()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F11:
            self.enter_presentation()
        elif event.key() == Qt.Key.Key_Space:
            self.toggle()
        else:
            super().keyPressEvent(event)

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
        self.clear_alert()
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
        self.clear_alert()
        if self.docked:
            self.toggle_dock()
        self.show()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        if self.presentation is not None:
            self.exit_presentation()
        self.store_position()
        QApplication.instance().quit()

    def closeEvent(self, event):
        self.store_position()
        event.accept()


def main():
    if sys.platform == "win32":
        # Stable identity for Windows taskbar and notification-area preferences.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TeacherTimer.Desktop.Timer")
    app = QApplication(sys.argv)
    app.setApplicationName("Teacher Timer")
    app.setOrganizationName("Teacher Timer")
    app.setWindowIcon(QIcon(str(resource_path("TeacherTimer.ico"))))
    app.setQuitOnLastWindowClosed(False)

    # One instance per Windows login. A second launch sends SHOW to the
    # existing process and exits, rather than creating another tray icon.
    # The user-specific suffix prevents clashes between different sessions.
    if sys.platform == "win32":
        import getpass
        import hashlib
        user_key = hashlib.sha256(getpass.getuser().encode("utf-8")).hexdigest()[:16]
        server_name = f"TeacherTimer-{user_key}"
    else:
        server_name = f"TeacherTimer-{os.getuid()}"

    def signal_existing():
        socket = QLocalSocket()
        socket.connectToServer(server_name)
        if socket.waitForConnected(700):
            socket.write(b"SHOW\n")
            socket.flush()
            socket.waitForBytesWritten(700)
            socket.disconnectFromServer()
            return True
        return False

    if signal_existing():
        return

    server = QLocalServer(app)
    if not server.listen(server_name):
        # A second launch may race the first one. Never remove a potentially
        # live Windows endpoint just to force another instance to open.
        if signal_existing():
            return
        if sys.platform != "win32":
            QLocalServer.removeServer(server_name)  # clean up stale Unix socket
            if not server.listen(server_name):
                return
        else:
            return

    timer = TeacherTimer()
    app.aboutToQuit.connect(clear_instructions_file)

    def accept_activation():
        while server.hasPendingConnections():
            socket = server.nextPendingConnection()
            socket.waitForReadyRead(250)
            if bytes(socket.readAll()).startswith(b"SHOW"):
                if timer.presentation is not None:
                    timer.exit_presentation()
                timer.show_normal()
            socket.disconnectFromServer()
            socket.deleteLater()

    server.newConnection.connect(accept_activation)
    timer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
