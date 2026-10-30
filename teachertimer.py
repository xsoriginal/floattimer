"""Teacher Timer: compact, customisable, always-on-top countdown for Windows."""
import json
import configparser
import os
import ctypes
import sys
import time
import math
import wave
import struct
import tempfile
import base64
import zlib
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPoint, QSize, QRectF, Signal, QPropertyAnimation, QEasingCurve, QEvent, QUrl
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap, QPen, QBrush, QFontMetrics, QPainterPath, QLinearGradient
from PySide6.QtWidgets import (
    QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox,
    QColorDialog, QFontComboBox, QComboBox, QDialogButtonBox, QSystemTrayIcon, QMenu,
    QMessageBox, QScrollArea, QFrame, QStackedWidget, QSizePolicy, QPlainTextEdit, QGraphicsOpacityEffect
)

DEFAULT = {
    "presets": [30, 60, 120, 300, 600], "preset_format": 2, "font": "Segoe UI", "font_size": 100,
    "text_color": "#000000", "background_color": "#DDA64B",
    "accent_color": "#43E5AD", "opacity": 95, "always_on_top": True,
    "sound": False, "alert_sound": "Double Beep", "final_pips": False, "start_with_windows": False, "x": None, "y": None, "width": None, "height": None,
}


# Original, synthesised classroom alert sounds; no external sound files required.
ALERT_SOUNDS = ("Bell", "Double Beep", "Playful Upward", "Confetti Pop")
_AUDIO_CACHE = {}


def _synth_sound(name):
    """Build a short 16-bit mono WAV in the temporary directory on first use."""
    if name in _AUDIO_CACHE:
        return _AUDIO_CACHE[name]
    if name in ("Final pip", "Double Beep"):
        return _woodblock_sound(name)
    rate = 22050
    length = {"Bell": 2.1, "Double Beep": 0.65, "Playful Upward": 1.35, "Final pip": 0.13}.get(name, 0)
    if not length:
        return None
    samples = []
    for i in range(int(rate * length)):
        t = i / rate
        if name == "Bell":
            # Inharmonic partials and individually decaying resonances approximate
            # a struck brass bell, rather than a pitched electronic sine tone.
            strike = min(1.0, t / .0025)
            partials = ((1.0, 1.00, 2.0), (.46, 2.01, 3.2),
                        (.24, 2.68, 4.7), (.17, 3.91, 6.0),
                        (.11, 5.43, 8.0), (.08, 6.82, 10.0))
            fundamental = 740.0
            signal = strike * sum(
                amp * math.exp(-decay * t) * math.sin(2 * math.pi * fundamental * ratio * t)
                for amp, ratio, decay in partials
            ) * .39
            # A very brief, soft high-frequency strike gives the bell definition.
            signal += .065 * math.exp(-85 * t) * math.sin(2 * math.pi * 3900 * t)
        elif name == "Playful Upward":
            # Warm, rounded rising flourish: softened attacks, lower register,
            # almost pure sine tones and gentle overlapping decays.
            notes = ((0.00, .22, 466.16), (.20, .22, 587.33),
                     (.40, .23, 698.46), (.63, .66, 932.33))
            signal = 0.0
            for start, duration, freq in notes:
                age = t - start
                if 0 <= age < duration + .18:
                    attack = min(1.0, age / .035)
                    decay = math.exp(-2.5 * max(0.0, age - .09))
                    tail = min(1.0, max(0.0, (duration + .18 - age) / .17))
                    signal += .18 * attack * decay * tail * (
                        math.sin(2 * math.pi * freq * age) +
                        .045 * math.sin(2 * math.pi * 2 * freq * age))
        elif name == "Double Beep":
            pulse = (0 <= t < .16) or (.30 <= t < .46)
            phase = t if t < .30 else t - .30
            env = min(1, phase / .012, (.16 - phase) / .025) if pulse else 0
            signal = .36 * max(0, env) * math.sin(2 * math.pi * 880 * t)
        else:
            env = min(1, t / .012, (length - t) / .025)
            signal = .26 * max(0, env) * math.sin(2 * math.pi * 880 * t)
        samples.append(struct.pack('<h', int(max(-1, min(1, signal)) * 32767)))
    folder = Path(tempfile.gettempdir()) / "TeacherTimerSounds"
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / (name.lower().replace(' ', '_') + '.wav')
    with wave.open(str(file), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b''.join(samples))
    _AUDIO_CACHE[name] = str(file)
    return str(file)


# The exact Soft Woodblock sample chosen for the five-second pips.
# Store a single strike in the script so packaged Windows builds need no asset.
_WOODBLOCK_PCM_ZLIB_B64 = (
    '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'
)

def _woodblock_sound(name):
    """Create clean single/double strikes from the same soft woodblock sample."""
    if name in _AUDIO_CACHE:
        return _AUDIO_CACHE[name]
    import array
    strike = zlib.decompress(base64.b64decode(''.join(_WOODBLOCK_PCM_ZLIB_B64)))
    # The embedded strike is mono, signed 16-bit PCM at 22,050 Hz.
    # Shape a gentle release so the second strike cannot produce a click.
    samples = array.array('h')
    samples.frombytes(strike)
    fade_count = min(1102, len(samples) // 3)  # 50 ms
    for i in range(fade_count):
        idx = len(samples) - fade_count + i
        samples[idx] = int(samples[idx] * (1.0 - i / fade_count))
    strike = samples.tobytes()

    if name == "Double Beep":
        # Exactly two clean hits, 420 ms apart (onset to onset).
        # Use actual binary zero PCM, not the ASCII text '\\x00'.
        interval_frames = int(22050 * .42)
        silence_frames = max(0, interval_frames - len(samples))
        data = strike + bytes(silence_frames * 2) + strike
    else:
        data = strike

    folder = Path(tempfile.gettempdir()) / "TeacherTimerSounds"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("soft_woodblock_double_v2.wav" if name == "Double Beep"
                     else "soft_woodblock_pip_v2.wav")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(data)
    _AUDIO_CACHE[name] = str(path)
    return str(path)


# User-provided cork-pop recording, converted losslessly to WAV for Qt playback.
# Compressed and embedded so the single Python file works without extra assets.
_CORK_WAV_ZLIB_B64 = (
    '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'
    'zRY/XZ8xn5WzvCKCP+9IWVzpQcrAgFl9KytmzphtPc8LDb2XFaP/fa0vum6G79hLWXik/DdFeg5mMyM341VPeJYj6G+Dv7uaij8D'
    'ZcVH3PM+f861PLL2BilLa0iZ+NXygqhD/WIYfQ4K/MdIegHXZ97b82LaPymWLFtNMyEm43U/2HOvsJLVlVN8+ZdmkY/4WzUr9ZJx'
    'RuufXU3H//O/x86Lr8Oi+PCf4qM8M8eHrHjKvw0sw33mNr/oGkaZ42fWjEIzXE0pa0bJao9SJr34YgVFM4xaVuj+O5aSsrx2ju9e'
    '//76TDTLzEXy4+6M3vv3V+x5/uwqzcAg/+k1of7p1aCer8vIf+XaVCwTGtnfxFZ/tWx9TsnqGkPSP7K89AJOlDJp8X9esuZKSxYq'
    'IWORM2UqL8426P+gZMT0v70KXNZXVfNX+n9/vbL//vZilD9f67G/vbbbf3KtvBdf6y0j+7z4ymP//Ep0//66Z3/nxS/K3fyV1H9+'
    'Pb7/mVVfjMp/ih2eSUX+0yv/PZ8LM14ZzNsi7385//4qgfQ/vnbgP6nFPzf2f+e/Xd9/erXErFr04gj7ondoFhE3Y2bzvHpepJf+'
    'bxeSgcv/3fj+0yhB/4djRf71VSL//TUyaabbv2O9rBQXJf+G9/9fXhn1v1WXPwO9mOsz8l3GX/2/avP/1ivjZm/ZW/aWvWVv2Vv2'
    'lr1lb9lb9pa9ZW/ZW/aWvWVv2Vv2lr1lb9lb9pa9ZW/ZW/aWvWVv2Vv2lr1lb9nbP9/+6fEn/t/LfKzS845eyvpM8H931MuLjox8'
    'UZsytsH7qf/9845H/b+zZXVUrO9Rnf6fZ7RhVr/637ple9f/f7b/A0VP0E0='
)


def cork_sound_path():
    folder = Path(tempfile.gettempdir()) / "TeacherTimerSounds"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "user_cork_pop.wav"
    if not path.is_file():
        path.write_bytes(zlib.decompress(base64.b64decode(''.join(_CORK_WAV_ZLIB_B64))))
    return path


def play_wav_native(path):
    """Play a local WAV on Windows without relying on Qt Multimedia."""
    try:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME |
                           winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except (OSError, RuntimeError, ValueError):
        QApplication.beep()


def play_alert_sound(name):
    try:
        path = _synth_sound(name)
        if sys.platform == "win32":
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        else:
            QApplication.beep()
    except (OSError, RuntimeError):
        QApplication.beep()


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



def top_position_file():
    """Top-mode horizontal preference, separate from legacy JSON settings."""
    return settings_file().with_name("settings.ini")


def load_top_position():
    parser = configparser.ConfigParser()
    try:
        parser.read(top_position_file(), encoding="utf-8")
        return float(parser.get("Top mode", "horizontal_position"))
    except (OSError, ValueError, configparser.Error):
        return 0.5


def save_top_position(fraction):
    parser = configparser.ConfigParser()
    try:
        parser.read(top_position_file(), encoding="utf-8")
    except configparser.Error:
        pass
    if not parser.has_section("Top mode"):
        parser.add_section("Top mode")
    parser.set("Top mode", "horizontal_position", str(max(0., min(1., fraction))))
    with top_position_file().open("w", encoding="utf-8") as file:
        parser.write(file)


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
    # Preserve existing choices under their new names; removed choices fall back to the default.
    sound_names = {"Classic bell": "Bell", "Digital beep": "Double Beep", "Silent": "Double Beep"}
    selected_sound = result.get("alert_sound", DEFAULT["alert_sound"])
    selected_sound = sound_names.get(selected_sound, selected_sound)
    result["alert_sound"] = selected_sound if selected_sound in ALERT_SOUNDS else DEFAULT["alert_sound"]
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
    """Use lighter controls on dark themes and darker controls on light themes."""
    base = QColor(background)
    channels = [base.redF(), base.greenF(), base.blueF()]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
              for c in channels]
    luminance = sum(a * b for a, b in zip(linear, (0.2126, 0.7152, 0.0722)))
    if luminance < 0.18:
        # Mix towards white, retaining the hue of the chosen background.
        def lighten(amount):
            return QColor.fromRgbF(*(c + (1 - c) * amount for c in channels)).name()
        return lighten(0.18), lighten(0.28)
    def darken(factor):
        return QColor.fromRgbF(*(c * factor for c in channels)).name()
    return darken(0.82), darken(0.65)


def accent_hover_colour(accent):
    """A stronger shade of the accent, independent of the background theme."""
    colour = QColor(accent)
    return QColor.fromRgbF(*(channel * 0.80 for channel in
                             (colour.redF(), colour.greenF(), colour.blueF()))).name()


def preset_label(seconds):
    """Use a short label that is unambiguous for second-based presets."""
    return f"{seconds // 60}m" if seconds % 60 == 0 else f"{seconds}s" if seconds < 60 else f"{seconds // 60}m {seconds % 60}s"


def save_settings(settings):
    settings_file().write_text(json.dumps(settings, indent=2), encoding="utf-8")



STARTUP_REGISTRY_NAME = "Teacher Timer"


def startup_command():
    """Use the stable, extracted EXE path; never a PyInstaller temp directory."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" --startup-tray'
    return None


def is_windows_startup_enabled():
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            value, _ = winreg.QueryValueEx(key, STARTUP_REGISTRY_NAME)
            return value in (startup_command(), startup_command().removesuffix(" --startup-tray")) if startup_command() else False
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
        k = self.kind
        color = QColor('#ffffff' if getattr(window, 'alert_active', False)
                       else getattr(window, "settings", {}).get("text_color", "#FFFFFF"))
        if k in ('play', 'pause') and not getattr(window, 'alert_active', False):
            accent = QColor(getattr(window, 'settings', {}).get('accent_color', '#43E5AD'))
            # Keep play/pause visible on both pale and dark accent backgrounds.
            color = QColor('#101820') if accent.lightnessF() > 0.55 else QColor('#ffffff')
        pen = QPen(color, 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
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
        elif k in ("zoom_out", "zoom_in"):
            # Small and large magnifying glasses, respectively.
            from PySide6.QtCore import QRectF
            if k == "zoom_out":
                painter.drawEllipse(QRectF(-10, -11, 13, 13))
                painter.drawLine(1, 0, 11, 10)
            else:
                painter.drawEllipse(QRectF(-13, -14, 20, 20))
                painter.drawLine(4, 3, 14, 13)
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
        # Give the warning its own complete palette. Without this, the
        # fullscreen window's generic QPushButton rules leak into QMessageBox,
        # leaving an unpainted OK button and unreadable dark-mode text.
        alert.setObjectName("teacherTimerWarning")
        alert.setStyleSheet("""
            QMessageBox#teacherTimerWarning {
                background-color: #252932;
                color: #f5f5f5;
            }
            QMessageBox#teacherTimerWarning QLabel {
                background: transparent;
                color: #f5f5f5;
                font-size: 14px;
            }
            QMessageBox#teacherTimerWarning QPushButton {
                background-color: #414957;
                color: #ffffff;
                border: 1px solid #667080;
                border-radius: 6px;
                padding: 7px 24px;
                min-width: 72px;
                min-height: 24px;
            }
            QMessageBox#teacherTimerWarning QPushButton:hover {
                background-color: #536073;
            }
            QMessageBox#teacherTimerWarning QPushButton:pressed {
                background-color: #343b47;
            }
        """)
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
        self.resize(490, 683)
        self.values = dict(settings)
        self.restore_top_position = False
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
        form.addRow("Font", self.font)
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
        self.sound = QCheckBox("Play sound when finished")
        self.sound.setChecked(settings["sound"])
        form.addRow(self.sound)
        self.alert_sound = QComboBox()
        self.alert_sound.addItems(ALERT_SOUNDS)
        self.alert_sound.setCurrentText(settings.get("alert_sound", "Double Beep"))
        sound_row = QHBoxLayout()
        sound_row.addWidget(self.alert_sound, 1)
        preview = QPushButton("Preview")
        self.cork_preview = QSoundEffect(self)
        self.cork_preview.setSource(QUrl.fromLocalFile(str(cork_sound_path())))
        self.cork_preview.setVolume(0.8)
        preview.clicked.connect(self.preview_completion_sound)
        sound_row.addWidget(preview)
        form.addRow("Completion sound", sound_row)
        self.final_pips = QCheckBox("Single pip at each of the final 5 seconds")
        self.final_pips.setChecked(settings.get("final_pips", False))
        form.addRow(self.final_pips)
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
        restore = QPushButton("Restore Defaults")
        restore.setToolTip("Reset all preferences, including Top mode position")
        restore.clicked.connect(self.restore_defaults)
        outer.addWidget(restore)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def restore_defaults(self):
        answer = QMessageBox.question(
            self, "Restore defaults",
            "Restore all Teacher Timer settings to their defaults?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.values = dict(DEFAULT)
        for i, (value, unit) in enumerate(self.preset_inputs):
            seconds = DEFAULT["presets"][i]
            unit.setCurrentIndex(1 if seconds % 60 == 0 else 0)
            value.setValue(seconds // 60 if seconds % 60 == 0 else seconds)
        self.font.setCurrentFont(QFont(DEFAULT["font"]))
        for key in self.colors:
            self.colors[key].setText(DEFAULT[key])
            self.update_color_preview(key)
        self.opacity.setValue(DEFAULT["opacity"])
        self.top.setChecked(DEFAULT["always_on_top"])
        self.sound.setChecked(DEFAULT["sound"])
        self.alert_sound.setCurrentText(DEFAULT["alert_sound"])
        self.final_pips.setChecked(DEFAULT["final_pips"])
        self.startup.setChecked(DEFAULT["start_with_windows"])
        self.restore_top_position = True
        self.accept()

    def preview_completion_sound(self):
        selected = self.alert_sound.currentText()
        if selected == "Confetti Pop":
            self.cork_preview.stop()
            self.cork_preview.play()
        else:
            play_alert_sound(selected)

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
                           alert_sound=self.alert_sound.currentText(), final_pips=self.final_pips.isChecked(),
                           start_with_windows=self.startup.isChecked())
        super().accept()


class ProgressStrip(QWidget):
    """Flat countdown strip with a short, time-fading trail as it empties."""
    def __init__(self, timer):
        super().__init__()
        self.timer = timer
        self.setFixedHeight(84)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._last_edge = None
        self._trail = []
        self._last_colour = None
        self._last_max = None

    def reset_trail(self):
        self._last_edge = None
        self._trail.clear()
        self._last_colour = None
        self._last_max = None

    def paintEvent(self, event):
        if not self.timer.progress_started or self.timer.remaining <= 0:
            self.reset_trail()
            return
        maximum = max(0.001, self.timer.progress_max)
        ratio = min(1.0, max(0.0, self.timer.remaining / maximum))
        seconds = self.timer.remaining
        colour = '#e5404b' if seconds <= 10 else '#e5e540' if seconds < 30 else '#43E5AD'
        edge = self.width() * ratio
        now = time.monotonic()
        lifetime = 0.42

        # Remember recently emptied strips, then fade those strips with time.
        # This is a temporal fade, not a gradient attached to the current edge.
        if (self._last_edge is None or self._last_max != maximum
                or self._last_colour != colour or edge > self._last_edge + 0.5):
            self._trail.clear()
        elif edge < self._last_edge:
            self._trail.append((edge, self._last_edge, now))
        self._last_edge = edge
        self._last_max = maximum
        self._last_colour = colour
        self._trail = [(lo, hi, born) for lo, hi, born in self._trail
                       if now - born < lifetime and hi > edge]

        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 95))
        if edge > 0:
            painter.fillRect(QRectF(0, 0, edge, self.height()), QColor(colour))
        for lo, hi, born in self._trail:
            left = max(edge, lo)
            if hi <= left:
                continue
            trail_colour = QColor(colour)
            trail_colour.setAlpha(round(200 * max(0.0, 1.0 - (now - born) / lifetime)))
            painter.fillRect(QRectF(left, 0, hi - left, self.height()), trail_colour)
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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if self.objectName() == 'dockDisplay':
            owner = self.window()
            bg = QColor('#e5404b' if getattr(owner, 'alert_active', False)
                        else owner.settings['background_color'])
            bg.setAlphaF(0.80)
            # Draw a single translucent shape: square top corners and rounded
            # bottom corners. Overlapping translucent fills darken the colour.
            rect = QRectF(self.rect())
            radius = min(12.0, rect.width() / 2, rect.height() / 2)
            path = QPainterPath()
            path.moveTo(rect.left(), rect.top())
            path.lineTo(rect.right(), rect.top())
            path.lineTo(rect.right(), rect.bottom() - radius)
            path.quadTo(rect.right(), rect.bottom(), rect.right() - radius, rect.bottom())
            path.lineTo(rect.left() + radius, rect.bottom())
            path.quadTo(rect.left(), rect.bottom(), rect.left(), rect.bottom() - radius)
            path.closeSubpath()
            painter.fillPath(path, bg)
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


class ConfettiSlip:
    """One paper slip with independently evolving position, air and orientation."""

    def __init__(self, rng, x, y, vx, vy, delay, colour):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.delay = delay
        self.colour = QColor(colour)
        self.width = rng.uniform(5.0, 10.0)
        self.height = rng.uniform(3.0, 6.5)
        self.angle = rng.uniform(-32, 32)
        self.angular_velocity = rng.uniform(-14, 14)
        self.tilt_target = rng.uniform(-28, 28)
        self.tilt_change = rng.uniform(.13, .55)
        self.tilt_clock = rng.uniform(0, self.tilt_change)
        self.face_phase = rng.uniform(0, 2 * math.pi)
        self.face_rate = rng.uniform(2.1, 6.4)
        self.face_width = 1.0
        self.drift = rng.uniform(-16, 16)
        self.wind_target = rng.uniform(-35, 35)
        self.wind_change = rng.uniform(.18, .85)
        self.wind_clock = rng.uniform(0, self.wind_change)
        self.drag = rng.uniform(2.0, 5.5)
        self.terminal_broad = rng.uniform(28, 68)
        self.terminal_edge = rng.uniform(105, 195)
        self.mass_response = rng.uniform(1.8, 4.5)
        self.flutter_kick = rng.uniform(4, 16)
        self.age = 0.0
        self.active = False

    def step(self, dt, elapsed, rng):
        if elapsed < self.delay:
            return
        if not self.active:
            self.active = True
            # A late-spawning slip should begin at its origin.
            self.age = 0.0
        self.age += dt
        self.wind_clock -= dt
        if self.wind_clock <= 0:
            self.wind_target = rng.uniform(-58, 58)
            self.wind_change = rng.uniform(.20, .95)
            self.wind_clock = self.wind_change

        self.tilt_clock -= dt
        if self.tilt_clock <= 0:
            self.tilt_target = rng.uniform(-37, 37)
            self.tilt_change = rng.uniform(.17, .72)
            self.tilt_clock = self.tilt_change

        # Each piece meets changing air currents at different moments.
        self.drift += (self.wind_target - self.drift) * min(1.0, dt * 2.5)
        self.vx += ((self.drift - self.vx) * self.drag +
                    rng.uniform(-self.flutter_kick, self.flutter_kick)) * dt

        # Apparent edge-on/broadside presentation changes air resistance.
        self.face_phase += self.face_rate * dt
        broadside = abs(math.cos(self.face_phase))
        self.face_width = max(.12, broadside)
        terminal = (self.terminal_broad * broadside +
                    self.terminal_edge * (1.0 - broadside))
        # Paper rises from the launch, slows, then settles into its own descent.
        self.vy += (terminal - self.vy) * min(1.0, dt * self.mass_response)
        self.vy += rng.uniform(-12, 12) * dt

        # Damped rocking toward a shifting tilt target; no endless spinning.
        angular_accel = (self.tilt_target - self.angle) * 18.0 - self.angular_velocity * 9.0
        self.angular_velocity += angular_accel * dt
        self.angle += self.angular_velocity * dt
        self.angle = max(-50.0, min(50.0, self.angle))
        self.x += self.vx * dt
        self.y += self.vy * dt


class RedConfetti(QWidget):
    """Short-lived, click-through confetti with independently simulated slips."""

    def __init__(self, timer, mode):
        import random
        self.mode = mode
        self.timer_owner = timer
        self.started = time.monotonic()
        self.last_frame = self.started
        self.duration = {'top': 5.5, 'float': 4.0, 'full': 6.5}[mode]
        self.rng = random.Random()
        if mode == 'full':
            parent = timer.presentation
            super().__init__(parent)
            self.setGeometry(parent.rect())
            self.origin = None
        else:
            super().__init__(None)
            timer_pos = timer.mapToGlobal(QPoint(timer.width() // 2, timer.height() // 2))
            screen = QApplication.screenAt(timer_pos) or timer.screen() or QApplication.primaryScreen()
            screen_rect = screen.geometry()
            self.setGeometry(screen_rect)
            local = timer.mapToGlobal(QPoint(0, 0)) - screen_rect.topLeft()
            self.origin = (local.x(), local.y(), timer.width(), timer.height())
            self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                                Qt.WindowType.WindowStaysOnTopHint |
                                Qt.WindowType.WindowDoesNotAcceptFocus |
                                Qt.WindowType.WindowTransparentForInput)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        self.pieces = []
        palette = ('#ff9299', '#ffb5ba', '#ffd6d9', '#ad1425', '#871020', '#6b0b18')
        for _ in range({'top': 85, 'float': 72, 'full': 150}[mode]):
            r = self.rng
            if mode == 'top':
                ox, oy, w, h = self.origin
                x = ox + r.uniform(.12, .88) * w
                y = oy + h - r.uniform(0, 8)
                vx, vy = r.uniform(-80, 80), r.uniform(-20, 55)
                delay = r.uniform(0, .75)
            elif mode == 'float':
                ox, oy, w, h = self.origin
                side = r.randrange(4)
                if side == 0:
                    x, y = ox - 5, oy + r.uniform(0, h)
                    vx, vy = r.uniform(-390, -175), r.uniform(-280, 25)
                elif side == 1:
                    x, y = ox + w + 5, oy + r.uniform(0, h)
                    vx, vy = r.uniform(175, 390), r.uniform(-280, 25)
                elif side == 2:
                    x, y = ox + r.uniform(0, w), oy - 5
                    vx, vy = r.uniform(-270, 270), r.uniform(-390, -180)
                else:
                    x, y = ox + r.uniform(0, w), oy + h + 5
                    vx, vy = r.uniform(-270, 270), r.uniform(60, 210)
                delay = r.uniform(0, .15)
            else:
                x = r.uniform(0, self.width())
                y = r.uniform(-45, 0)
                vx, vy = r.uniform(-55, 55), r.uniform(15, 95)
                delay = r.uniform(0, 1.7)
            self.pieces.append(ConfettiSlip(r, x, y, vx, vy, delay,
                                            r.choice(palette)))
        self.animation = QTimer(self)
        self.animation.setInterval(25)
        self.animation.timeout.connect(self.advance)
        self.animation.start()
        self.show()
        self.raise_()
        if mode == 'float':
            timer.raise_()

    def advance(self):
        now = time.monotonic()
        elapsed = now - self.started
        if elapsed >= self.duration:
            self.animation.stop()
            self.close()
            # Keep the Qt object valid until the next animation replaces it.
            return
        # Limit huge time steps after Windows sleep or a busy GUI frame.
        dt = min(.05, max(.001, now - self.last_frame))
        self.last_frame = now
        for slip in self.pieces:
            slip.step(dt, elapsed, self.rng)
        self.update()

    def paintEvent(self, event):
        remaining = self.duration - (time.monotonic() - self.started)
        fade = max(0.0, min(1.0, remaining / .8))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for slip in self.pieces:
            if not slip.active:
                continue
            if (slip.y < -20 or slip.y > self.height() + 20 or
                    slip.x < -20 or slip.x > self.width() + 20):
                continue
            painter.save()
            painter.translate(slip.x, slip.y)
            painter.rotate(slip.angle)
            colour = QColor(slip.colour)
            colour.setAlphaF(fade)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            visible_width = slip.width * slip.face_width
            painter.drawRect(QRectF(-visible_width / 2, -slip.height / 2,
                                    visible_width, slip.height))
            painter.restore()
        painter.end()


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
        self.text_smaller = IconButton('zoom_out', lambda: self.resize_instructions(-2), size=44)
        self.text_larger = IconButton('zoom_in', lambda: self.resize_instructions(2), size=44)
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
            preset.setFixedHeight(58)
            preset.setMinimumWidth(0)
            preset.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            font = QFont(timer.settings['font'])
            font.setPixelSize(20)
            font.setBold(True)
            preset.setFont(font)
            bottom.addWidget(preset, 1)
            self.preset_buttons.append(preset)
        layout.addLayout(bottom)
        self.apply_theme()
        QApplication.instance().installEventFilter(self)

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
        self.instructions_editor.document().setDefaultFont(font)
        # Qt draws placeholder text using the editor's styled font. Explicitly
        # update the widget's font-size rule too, so zoom controls affect the
        # placeholder even when the parent window has an active stylesheet.
        self.instructions_editor.setStyleSheet(
            f"font-size: {self.instructions_font_size}px;"
        )
        self.instructions_editor.viewport().update()

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
        # Consume Enter on the time field before Qt can propagate the same
        # key press to the window after commit_time switches the active widget.
        if (obj is self.time_input
                and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
            if not event.isAutoRepeat():
                self.commit_time()
            return True
        # Keyboard shortcuts work even when a child control has focus. Leave
        # text editors alone so spaces can be typed and Enter can commit MMSS.
        if (event.type() == QEvent.Type.KeyPress
                and isinstance(obj, QWidget)
                and (obj is self or self.isAncestorOf(obj))
                and not isinstance(obj, (QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox))
                and not event.isAutoRepeat()):
            if event.key() == Qt.Key.Key_Space and self.display_stack.currentWidget() is not self.time_input:
                self.timer.toggle()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.edit_time()
                return True
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
        self.progress.reset_trail()
        self.progress_animation.stop()
        self.progress_animation.setStartValue(self.progress_effect.opacity())
        self.progress_animation.setEndValue(1.0)
        self.progress_animation.start()
        self.progress.update()

    def hide_progress(self):
        self.progress.reset_trail()
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
        play_bg = button_bg if self.alert_active else s["accent_color"]
        play_hover = button_hover if self.alert_active else accent_hover_colour(s["accent_color"])
        top_bg = 'transparent'
        self.setStyleSheet(f"""
            PresentationWindow {{ background: {background}; }}
            QLabel, QPushButton#fullscreenDisplay {{ color: {foreground}; background: transparent; border: none; }}
            QPushButton {{ background: {button_bg}; border: none; border-radius: 14px; }}
            QPushButton:hover {{ background: {button_hover}; }}
            QPushButton#play {{ background: {play_bg}; }}
            QPushButton#play:hover {{ background: {play_hover}; }}
            QPushButton#topButton, QPushButton#topButton:hover {{ background: {top_bg}; }}
            QLineEdit#fullscreenTimeInput {{ background: rgba(255,255,255,25); color: {foreground}; border: 2px solid {s['accent_color']}; border-radius: 12px; }}
            QPushButton#fullscreenPreset {{ color: {foreground}; }}
            QFrame#instructionsPanel {{ border: 2px solid {button_bg}; border-radius: 12px; background: transparent; }}
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


class DraggableTopClock(FixedSlotClock):
    """Drag horizontally to reposition; a click still restores Float mode."""
    def __init__(self, label, owner):
        super().__init__(label)
        self.owner = owner
        self.drag_start = None
        self.start_x = 0
        self.was_dragged = False
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start = event.globalPosition().toPoint()
            self.start_x = self.owner.x()
            self.was_dragged = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint().x() - self.drag_start.x()
            if abs(delta) >= QApplication.startDragDistance():
                self.was_dragged = True
            if self.was_dragged:
                self.owner.move_top_horizontally(self.start_x + delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.drag_start is not None and event.button() == Qt.MouseButton.LeftButton:
            dragged = self.was_dragged
            self.drag_start = None
            self.was_dragged = False
            if dragged:
                self.owner.remember_top_position()
            else:
                QTimer.singleShot(0, self.owner.toggle_dock)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class TeacherTimer(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.cork_effect = QSoundEffect(self)
        self.cork_effect.setSource(QUrl.fromLocalFile(str(cork_sound_path())))
        self.cork_effect.setVolume(0.8)
        self.duration = self.settings["presets"][0]
        self.remaining = float(self.duration)
        self.deadline = None
        self.running = False
        self.finished = False
        self.last_pip_second = None
        self.alert_active = False
        self.minimized_to_tray = False
        self.progress_max = 0.0
        self.progress_started = False
        self.progress_needs_initialising = True
        self.docked = False
        self.top_horizontal_fraction = load_top_position()
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
        self.fullscreen_button = IconButton("fullscreen", self.enter_presentation, "topButton", 32)
        self.fullscreen_button.setToolTip("Presentation Mode (F11)")
        bar_layout.addWidget(self.fullscreen_button)
        settings_button = IconButton("settings", self.open_settings, "topButton", 32)
        self.settings_button = settings_button
        settings_button.setToolTip("Settings")
        bar_layout.addWidget(settings_button)
        minimize_button = IconButton("minimize", self.minimize_to_tray, "topButton", 32)
        self.minimize_button = minimize_button
        minimize_button.setToolTip("Minimise to tray")
        bar_layout.addWidget(minimize_button)
        close_button = IconButton("close", self.quit_app, "topButton", 32)
        self.close_button = close_button
        close_button.setToolTip("Exit Teacher Timer")
        bar_layout.addWidget(close_button)
        body.addWidget(bar)
        body.addSpacing(12)
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
        left.addWidget(self.display_stack, stretch=1, alignment=Qt.AlignmentFlag.AlignHCenter)
        left.addSpacing(12)
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
        self.preset_box.setSpacing(5)
        body.addLayout(self.preset_box)
        # The complete interface is hidden in dock mode, leaving only a clickable time.
        self.dock_display = DraggableTopClock("05:00", self)
        self.dock_display.setObjectName("dockDisplay")
        self.dock_display.setToolTip("Click to restore the full timer")
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
        presets_width = len(self.settings["presets"]) * 54 + max(0, len(self.settings["presets"]) - 1) * 6
        width = max(left_width, presets_width) + 18 + 28 + 24
        height = max(190, clock_height + 50 + 43 + 32 + 32 + 24)
        if not self.docked:
            self.setFixedSize(width, height)
        # Dock mode has its own constant font size, independent of this setting.
        dock_font = QFont(self.settings["font"])
        dock_font.setBold(True)
        dock_font.setPixelSize(48)
        self.dock_display.setFont(dock_font)
        dock_metrics = QFontMetrics(dock_font)
        self.dock_display.setFixedSize(FixedSlotClock.text_width(dock_font, template) + 24,
                                       dock_metrics.height() + 6)  # 3px above/below instead of 6px

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

    def minimize_to_tray(self):
        self.minimized_to_tray = True
        self.hide()

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
        # Consume Enter on the time field before Qt can propagate the same
        # key press to the window after commit_time switches the active widget.
        if (obj is self.time_input
                and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
            if not event.isAutoRepeat():
                self.commit_time()
            return True
        # Keyboard shortcuts work even when a child control has focus. Leave
        # text editors alone so spaces can be typed and Enter can commit MMSS.
        if (event.type() == QEvent.Type.KeyPress
                and isinstance(obj, QWidget)
                and (obj is self or self.isAncestorOf(obj))
                and not isinstance(obj, (QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox))
                and not event.isAutoRepeat()):
            if event.key() == Qt.Key.Key_Space and self.display_stack.currentWidget() is not self.time_input:
                self.toggle()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.show_normal() if self.docked else None
                self.edit_time()
                return True
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
        if self.windowFlags() != flags:
            self.setWindowFlags(flags)
        bg = QColor("#e5404b" if self.alert_active else s["background_color"])
        bg.setAlphaF(s["opacity"] / 100)
        rgba = f"rgba({bg.red()}, {bg.green()}, {bg.blue()}, {bg.alpha()})"
        foreground = "#ffffff" if self.alert_active else s["text_color"]
        button_bg, button_hover = themed_button_colours('#e5404b' if self.alert_active else s['background_color'])
        play_bg = button_bg if self.alert_active else s["accent_color"]
        play_hover = button_hover if self.alert_active else accent_hover_colour(s["accent_color"])
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
            QPushButton#play:hover {{ background: {play_hover}; }}
            QPushButton#topButton, QPushButton#topButton:hover {{ background: {top_bg}; padding: 0px; }}
        """)
        self.display.set_clock_colour(foreground)
        self.dock_display.set_clock_colour(foreground)
        # Docked display is a sibling of panel, so style it independently.
        dock_bg = QColor("#e5404b" if self.alert_active else s["background_color"])
        dock_bg.setAlphaF(0.80)
        dock_rgba = f"rgba({dock_bg.red()}, {dock_bg.green()}, {dock_bg.blue()}, {dock_bg.alpha()})"
        self.dock_display.setStyleSheet('QPushButton { background: transparent; border: none; padding: 0px; }')
        self.dock_display.update()
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
            font.setPixelSize(18)
            font.setBold(True)
            b.setFont(font)
            b.setMinimumWidth(0)
            b.setMinimumHeight(39)
            self.preset_box.addWidget(b, 1)
            self.preset_buttons.append((seconds, b))
        self.refresh()

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
                # Restarting a completed countdown must also dismiss the red alert
                # styling, whether triggered by Space or the Play button.
                self.clear_alert()
                if self.presentation is not None:
                    self.presentation.clear_alert()
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
        self.last_pip_second = None
        self.mark_new_time()
        self.refresh()

    def tick(self):
        if not self.running:
            return
        self.remaining = max(0.0, self.deadline - time.monotonic())
        seconds_left = max(0, math.ceil(self.remaining))
        if (self.settings.get("final_pips", False) and self.running and
                1 <= seconds_left <= 5 and seconds_left != self.last_pip_second):
            self.last_pip_second = seconds_left
            play_alert_sound("Final pip")
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
            if self.minimized_to_tray:
                # Bring the completed timer back in Float mode without clearing its alert.
                self.restore_finished_alert()
            # Confetti Pop is an easter egg: both the recording and the visual
            # effect are exclusive to this completion sound selection.
            if self.settings["sound"]:
                selected = self.settings.get("alert_sound", "Double Beep")
                if selected == "Confetti Pop":
                    previous_overlay = getattr(self, "confetti_overlay", None)
                    if previous_overlay is not None:
                        # Older builds deleted the underlying Qt object at the
                        # end of an animation. Guard against stale wrappers.
                        from shiboken6 import isValid
                        if isValid(previous_overlay):
                            previous_overlay.close()
                            previous_overlay.deleteLater()
                        self.confetti_overlay = None
                    # Retain the overlay until its own timer completes. Without
                    # a Python reference, the unparented desktop overlay can be
                    # collected immediately after this function returns.
                    if self.presentation is not None:
                        self.confetti_overlay = RedConfetti(self, 'full')
                    elif self.docked:
                        self.confetti_overlay = RedConfetti(self, 'top')
                    else:
                        self.confetti_overlay = RedConfetti(self, 'float')
                    # Windows: play the cork WAV through the same native
                    # backend used by the other completion sounds. QSoundEffect
                    # can silently fail if its multimedia backend is unavailable
                    # or the sample has not finished loading.
                    if sys.platform == "win32":
                        play_wav_native(cork_sound_path())
                    else:
                        self.cork_effect.stop()
                        self.cork_effect.play()
                else:
                    play_alert_sound(selected)
            # The visible red alert already communicates completion.
            # Avoid a redundant Windows notification toast at exactly 00:00.
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
            if dialog.restore_top_position:
                self.top_horizontal_fraction = 0.5
                save_top_position(0.5)
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
        travel = max(0, rect.width() - self.width())
        self.move(rect.x() + round(travel * self.top_horizontal_fraction), rect.y())

    def move_top_horizontally(self, x):
        screen = self.screen() or QApplication.primaryScreen()
        rect = screen.geometry()
        x = max(rect.left(), min(x, rect.right() - self.width() + 1))
        self.move(x, rect.top())

    def remember_top_position(self):
        screen = self.screen() or QApplication.primaryScreen()
        rect = screen.geometry()
        travel = max(0, rect.width() - self.width())
        self.top_horizontal_fraction = max(0., min(1., (self.x() - rect.left()) / travel)) if travel else 0.5
        save_top_position(self.top_horizontal_fraction)

    def toggle_dock(self):
        leaving_top = self.docked
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
        if leaving_top:
            self.clear_alert()
        self.refresh()

    def store_position(self):
        if self.docked:
            return
        self.settings["x"] = self.x()
        self.settings["y"] = self.y()
        save_settings(self.settings)

    def restore_finished_alert(self):
        self.minimized_to_tray = False
        if self.docked:
            self.toggle_dock()
        self.alert_active = True
        self.apply_settings()
        self.show()
        self.raise_()
        self.activateWindow()

    def show_normal(self):
        self.minimized_to_tray = False
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

    startup_tray = "--startup-tray" in sys.argv[1:]

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
    # Upgrade the pre-existing login entry to the silent-start argument.
    if sys.platform == "win32" and is_windows_startup_enabled():
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                saved_command, _ = winreg.QueryValueEx(key, STARTUP_REGISTRY_NAME)
            if saved_command != startup_command():
                set_windows_startup(True)
        except OSError:
            pass
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
    if not startup_tray or not QSystemTrayIcon.isSystemTrayAvailable():
        timer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
