# utils.py

# Standard library imports
import functools
import inspect
import math
import os
import re
import traceback
import urllib.parse
import fnmatch
from typing import List, Optional

# Third-party imports
from PySide6.QtCore import Qt, QTimer, QByteArray, QRect
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from ctypes import CDLL, c_uint
from PySide6.QtWidgets import QApplication, QDialog, QProgressBar, QProgressDialog, QMessageBox

# Local imports
from thumbnail_constants import GREEN, RED, RESET, YELLOW
from photos_library_paths import (
    is_inside_photos_library,
    is_inside_photos_library_resources_or_scopes,
)


def _create_gear_pixmap(color: str) -> QPixmap:
    """Create a gear pixmap (used by create_gear_icon and create_gear_icon_data_url)."""
    pixmap = QPixmap(18, 18)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))

    cx, cy = 9.0, 9.0
    n = 7
    r_out, r_in, r_hub = 7.5, 5.2, 2.3
    step = 2 * math.pi / n
    t_half = step * 0.28

    path = QPainterPath()
    first = True
    for i in range(n):
        base = step * i - math.pi / 2
        pts = [
            (cx + r_in * math.cos(base - step * 0.5 + t_half * 1.1), cy + r_in * math.sin(base - step * 0.5 + t_half * 1.1)),
            (cx + r_out * math.cos(base - t_half), cy + r_out * math.sin(base - t_half)),
            (cx + r_out * math.cos(base + t_half), cy + r_out * math.sin(base + t_half)),
            (cx + r_in * math.cos(base + step * 0.5 - t_half * 1.1), cy + r_in * math.sin(base + step * 0.5 - t_half * 1.1)),
        ]
        for x, y in pts:
            if first:
                path.moveTo(x, y)
                first = False
            else:
                path.lineTo(x, y)
    path.closeSubpath()

    hub = QPainterPath()
    hub.addEllipse(cx - r_hub, cy - r_hub, r_hub * 2, r_hub * 2)
    painter.drawPath(path.subtracted(hub))
    painter.end()
    return pixmap


def create_gear_icon(color: str = "#50c8ff") -> QIcon:
    """Create a gear icon for settings buttons."""
    return QIcon(_create_gear_pixmap(color))


mainWindow = None
def get_main_window():
    global mainWindow
    return mainWindow

def set_main_window(window):
    global mainWindow
    mainWindow = window


def file_string(n: int) -> str:
    return "file" if n == 1 else "files"


# GIL-free sleep function using ctypes
_usleep_libc = None
def _usleep_ms(milliseconds):
    """Sleep for milliseconds without requiring GIL acquisition"""
    global _usleep_libc
    if milliseconds <= 0:
        return
    try:
        if _usleep_libc is None:
            _usleep_libc = CDLL('libc.dylib')  # macOS - cache the CDLL object
        _usleep_libc.usleep(c_uint(int(milliseconds * 1000)))  # Convert ms to microseconds
    except:
        # Fallback to QThread.msleep if ctypes fails
        from PySide6.QtCore import QThread
        QThread.currentThread().msleep(int(milliseconds))


def entry_debug(dump_stack=False):
    stack = inspect.stack()
    # stack[0] is entry_debug, stack[1] is the caller, stack[2] is the caller's caller
    caller_func = stack[1].function if len(stack) > 1 else "<unknown>"
    caller_lineno = stack[1].lineno if len(stack) > 1 else "?"
    caller_caller_func = stack[2].function if len(stack) > 2 else "<unknown>"
    caller_caller_lineno = stack[2].lineno if len(stack) > 2 else "?"
    print(f"DEBUG Traceback: Entered {RED}{caller_func}{RESET} called by {GREEN}{caller_caller_func}{RESET} line {caller_caller_lineno}")
    if dump_stack:
        stack_lines = traceback.format_stack()
        for line in stack_lines[:-4]:
            print(line.replace(" File ",f"File {YELLOW}").replace(" line ",f"{RESET} line "), end='')
        with open("/tmp/exception.txt", "a") as f:
            f.write(f"DEBUG Traceback: Entered {caller_func} line {caller_lineno} (called by {caller_caller_func} line {caller_caller_lineno})\n")
            for line in stack_lines[:-4]:
                f.write(line)

def mutex_debug(mutex_name, action="LOCK"):
    """Log mutex entry/exit with caller information"""
    stack = inspect.stack()
    # stack[0] is mutex_debug, stack[1] is the caller (where mutex is used)
    caller_frame = stack[1] if len(stack) > 1 else None
    if caller_frame:
        caller_func = caller_frame.function
        caller_lineno = caller_frame.lineno
        caller_filename = os.path.basename(caller_frame.filename)
        module_name = os.path.basename(caller_filename).replace('.py', '')
        
        # Suppress logging for frequent queue polling in worker threads to reduce noise
        # Only log when there's actual work or when it's not a polling operation
        if (caller_func == "run" and module_name == "image_cache" and 
            mutex_name == "queue_mutex" and caller_lineno in [95, 99]):
            # This is frequent queue polling - only log if queue has items or on errors
            # We'll check the queue state by looking at the code context
            # For now, suppress all queue polling logs to reduce noise
            return
        
        # Get caller's caller for context
        caller_caller_frame = stack[2] if len(stack) > 2 else None
        if caller_caller_frame:
            caller_caller_func = caller_caller_frame.function
            caller_caller_lineno = caller_caller_frame.lineno
            caller_caller_filename = os.path.basename(caller_caller_frame.filename)
            msg = f"MUTEX {action}: {mutex_name} | Module: {module_name} | Function: {caller_func} (line {caller_lineno}) | Called by: {caller_caller_func} in {caller_caller_filename} (line {caller_caller_lineno})"
        else:
            msg = f"MUTEX {action}: {mutex_name} | Module: {module_name} | Function: {caller_func} (line {caller_lineno})"
        print(msg)
        with open("/tmp/exception.txt", "a") as f:
            f.write(f"{msg}\n")
    else:
        msg = f"MUTEX {action}: {mutex_name} | <unknown caller>"
        print(msg)
        with open("/tmp/exception.txt", "a") as f:
            f.write(f"{msg}\n")
    
# Decorator to print debug info when entering a function, including line numbers
def entry_debug_wrapper(func=None, *, dump_stack=False,showParms=False,printval=None):
    def decorator(inner_func):
        @functools.wraps(inner_func)
        def wrapper(*args, **kwargs):
            stack = inspect.stack()
            if dump_stack or showParms:
                ansi_escape = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
                pad = ""
                left_colored = []
                left_plain = []
                right = []
                for i in range(1, len(stack)):
                    frame = stack[i]
                    code_context = frame.code_context[0].strip() if frame.code_context else "???"
                    module = code_context.rsplit('.', 1)[-1] if '.' in code_context else code_context
                    func = frame.function
                    lineno = frame.lineno
                    filename = os.path.basename(frame.filename)
                    if i < len(stack) - 1:
                        caller_filename = os.path.basename(stack[i + 1].filename)
                        left = f"{pad}{RED}{module}{RESET} called by {GREEN}{func}{RESET}"
                        left_no_ansi = ansi_escape.sub('', left)
                        right_part = f"{caller_filename}{RESET} line {lineno}"
                    else:
                        left = f"{pad}{module}.{RED}{func}{RESET}"
                        left_no_ansi = ansi_escape.sub('', left)
                        right_part = f"{filename}{RESET} line {lineno}"
                    left_colored.append(left)
                    left_plain.append(left_no_ansi)
                    right.append(right_part)
                    pad += "    "
                max_left_len = max((len(part) for part in left_plain), default=80) + 2
                for l_col, l_plain, r_part in zip(left_colored, left_plain, right):
                    response = f"{RESET}DEBUG: {l_col:<{max_left_len + (len(l_col) - len(l_plain))}} {r_part}"
                    print(response[:200])
                    with open("/tmp/exception.txt", "a") as f:
                        f.write(f"{response}\n")
                if showParms:
                    # Improved: use inspect to get real param names and values
                    try:
                        sig = inspect.signature(inner_func)
                        bound = sig.bind(*args, **kwargs)
                        bound.apply_defaults()
                        params_str = ', '.join(f"{k}={v!r}" for k, v in bound.arguments.items())
                    except Exception as e:
                        params_str = f"(Unable to extract params: {e})"
                    response_params = f"\n\tParams: {params_str}"
                    print(response_params)
                    with open("/tmp/exception.txt", "a") as f:
                        f.write(f"{response_params}\n")

            if printval and hasattr(args[0], printval):
                print_value = getattr(args[0], printval)
                print(f"DEBUG: {print_value}")
                with open("/tmp/exception.txt", "a") as f:
                    f.write(f"DEBUG: {printval}={print_value}\n")

            return inner_func(*args, **kwargs)
        return wrapper
    # Support both @entry_debug_wrapper and @entry_debug_wrapper(dump_stack=True)
    if func is not None and callable(func):
        return decorator(func)
    else:
        return decorator

def is_macos_spaces_fullscreen() -> bool:
    """Check if we are in macOS Spaces (true OS fullscreen) mode"""
    try:
        from AppKit import NSApplication
        app = NSApplication.sharedApplication()
        # 4 == NSApplicationPresentationFullScreen (macOS Spaces fullscreen)
        # See: https://developer.apple.com/documentation/appkit/nsapplicationpresentationoptions/nsapplicationpresentationfullscreen
        if hasattr(app, 'presentationOptions') and app.presentationOptions() & 4:
            return True
    except Exception:
        pass
    return False

def get_button_focus_colors() -> tuple:
    """
    Returns the focus colors used for button highlighting.
    This ensures all buttons use the same focus colors.
    
    Returns:
        Tuple of (focus_bg_rgba, focus_border_hex, focus_text_hex)
    """
    try:
        from thumbnail_constants import (
            CURRENT_IMAGE_BACKGROUND_COLOR, CURRENT_IMAGE_BORDER_COLOR,
            BUTTON_FOCUS_TEXT_HEX,
        )
        
        def qtcolor_to_rgba(color):
            return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha() / 255 if color.alpha() != 255 else 1})"
        
        def qtcolor_to_hex(color):
            return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"
        
        focus_bg = qtcolor_to_rgba(CURRENT_IMAGE_BACKGROUND_COLOR)
        focus_border = qtcolor_to_hex(CURRENT_IMAGE_BORDER_COLOR)
        focus_text = BUTTON_FOCUS_TEXT_HEX
    except ImportError:
        focus_bg = "rgba(74, 144, 226, 0.3)"
        focus_border = "#4a90e2"
        focus_text = "#ffffff"
    
    return (focus_bg, focus_border, focus_text)


def get_button_style() -> str:
    """
    Returns the standard button style string for all QPushButton widgets.
    This centralizes button styling application-wide.
    
    Returns:
        CSS stylesheet string for QPushButton styling
    """
    # Get focus colors from centralized function
    focus_bg, focus_border, focus_text = get_button_focus_colors()
    
    from thumbnail_constants import (
        BUTTON_BG_DEFAULT_HEX, BUTTON_TEXT_DEFAULT_HEX, BUTTON_BORDER_DEFAULT_HEX,
        BUTTON_BG_HOVER_HEX, BUTTON_TEXT_HOVER_HEX, BUTTON_BORDER_HOVER_HEX,
        BUTTON_BG_PRESSED_HEX, BUTTON_DEFAULT_BG_HEX, BUTTON_DEFAULT_BORDER_HEX,
        BUTTON_FOCUS_TEXT_HEX,
    )
    
    button_styles = f"""
        QPushButton {{
            background-color: {BUTTON_BG_DEFAULT_HEX};
            color: {BUTTON_TEXT_DEFAULT_HEX};
            border: 1px solid {BUTTON_BORDER_DEFAULT_HEX};
            border-radius: 5px;
            padding: 6px 18px;
            min-width: 100px;
            font-size: 13px;
            font-family: 'Arial Narrow', Arial;
            letter-spacing: 0.5px;
        }}
        QPushButton:default {{
            background-color: {BUTTON_DEFAULT_BG_HEX};
            color: {BUTTON_FOCUS_TEXT_HEX};
            border: 1px solid {BUTTON_DEFAULT_BORDER_HEX};
        }}
        QPushButton:focus {{
            background-color: {focus_bg};
            color: {focus_text};
            border: 1px solid {focus_border};
            outline: none;
        }}
        QPushButton:hover {{
            background-color: {BUTTON_BG_HOVER_HEX};
            color: {BUTTON_TEXT_HOVER_HEX};
            border: 1px solid {BUTTON_BORDER_HOVER_HEX};
        }}
        QPushButton:pressed {{
            background-color: {BUTTON_BG_PRESSED_HEX};
            color: {focus_text};
        }}
    """
    return button_styles


def get_dialog_button_box_style() -> str:
    """
    Returns button style string for QDialogButtonBox QPushButton widgets.
    This adapts the standard button style for use in QDialogButtonBox.
    
    Returns:
        CSS stylesheet string for QDialogButtonBox QPushButton styling
    """
    # Get focus colors from centralized function
    focus_bg, focus_border, focus_text = get_button_focus_colors()
    
    from thumbnail_constants import (
        BUTTON_BG_DEFAULT_HEX, BUTTON_TEXT_DEFAULT_HEX, BUTTON_BORDER_DEFAULT_HEX,
        BUTTON_BG_HOVER_HEX, BUTTON_TEXT_HOVER_HEX, BUTTON_BORDER_HOVER_HEX,
        BUTTON_BG_PRESSED_HEX, BUTTON_DEFAULT_BG_HEX, BUTTON_DEFAULT_BORDER_HEX,
        BUTTON_FOCUS_TEXT_HEX,
    )
    
    return f"""
        QDialogButtonBox QPushButton {{
            background-color: {BUTTON_BG_DEFAULT_HEX};
            color: {BUTTON_TEXT_DEFAULT_HEX};
            border: 1px solid {BUTTON_BORDER_DEFAULT_HEX};
            border-radius: 5px;
            padding: 6px 18px;
            min-width: 100px;
            font-size: 13px;
            font-family: 'Arial Narrow', Arial;
            letter-spacing: 0.5px;
        }}
        QDialogButtonBox QPushButton:default {{
            background-color: {BUTTON_DEFAULT_BG_HEX};
            color: {BUTTON_FOCUS_TEXT_HEX};
            border: 1px solid {BUTTON_DEFAULT_BORDER_HEX};
        }}
        QDialogButtonBox QPushButton:hover {{
            background-color: {BUTTON_BG_HOVER_HEX};
            color: {BUTTON_TEXT_HOVER_HEX};
            border: 1px solid {BUTTON_BORDER_HOVER_HEX};
        }}
        QDialogButtonBox QPushButton:focus {{
            background-color: {focus_bg};
            color: {focus_text};
            border: 1px solid {focus_border};
            outline: none;
        }}
        QDialogButtonBox QPushButton:pressed {{
            background-color: {BUTTON_BG_PRESSED_HEX};
            color: {focus_text};
        }}
    """


def format_file_size(size_bytes: int) -> str:
    """Format file size in bytes to human-readable format (KB, MB, GB)"""
    if size_bytes < 1024 * 1024:  # Less than 1 MB
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:  # Less than 1 GB
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:  # 1 GB or more
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def _resolve_screen_for_styled_dialog(parent):
    """Pick a QScreen for centering: visible window in parent chain, else parent's window, else primary."""
    screen = None
    if parent is not None:
        p = parent
        while p is not None:
            w = p.window()
            if w is not None and w.isVisible():
                screen = w.screen()
                if screen is not None:
                    return screen
            p = p.parentWidget()
        w = parent.window()
        if w is not None:
            screen = w.screen()
            if screen is not None:
                return screen
    app = QApplication.instance()
    return app.primaryScreen() if app else None


def _center_styled_dialog_on_screen(dialog, parent):
    """Center dialog on available area of the resolved screen (after size hint is valid)."""
    screen = _resolve_screen_for_styled_dialog(parent)
    if screen is None:
        return
    dialog.adjustSize()
    geo = screen.availableGeometry()
    fg = dialog.frameGeometry()
    fg.moveCenter(geo.center())
    dialog.move(fg.topLeft())


def ensure_dialog_fits_screen(dialog, parent=None, *, margin: int = 8) -> None:
    """Clamp dialog size/position to the current screen available area."""
    screen = _resolve_screen_for_styled_dialog(parent)
    if screen is None:
        return
    ag = screen.availableGeometry()
    min_w = max(dialog.minimumWidth(), 1)
    min_h = max(dialog.minimumHeight(), 1)
    fg = dialog.frameGeometry()
    w = max(min_w, min(fg.width(), ag.width() - 2 * margin))
    h = max(min_h, min(fg.height(), ag.height() - 2 * margin))
    x, y = fg.x(), fg.y()
    if x + w > ag.right() - margin:
        x = ag.right() - margin - w
    if x < ag.left() + margin:
        x = ag.left() + margin
    if y + h > ag.bottom() - margin:
        y = ag.bottom() - margin - h
    if y < ag.top() + margin:
        y = ag.top() + margin
    rect = QRect(x, y, w, h)
    if not ag.intersects(rect):
        rect.moveCenter(ag.center())
    dialog.setGeometry(rect)


def restore_dialog_geometry_hex(dialog, geom_hex: str, parent=None) -> bool:
    """Restore saved geometry and clamp for the current screen layout."""
    if not geom_hex:
        return False
    try:
        ok = dialog.restoreGeometry(QByteArray(bytes.fromhex(geom_hex)))
    except Exception:
        return False
    if not ok:
        return False
    ensure_dialog_fits_screen(dialog, parent)
    return True


def save_dialog_geometry_hex(dialog) -> str:
    """Serialize dialog geometry for settings persistence."""
    return dialog.saveGeometry().data().hex()


class _StyledMessageDialog(QDialog):
    """QDialog that centers on screen when shown; parent may be unmapped (e.g. warning during __init__)."""

    def __init__(self, parent, parent_for_screen):
        super().__init__(parent)
        self._parent_for_screen = parent_for_screen

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._center_after_layout)

    def _center_after_layout(self):
        _center_styled_dialog_on_screen(self, self._parent_for_screen)


def styled_message_box(parent, icon, title, text, buttons=None, default_button=None, button_label_overrides=None):
    """
    Create a QMessageBox-like dialog using QDialog.

    Args:
        parent: Parent widget (can be None)
        icon: QMessageBox.Icon value (Warning, Critical, Information, Question)
        title: Dialog window title
        text: Message body text
        buttons: OR-ed QMessageBox.StandardButton enum values (e.g., QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        default_button: Default button (QMessageBox.StandardButton), or None
        button_label_overrides: optional dict mapping QMessageBox.StandardButton to label text

    Returns:
        Dialog object (call .exec()/.exec_() on it, and check dialog.result_data['button'] for result)
        The result will be a QMessageBox.StandardButton enum value
    """
    from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox, QStyle
    from PySide6.QtCore import Qt

    # Map QMessageBox.StandardButton enum values to button text
    STANDARD_BUTTONS = [
        (QMessageBox.StandardButton.Ok, "Ok"),
        (QMessageBox.StandardButton.Cancel, "Cancel"),
        (QMessageBox.StandardButton.Yes, "Yes"),
        (QMessageBox.StandardButton.No, "No"),
        (QMessageBox.StandardButton.Abort, "Abort"),
        (QMessageBox.StandardButton.Retry, "Retry"),
        (QMessageBox.StandardButton.Ignore, "Ignore"),
        (QMessageBox.StandardButton.Close, "Close"),
        (QMessageBox.StandardButton.Help, "Help"),
        (QMessageBox.StandardButton.Apply, "Apply"),
        (QMessageBox.StandardButton.Reset, "Reset"),
        (QMessageBox.StandardButton.Save, "Rename"),  # Map Save to Rename for file operations
    ]

    # If no buttons specified, fall back to Ok
    if buttons is None or buttons == 0:
        buttons = QMessageBox.StandardButton.Ok

    button_defs = []
    for value, label in STANDARD_BUTTONS:
        if buttons & value:
            if button_label_overrides and value in button_label_overrides:
                label = button_label_overrides[value]
            button_defs.append((value, label))

    if not button_defs:  # fallback in weird edge case
        button_defs = [(QMessageBox.StandardButton.Ok, "Ok")]

    dialog = _StyledMessageDialog(parent, parent)
    dialog.setWindowTitle(title)
    dialog.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setMinimumWidth(340)

    main_layout = QVBoxLayout(dialog)
    main_layout.setSpacing(18)
    main_layout.setContentsMargins(22, 18, 22, 18)

    # Optional icon support:
    icon_layout = QHBoxLayout()
    if icon is not None and icon in [QMessageBox.Warning, QMessageBox.Critical, QMessageBox.Information, QMessageBox.Question]:
        icon_label = QLabel()
        # Choose icon pixmap based on type:
        if icon == QMessageBox.Warning:
            icon_label.setPixmap(dialog.style().standardIcon(QStyle.SP_MessageBoxWarning).pixmap(44, 44))
        elif icon == QMessageBox.Critical:
            icon_label.setPixmap(dialog.style().standardIcon(QStyle.SP_MessageBoxCritical).pixmap(44, 44))
        elif icon == QMessageBox.Information:
            icon_label.setPixmap(dialog.style().standardIcon(QStyle.SP_MessageBoxInformation).pixmap(44, 44))
        elif icon == QMessageBox.Question:
            icon_label.setPixmap(dialog.style().standardIcon(QStyle.SP_MessageBoxQuestion).pixmap(44, 44))
        else:  # fallback generic
            icon_label.setPixmap(dialog.style().standardIcon(QStyle.SP_MessageBoxInformation).pixmap(44, 44))
        icon_layout.addWidget(icon_label, alignment=Qt.AlignTop)
    else:
        icon_label = None

    # Message text
    text_label = QLabel(text)
    text_label.setWordWrap(True)
    text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    text_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    text_label.setMinimumWidth(240)
    # Calculate proper height for wrapped text using QTextDocument for accurate measurement
    from PySide6.QtGui import QTextDocument
    font_metrics = text_label.fontMetrics()
    # Calculate available width (dialog min width 340 - margins 44 - icon space if present)
    available_width = 240 if icon_label else 296
    # Use QTextDocument for more accurate multi-line wrapped text measurement
    doc = QTextDocument()
    doc.setDefaultFont(text_label.font())
    doc.setTextWidth(available_width)
    doc.setPlainText(text)
    # Get the ideal height from the document
    ideal_height = doc.size().height()
    # Add generous padding: descent for characters below baseline + extra spacing
    descent = font_metrics.descent()
    leading = font_metrics.leading()
    # Use generous padding to ensure all text is visible, especially the last line
    padding = max(14, descent + leading + 10)  # At least 14px, or descent + leading + 10px
    calculated_height = int(ideal_height) + padding
    # Ensure minimum height is at least one line
    min_line_height = font_metrics.height() + padding
    calculated_height = max(calculated_height, min_line_height)
    # Set minimum height but don't constrain maximum - let it expand if needed
    text_label.setMinimumHeight(calculated_height)
    # Don't set maximum height - allow the label to size naturally if text is very long
    if icon_label:
        icon_layout.addWidget(text_label)
        main_layout.addLayout(icon_layout)
    else:
        main_layout.addWidget(text_label)

    # Button bar
    button_bar = QHBoxLayout()
    button_bar.addStretch()

    dialog.result_data = {'button': None}

    # Helper: for PyQt compatibility with exec_(), set 'done' to code
    def _set_dialog_result(value):
        dialog.result_data['button'] = value
        dialog.done(value)

    button_widgets = []
    default_btn_widget = None
    # Apply centralized button styling
    button_style = get_button_style()
    for b_val, b_label in button_defs:
        btn = QPushButton(b_label)
        btn.setStyleSheet(button_style)
        btn.setAutoDefault(False)
        is_default = default_button == b_val or (default_button is None and b_val == QMessageBox.StandardButton.Ok)
        if is_default:
            btn.setDefault(True)
            default_btn_widget = btn
        btn.clicked.connect(lambda chk, v=b_val: _set_dialog_result(v))
        button_bar.addWidget(btn)
        button_widgets.append(btn)

    button_bar.addStretch()
    main_layout.addLayout(button_bar)

    if default_btn_widget is not None:
        def _focus_default():
            default_btn_widget.setFocus(Qt.OtherFocusReason)
        QTimer.singleShot(0, _focus_default)

    # Add ESC key = Cancel or Close button, or No for Yes/No dialogs, or Ok if exists
    from PySide6.QtGui import QKeySequence
    esc_btn = None
    esc_button_value = None
    # First, look for explicit cancel buttons
    for idx, (b_val, b_label) in enumerate(button_defs):
        if b_val in (QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Close, QMessageBox.StandardButton.Ok):
            esc_btn = button_widgets[idx]
            esc_button_value = b_val
            break
    # If no cancel button, look for No button (for Yes/No dialogs)
    if esc_btn is None:
        for idx, (b_val, b_label) in enumerate(button_defs):
            if b_val == QMessageBox.StandardButton.No:
                esc_btn = button_widgets[idx]
                esc_button_value = b_val
                break
    # If still no cancel button, use the last button (typically the cancel action)
    if esc_btn is None and button_widgets:
        esc_btn = button_widgets[-1]
        esc_button_value = button_defs[-1][0]
    if esc_btn is not None and esc_button_value is not None:
        dialog.reject = lambda: _set_dialog_result(esc_button_value)
    # Dialog returns via .done() signal, which sets dialog.result (int)

    return dialog


def _dialog_thumbnail_border_color() -> str:
    """Border color for dialog thumbnails (valid for Qt stylesheets)."""
    from thumbnail_constants import BORDER_DEFAULT_HEX, MULTISELECT_BORDER_COLOR_HEX

    color = (MULTISELECT_BORDER_COLOR_HEX or BORDER_DEFAULT_HEX or "#808080").strip()
    return color if color else "#808080"


def create_dialog_thumbnail_label(file_path: str, size: int, ignore_exif: bool = False):
    """Create a QLabel for a dialog thumbnail with square frame (1px solid border).

    Avoid border-radius on pixmap QLabels — Qt on macOS often logs stylesheet parse errors.
    """
    from PySide6.QtWidgets import QLabel

    thumb = QLabel()
    thumb.setFixedSize(size, size)
    thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    thumb.setStyleSheet(f"border: 1px solid {_dialog_thumbnail_border_color()};")
    px = load_dialog_thumbnail(file_path, size, ignore_exif)
    if px and not px.isNull():
        thumb.setPixmap(px)
    return thumb


def load_dialog_thumbnail(file_path: str, size: int, ignore_exif: bool = False):
    """Load a thumbnail for use in dialogs. For image files uses EXIF-corrected load;
    for non-image files returns the noimage placeholder.
    """
    if not file_path or not os.path.isfile(file_path):
        from exif_image_loader import load_noimage_thumbnail
        return load_noimage_thumbnail(size)
    if not is_image_extension(get_file_extension(file_path)):
        from exif_image_loader import load_noimage_thumbnail
        return load_noimage_thumbnail(size)
    try:
        from exif_image_loader import load_thumbnail_with_exif_correction
        px = load_thumbnail_with_exif_correction(file_path, size, ignore_exif=ignore_exif)
        if px and not px.isNull():
            return px
    except Exception:
        pass
    from exif_image_loader import load_noimage_thumbnail
    return load_noimage_thumbnail(size)


def create_image_preview_row(image_paths, labels=None, size=96):
    """Create an QHBoxLayout with 1 or 2 thumbnail previews for dialog use.
    image_paths: list of 1 or 2 file paths (can be None for placeholder)
    labels: optional list of captions (e.g. ["Source", "Existing"])
    Returns: (QHBoxLayout, list of QLabel widgets for thumbnails)
    """
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout
    row = QHBoxLayout()
    row.setSpacing(14)
    thumb_labels = []
    paths = list(image_paths) if image_paths else []
    if not paths:
        return row, thumb_labels
    lab_list = labels or []
    for i, path in enumerate(paths[:2]):  # max 2
        cell = QVBoxLayout()
        lab = lab_list[i] if i < len(lab_list) else None
        if lab:
            cap = QLabel(lab)
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.addWidget(cap)
        thumb = create_dialog_thumbnail_label(path, size)
        thumb_labels.append(thumb)
        cell.addWidget(thumb, alignment=Qt.AlignmentFlag.AlignCenter)
        row.addLayout(cell)
    row.addStretch()
    return row, thumb_labels


def show_styled_warning(parent, title, text):
    """Show a styled warning message box"""
    from PySide6.QtWidgets import QMessageBox
    msg_box = styled_message_box(parent, QMessageBox.Warning, title, text)
    msg_box.exec()

def show_styled_information(parent, title, text):
    """Show a styled information message box and ensure focus after showing.

    Fix: Handle both QMessageBox and QDialog returned by styled_message_box.
    """
    msg_box = styled_message_box(parent, QMessageBox.Information, title, text)
    msg_box.exec()

def show_styled_critical(parent, title, text):
    """Show a styled critical message box"""
    msg_box = styled_message_box(parent, QMessageBox.Critical, title, text)
    msg_box.exec()

def create_file_operation_progress_dialog(parent, title: str, total_files: int) -> 'QProgressDialog':
    """Create a progress dialog for file operations (deletions, moves, copies)
    
    Args:
        parent: Parent widget (usually main window)
        title: Dialog title
        total_files: Total number of files to process
        
    Returns:
        QProgressDialog instance configured for file operations
    """
    
    progress_dialog = QProgressDialog(title, None, 0, total_files, parent)
    progress_dialog.setWindowTitle(title)
    progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    progress_dialog.setCancelButton(None)  # No cancel button
    progress_dialog.setMinimumDuration(0)  # Show immediately
    progress_dialog.setValue(0)
    
    # Set format on the internal progress bar to show percentage
    progress_bar = progress_dialog.findChild(QProgressBar)
    if progress_bar:
        progress_bar.setFormat("%p%")  # Show percentage
    
    # Ensure dialog is shown and raised to front
    progress_dialog.show()
    progress_dialog.raise_()
    progress_dialog.activateWindow()
    QApplication.processEvents()
    return progress_dialog

def show_styled_question(parent, title, text, default_no=True):
    """
    Show a styled question message box with Yes/No buttons
    
    Args:
        parent: Parent widget (can be None)
        title: Dialog window title
        text: Message body text
        default_no: If True, No button is default; if False, Yes button is default
    
    Returns:
        QMessageBox.StandardButton.Yes or QMessageBox.StandardButton.No
    """
    from PySide6.QtWidgets import QMessageBox
    default_button = QMessageBox.StandardButton.No if default_no else QMessageBox.StandardButton.Yes
    msg_box = styled_message_box(
        parent,
        QMessageBox.Question,
        title,
        text,
        buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        default_button=default_button
    )
    msg_box.exec()
    return msg_box.result_data['button']


def show_styled_ok_cancel(parent, title, text, default_cancel=True):
    """
    Show a styled question dialog with OK and Cancel buttons.

    Returns:
        QMessageBox.StandardButton.Ok or QMessageBox.StandardButton.Cancel
    """
    from PySide6.QtWidgets import QMessageBox

    default_button = (
        QMessageBox.StandardButton.Cancel
        if default_cancel
        else QMessageBox.StandardButton.Ok
    )
    msg_box = styled_message_box(
        parent,
        QMessageBox.Question,
        title,
        text,
        buttons=QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        default_button=default_button,
    )
    msg_box.exec()
    return msg_box.result_data["button"]


def is_drag_out_of_photos_library(source_path: str, target_directory: str) -> bool:
    """
    Check if a drag operation is moving files OUT of a Photos Library to a non-Photos Library location.
    This is the only allowed operation - dragging items out of Photos Libraries.
    
    Args:
        source_path: Source file path
        target_directory: Target directory path
        
    Returns:
        True if source is in Photos Library and target is NOT in Photos Library, False otherwise
    """
    source_in_library = is_inside_photos_library(source_path)
    target_in_library = is_inside_photos_library(target_directory)
    
    # Allow if source is in Photos Library but target is not
    return source_in_library and not target_in_library

def is_root_or_system_volume(directory_path: str) -> bool:
    """
    Check if a directory is either the root directory (/) or a system volume.
    
    On macOS, system volumes include:
    - The root directory itself (/)
    - /System and its subdirectories
    - /System/Volumes and its subdirectories (APFS system volumes)
    - Volumes mounted under /Volumes/ that are actually the system volume
      (e.g., /Volumes/Macintosh HD)
    
    For volumes under /Volumes/, this function uses device number comparison:
    it compares the st_dev from os.stat() of the volume root to that of the
    system root (/). If they match, the volume is the system volume.
    
    This function is used to prevent recursive operations on root or system volumes,
    which could be dangerous or cause performance issues.
    
    Args:
        directory_path: Directory path to check
        
    Returns:
        True if the directory is root or a system volume, False otherwise
    """
    if not directory_path:
        return False
    
    # Normalize to absolute path
    try:
        abs_path = os.path.abspath(os.path.expanduser(directory_path))
    except Exception:
        return False
    
    # Check if it's the root directory
    if abs_path == '/':
        return True
    
    # Check if it's under /System (system volume)
    # On macOS, /System contains system files and should not be recursively searched
    if abs_path.startswith('/System'):
        return True
    if abs_path.rstrip('/') in {
        '/Volumes', '/Volumes/System', '/Volumes/System/Volumes'
    }:
        return True
    
    # Check if it's under /System/Volumes (APFS system volumes on newer macOS)
    # This includes the system volume and read-only snapshots
    if abs_path.startswith('/System/Volumes'):
        return True
    
    # Check if it's a volume mounted under /Volumes/ that is actually the system volume
    # On macOS, we can check if a directory is on the system volume by comparing
    # its device number (st_dev) to that of the system root (/)
    if abs_path.startswith('/Volumes/'):
        try:
            # Extract the volume root path (e.g., /Volumes/Macintosh HD)
            parts = abs_path.split(os.sep)
            if len(parts) == 3 and parts[1] == 'Volumes':
                volume_name = parts[2]
                volume_root_path = os.path.join('/Volumes', volume_name)
                
                # Get device number for the root directory
                root_stat = os.stat('/')
                root_dev = root_stat.st_dev
                
                # Get device number for the volume root
                # This works even if the specific path doesn't exist yet
                volume_stat = os.stat(volume_root_path)
                volume_dev = volume_stat.st_dev
                
                # If device numbers match, it's on the system volume
                if volume_dev == root_dev:
                    return True
        except (OSError, PermissionError):
            # If we can't stat the volume root, it might not exist or we don't have permission
            # In this case, we can't determine if it's the system volume, so return False
            pass
    
    return False

def determine_suggested_filters(filenames: List[str]) -> List[str]:
    """
    Determine up to 5 longest prefixes that create the largest non-overlapping groups.
    For each group of files, find the longest prefix that matches that entire group.

    Args:
        filenames: List of filenames (should be basenames without extensions)

    Returns:
        List of suggested filter prefixes (without trailing asterisk), up to 5 items
    """
    if not filenames:
        return []

    from collections import defaultdict

    # Step 1: Build prefix-to-files mapping
    prefix_to_files = defaultdict(set)
    for fname in filenames:
        for i in range(1, len(fname) + 1):
            prefix = fname[:i]
            prefix_to_files[prefix].add(fname)

    # Only keep prefixes that cover more than 1 file
    candidates = []
    for prefix, matched in prefix_to_files.items():
        if len(matched) > 1:
            candidates.append((prefix, matched))

    # Step 2: For each unique fileset, keep only the LONGEST prefix 
    # (since longer prefix is more specific and still covers all those files)
    fileset_to_prefix = {}
    for prefix, matched_files in candidates:
        key = frozenset(matched_files)
        if key not in fileset_to_prefix or len(prefix) > len(fileset_to_prefix[key]):
            fileset_to_prefix[key] = prefix

    # Compose list of (prefix, num matched files) for further filtering
    candidate_prefixes = [(prefix, set(fileset)) for fileset, prefix in fileset_to_prefix.items()]

    # Step 3: Sort by: number of files matched desc, then prefix length desc (longer/more specific)
    candidate_prefixes.sort(key=lambda x: (-len(x[1]), -len(x[0]), x[0]))

    # Step 4: Select only non-overlapping prefixes.
    # As we pick a prefix, exclude any later prefix whose matched files overlap
    # with something we've already selected.

    selected = []
    matched_files_covered = set()
    for prefix, files in candidate_prefixes:
        if files.isdisjoint(matched_files_covered):
            selected.append((prefix, len(files)))
            matched_files_covered.update(files)
        # else: skip, because files are already covered by a previous filter

        if len(selected) == 5:
            break

    # Step 5: Clean up prefixes by removing trailing digits if safe
    cleaned_prefixes = []
    cleaned_set = set()
    
    for prefix, count in selected:
        # Try to remove trailing digits
        cleaned = prefix.rstrip('0123456789')
        
        # Only use cleaned version if:
        # 1. It's not empty
        # 2. It's different from original (had trailing digits)
        # 3. It doesn't create a duplicate
        if cleaned and cleaned != prefix and cleaned not in cleaned_set:
            cleaned_prefixes.append(cleaned)
            cleaned_set.add(cleaned)
        else:
            # Use original prefix
            cleaned_prefixes.append(prefix)
            cleaned_set.add(prefix)
    
    return cleaned_prefixes


# ============================================================================
# Path and File Utilities
# ============================================================================

def convert_file_url_to_path(file_path: str) -> str:
    """Convert file:// URLs to regular file paths for macOS compatibility"""
    if file_path.startswith('file://'):
        # Remove the file:// prefix and decode URL encoding
        file_path = file_path[7:]  # Remove 'file://'
        file_path = urllib.parse.unquote(file_path)
        
        # Handle macOS file:// URLs that might have multiple slashes
        if file_path.startswith('//'):
            file_path = file_path[1:]  # Remove extra slash
        elif file_path.startswith('/'):
            file_path = file_path  # Keep single slash
    return file_path


def resolve_path(path: str, must_exist: bool = False) -> Optional[str]:
    """
    Resolve a path: convert file:// URLs, expand ~, make absolute.
    
    Args:
        path: Path string (may be file:// URL, relative, or absolute)
        must_exist: If True, return None if path doesn't exist
        
    Returns:
        Resolved absolute path, or None if must_exist=True and path doesn't exist
    """
    if not path:
        return None
    
    # Convert file:// URLs
    path = convert_file_url_to_path(path)
    
    # Expand ~
    path = os.path.expanduser(path)
    
    # Make absolute
    if not os.path.isabs(path):
        path = os.path.abspath(path)
    
    # Check existence if required
    if must_exist and not os.path.exists(path):
        return None
    
    return path


def validate_path_exists(path: str) -> bool:
    """Check if a path exists"""
    if not path:
        return False
    try:
        return os.path.exists(path)
    except Exception:
        return False


def normalize_path_for_display(path: str) -> str:
    """
    Convert full path to ~ format for display (UI, clipboard, messages).

    Not for cache keys or identity: use face_cache.normalize_path_for_face_cache for
    stable filesystem identity (resolved real path) when indexing or storing data
    keyed by file path.

    Args:
        path: Full path string (e.g., '/Users/bubba/foo')

    Returns:
        Display format path (e.g., '~/foo') or original path if not under home
    """
    if not path:
        return path
    
    path = path.strip()
    if not path:
        return path
    
    try:
        home = os.path.expanduser("~")
        if path.startswith(home):
            # Replace home directory with ~
            relative = os.path.relpath(path, home)
            if relative == '.':
                return "~"
            else:
                return os.path.join("~", relative).replace("\\", "/")
    except (ValueError, OSError):
        # If path is not under home or there's an error, return as-is
        pass
    
    return path


def display_to_path(display_path: str) -> str:
    """
    Convert display format path (with ~) to full path.
    
    Args:
        display_path: Display format path (e.g., '~/foo' or '/Users/bubba/foo')
        
    Returns:
        Full path string (e.g., '/Users/bubba/foo')
    """
    if not display_path:
        return display_path
    
    display_path = display_path.strip()
    if not display_path:
        return display_path
    
    # Expand ~ to full home path
    return os.path.expanduser(display_path)


# ============================================================================
# Image File Utilities
# ============================================================================

def get_file_extension(file_path: str) -> str:
    """
    Get lowercase file extension including dot.
    
    Args:
        file_path: File path string
        
    Returns:
        Lowercase extension including dot (e.g., '.jpg'), or empty string if no extension
    """
    _, ext = os.path.splitext(file_path)
    return ext.lower()


def is_image_extension(ext: str) -> bool:
    """
    Check if extension is a valid image extension.
    
    Args:
        ext: File extension (with or without dot, case insensitive)
        
    Returns:
        True if extension is a valid image extension
    """
    from thumbnail_constants import get_image_extensions
    # Normalize extension to include dot and lowercase
    if ext and not ext.startswith('.'):
        ext = '.' + ext
    return ext.lower() in get_image_extensions()


def validate_image_file(file_path: str) -> bool:
    """
    Validate that a file is a supported image format.
    
    Args:
        file_path: File path to validate
        
    Returns:
        True if file has a supported image extension
    """
    ext = get_file_extension(file_path)
    return is_image_extension(ext)


def directory_has_images(dir_path: str, filter_pattern: Optional[str] = None) -> bool:
    """
    Check if directory contains any image files matching optional filter.
    
    Args:
        dir_path: Directory path to check
        filter_pattern: Optional glob pattern to filter filenames (e.g., 'image*', '*.jpg')
        
    Returns:
        True if directory contains at least one matching image file
    """
    if not dir_path or not os.path.isdir(dir_path):
        return False
    
    try:
        from thumbnail_constants import get_image_extensions
        from config import ImageBrowserConfig
        
        image_exts = get_image_extensions()
        if not image_exts:
            return False
        
        # Normalize filter pattern for matching
        match_pattern = None
        if filter_pattern:
            match_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(filter_pattern)
        
        # Check directory contents
        for entry in os.scandir(dir_path):
            if entry.is_file():
                ext = get_file_extension(entry.name)
                if ext in image_exts:
                    # If filter pattern provided, check if filename matches
                    if match_pattern and match_pattern != '*':
                        if fnmatch.fnmatch(entry.name.lower(), match_pattern.lower()):
                            return True
                    else:
                        # No filter or filter is '*', any image file matches
                        return True
        
        return False
    except Exception:
        return False


def handle_filter_pattern_mismatch(main_window, displayed_images: List[str], non_matching_images: List[str],
                                   recursive: bool):
    """Centralized handler for filter pattern mismatch during recursive search.
    When recursive search finds images that don't match the current filter pattern,
    asks user whether to reset filter to '*' or exclude non-matching images.
    Returns displayed_images (possibly filtered)."""
    if not recursive or not non_matching_images:
        return displayed_images
    reply = show_styled_question(
        main_window,
        "Filter Pattern Mismatch",
        f"Found {len(non_matching_images)} image(s) that don't match the current filter pattern.\n\n"
        "Would you like to reset the filter pattern to '*' to see all images?",
        default_no=True,
    )
    if reply == QMessageBox.StandardButton.Yes:
        main_window.filter_pattern = None
        if hasattr(main_window, 'config'):
            from config import ImageBrowserConfig
            main_window.config.update_setting('filter_pattern', ImageBrowserConfig.normalize_filter_pattern('*'))
        if hasattr(main_window, 'status_bar_manager'):
            main_window.status_bar_manager._update_filter_section(main_window)
        return displayed_images
    return [img for img in displayed_images if img not in non_matching_images]
