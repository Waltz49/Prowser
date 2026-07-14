# utils.py

# Standard library imports
import functools
import inspect
import math
import os
import re
import sys
import traceback
import urllib.parse
import fnmatch
from typing import Callable, Dict, List, Optional, Tuple

# Third-party imports
from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QByteArray, QRect
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPainterPath, QPixmap
from ctypes import CDLL, c_uint
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QProgressBar,
    QProgressDialog,
    QMessageBox,
    QPushButton,
    QWidget,
)

PROGRESS_LABEL_MAX_WIDTH_PX = 400
PROGRESS_LINE_MAX_CHARS = 64
PROGRESS_FILENAME_MAX_CHARS = 44


def elide_middle(text: str, max_len: int) -> str:
    """Elide a string with a middle ellipsis when longer than max_len."""
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    keep = max_len - 3
    front = (keep + 1) // 2
    back = keep // 2
    return f"{text[:front]}...{text[-back:]}"


def elide_progress_filename(filename: str, max_len: int = PROGRESS_FILENAME_MAX_CHARS) -> str:
    """Elide a filename for display in a progress dialog label."""
    return elide_middle(filename, max_len)


def format_progress_label(text: str, *, line_max: int = PROGRESS_LINE_MAX_CHARS) -> str:
    """Elide each line of progress dialog label text to limit dialog growth."""
    lines = text.split("\n")
    if len(lines) == 1:
        return elide_middle(text, line_max)
    return "\n".join(elide_middle(line, line_max) for line in lines)


def configure_progress_dialog_label(progress_dialog: QProgressDialog) -> None:
    """Constrain progress dialog label width so long paths do not widen the dialog."""
    label = progress_dialog.findChild(QLabel)
    if label:
        label.setWordWrap(False)
        label.setMaximumWidth(PROGRESS_LABEL_MAX_WIDTH_PX)


def wrap_progress_dialog_label_elision(progress_dialog: QProgressDialog) -> None:
    """Wrap setLabelText so all progress messages are elided and width-limited."""
    configure_progress_dialog_label(progress_dialog)
    _orig_set_label = progress_dialog.setLabelText

    def _elided_set_label(text: str) -> None:
        _orig_set_label(format_progress_label(text))

    progress_dialog.setLabelText = _elided_set_label  # type: ignore[method-assign]

# Local imports
from thumbnails.thumbnail_constants import GREEN, RED, RESET, YELLOW
from files.photos_library_paths import (
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

def is_macos_space_mode() -> bool:
    """True when the main window is in macOS Space display mode (native fullscreen Space)."""
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
    Focus/hover accent colors for buttons (from theme button settings).

    Returns:
        Tuple of (background_hex, border_hex, text_hex)
    """
    from thumbnails.thumbnail_constants import (
        BUTTON_BG_HOVER_HEX,
        BUTTON_BORDER_HOVER_HEX,
        BUTTON_TEXT_HOVER_HEX,
    )

    return (BUTTON_BG_HOVER_HEX, BUTTON_BORDER_HOVER_HEX, BUTTON_TEXT_HOVER_HEX)


def get_dialog_shell_stylesheet() -> str:
    """Dialog window + child QWidget backgrounds (overrides global application QWidget fill)."""
    from theme.theme_service import get_active_theme

    th = get_active_theme()
    return (
        f"QDialog, QDialog QWidget {{ "
        f"background-color: {th.dialog_background_hex}; "
        f"color: {th.dialog_text_color_hex}; "
        f"}}\n"
    )


def get_button_style() -> str:
    """
    Returns the standard button style string for all QPushButton widgets.
    This centralizes button styling application-wide.

    Returns:
        CSS stylesheet string for QPushButton styling
    """
    from theme.theme import push_button_stylesheet
    from theme.theme_service import get_active_theme

    return push_button_stylesheet(get_active_theme())


def get_dialog_button_box_style() -> str:
    """
    Returns button style string for QDialogButtonBox QPushButton widgets.

    Returns:
        CSS stylesheet string for QDialogButtonBox QPushButton styling
    """
    from theme.theme import push_button_stylesheet
    from theme.theme_service import get_active_theme

    return (
        push_button_stylesheet(get_active_theme(), selector="QDialogButtonBox QPushButton")
        + """
    QDialogButtonBox QPushButton {
        min-width: 80px;
        padding: 6px 14px;
    }
    """
    )


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


def _is_terminal_gui_launch() -> bool:
    """True when the GUI was started from a script, not as a bundled .app."""
    if getattr(sys, "frozen", False):
        return False
    argv0 = os.path.abspath(sys.argv[0]) if sys.argv else ""
    if ".app/Contents/MacOS/" in argv0:
        return False
    if argv0.endswith(".app"):
        return False
    return True


def _process_serial_number_type():
    from ctypes import Structure, c_uint32

    class _ProcessSerialNumber(Structure):
        _fields_ = [("highLongOfPSN", c_uint32), ("lowLongOfPSN", c_uint32)]

    return _ProcessSerialNumber


def _application_services():
    import ctypes

    lib = ctypes.CDLL(
        "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
    )
    psn_type = _process_serial_number_type()
    get_current = lib.GetCurrentProcess
    get_current.argtypes = [ctypes.POINTER(psn_type)]
    get_current.restype = ctypes.c_int
    return lib, psn_type, get_current


def _promote_process_to_foreground() -> None:
    """Promote a terminal-spawned Python process to a foreground GUI app."""
    try:
        import ctypes

        lib, psn_type, get_current = _application_services()
        transform = lib.TransformProcessType
        transform.argtypes = [ctypes.POINTER(psn_type), ctypes.c_int]
        transform.restype = ctypes.c_int
        psn = psn_type()
        if get_current(ctypes.byref(psn)) != 0:
            return
        # kProcessTransformToForegroundApplication
        transform(ctypes.byref(psn), 1)
    except Exception:
        pass


def _activate_via_osascript() -> None:
    """Last-resort activation for terminal launches (System Events by unix pid)."""
    try:
        import subprocess

        pid = os.getpid()
        subprocess.run(
            [
                "osascript",
                "-e",
                (
                    'tell application "System Events" to set frontmost of '
                    f"(first process whose unix id is {pid}) to true"
                ),
            ],
            capture_output=True,
            timeout=2,
            check=False,
        )
    except Exception:
        pass


def activate_macos_application(*, force: Optional[bool] = None) -> None:
    """Activate the Cocoa application object (needed for terminal launches)."""
    if force is None:
        force = _is_terminal_gui_launch()
    if force:
        _promote_process_to_foreground()
    try:
        from AppKit import NSApplication, NSRunningApplication

        ns_app = NSApplication.sharedApplication()
        # NSApplicationActivationPolicyRegular
        ns_app.setActivationPolicy_(0)
        if hasattr(ns_app, "finishLaunching") and not ns_app.isFinishedLaunching():
            ns_app.finishLaunching()
        if force:
            ns_app.activateIgnoringOtherApps_(True)
        running = NSRunningApplication.runningApplicationWithProcessIdentifier_(os.getpid())
        if running is not None:
            options = (1 | 2) if force else 1
            running.activateWithOptions_(options)
    except Exception:
        pass
    if not force:
        return
    try:
        import ctypes

        lib, psn_type, get_current = _application_services()
        set_front = lib.SetFrontProcess
        set_front.argtypes = [ctypes.POINTER(psn_type)]
        set_front.restype = ctypes.c_int
        psn = psn_type()
        get_current(ctypes.byref(psn))
        set_front(ctypes.byref(psn))
    except Exception:
        pass
    if force:
        _activate_via_osascript()


def _make_native_window_key(window: QWidget) -> bool:
    try:
        import objc
        from ctypes import c_void_p

        wid = window.winId()
        if not wid:
            return False
        view = objc.objc_object(c_void_p=int(wid))
        ns_window = view.window()
        if ns_window is None:
            return False
        if hasattr(ns_window, "orderFrontRegardless"):
            ns_window.orderFrontRegardless()
        ns_window.makeKeyAndOrderFront_(None)
        return True
    except Exception:
        return False


def activate_application_window(window: Optional[QWidget], *, force: Optional[bool] = None) -> None:
    """Bring the app and main window to the macOS foreground like a normal app launch."""
    if window is None:
        return
    if force is None:
        force = _is_terminal_gui_launch()

    activate_macos_application(force=force)
    try:
        top = window.window() if window is not None else None
        if top is None:
            return
        if not top.isVisible():
            top.show()
        top.raise_()
        top.activateWindow()
        if top.isWindow():
            wh = top.windowHandle()
            if wh is not None:
                wh.requestActivate()
    except Exception:
        pass
    if force:
        _make_native_window_key(window)


def schedule_startup_activation(window: Optional[QWidget], *, force: Optional[bool] = None) -> None:
    """Retry activation while the first main window is mapping on screen."""
    if window is None:
        return
    if force is None:
        force = _is_terminal_gui_launch()
    # Terminal launches need more retries; bundled .app launches only need a light nudge.
    delays = (0, 50, 150, 400, 800, 1500, 2500, 4000) if force else (0, 200)
    for delay_ms in delays:
        QTimer.singleShot(
            delay_ms,
            lambda w=window, f=force: activate_application_window(w, force=f),
        )


class _StartupActivationFilter(QObject):
    """One-shot activation when the main window is first shown."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self._activated = False

    def eventFilter(self, obj, event):
        if obj is self._window and event.type() == QEvent.Type.Show and not self._activated:
            self._activated = True
            force = _is_terminal_gui_launch()
            activate_application_window(self._window, force=force)
            schedule_startup_activation(self._window, force=force)
        return False


def install_startup_activation(window: QWidget) -> None:
    """Ensure terminal launches bring the first main window to the foreground."""
    filt = _StartupActivationFilter(window)
    window.installEventFilter(filt)
    window._startup_activation_filter = filt


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


def restore_dialog_geometry_before_first_show(
    dialog,
    geom_hex: Optional[str],
    parent=None,
) -> bool:
    """Restore saved geometry while the dialog is still hidden (no resize blink)."""
    if getattr(dialog, "_geometry_restore_attempted", False):
        return bool(getattr(dialog, "_geometry_was_restored", False))
    dialog._geometry_restore_attempted = True
    restored = False
    if geom_hex:
        try:
            restored = restore_dialog_geometry_hex(dialog, geom_hex, parent)
        except Exception:
            restored = False
    dialog._geometry_was_restored = restored
    return restored


def dialog_main_window(dialog: QWidget) -> Optional[QWidget]:
    """Return the host main window for a dialog, if any."""
    w: Optional[QWidget] = dialog.parentWidget()
    while w is not None:
        if hasattr(w, "isFullScreen"):
            return w
        w = w.parentWidget()
    win = dialog.window()
    if win is not None and hasattr(win, "isFullScreen"):
        return win
    return None


def host_is_macos_space_mode(host: Optional[QWidget]) -> bool:
    """True when the host window is in native macOS fullscreen (Space) mode."""
    return host is not None and hasattr(host, "isFullScreen") and host.isFullScreen()


def fix_macos_dialog_same_space(widget: QWidget) -> None:
    """Keep a dialog on the active macOS Space when the host is fullscreen."""
    if not isinstance(widget, QDialog) or not widget.isWindow():
        return
    if not host_is_macos_space_mode(dialog_main_window(widget)):
        return
    try:
        from ctypes import c_void_p

        import objc
        from AppKit import (
            NSWindowCollectionBehaviorFullScreenAuxiliary,
            NSWindowCollectionBehaviorFullScreenPrimary,
            NSWindowCollectionBehaviorMoveToActiveSpace,
        )
    except ImportError:
        return
    wid = widget.winId()
    if not wid:
        return
    view = objc.objc_object(c_void_p=int(wid))
    ns_window = view.window()
    if ns_window is None:
        return
    behavior = int(ns_window.collectionBehavior())
    behavior &= ~int(NSWindowCollectionBehaviorFullScreenPrimary)
    behavior |= int(NSWindowCollectionBehaviorFullScreenAuxiliary)
    behavior |= int(NSWindowCollectionBehaviorMoveToActiveSpace)
    ns_window.setCollectionBehavior_(behavior)


def raise_dialog_without_space_hop(dialog: QDialog) -> None:
    """Raise a dialog; avoid activateWindow in macOS Space mode."""
    dialog.raise_()
    if host_is_macos_space_mode(dialog_main_window(dialog)):
        fix_macos_dialog_same_space(dialog)
        dialog.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
    else:
        dialog.activateWindow()


def present_auxiliary_dialog(dialog: QDialog) -> None:
    """Show a non-modal auxiliary dialog."""
    dialog.show()
    raise_dialog_without_space_hop(dialog)


def should_preserve_window_focus(main_window: Optional[QWidget] = None) -> bool:
    """True when raising/activating the main window would interrupt the user."""
    app = QApplication.instance()
    if app is None:
        return False
    if QGuiApplication.applicationState() != Qt.ApplicationState.ApplicationActive:
        return True
    focus = app.focusWidget()
    if focus is None:
        return False
    w: Optional[QWidget] = focus
    while w is not None:
        if isinstance(w, QDialog) and w.isVisible():
            return True
        w = w.parentWidget()
    return False


class _StyledMessageButtonKeyFilter(QObject):
    """Tab/arrow navigation between styled message box buttons."""

    def __init__(self, buttons: List[QPushButton], dialog: QWidget):
        super().__init__(dialog)
        self._buttons = buttons
        self._dialog = dialog

    def eventFilter(self, obj, event):
        if obj is not self._dialog and obj not in self._buttons:
            return False
        if event.type() != QEvent.Type.KeyPress:
            return False
        key = event.key()
        if key == Qt.Key.Key_Tab:
            direction = -1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        elif key == Qt.Key.Key_Backtab:
            direction = -1
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            direction = -1 if key == Qt.Key.Key_Left else 1
        else:
            return False
        focused = QApplication.focusWidget()
        if focused in self._buttons:
            idx = self._buttons.index(focused)
        else:
            idx = -1 if direction > 0 else 0
        self._buttons[(idx + direction) % len(self._buttons)].setFocus(
            Qt.FocusReason.TabFocusReason
        )
        return True


def _install_styled_message_button_navigation(dialog: QDialog, button_widgets: List[QPushButton]) -> None:
    """Enable Tab/arrow keyboard navigation between dialog action buttons."""
    if not button_widgets:
        return
    for btn in button_widgets:
        btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    if len(button_widgets) >= 2:
        for idx in range(len(button_widgets) - 1):
            QWidget.setTabOrder(button_widgets[idx], button_widgets[idx + 1])
        QWidget.setTabOrder(button_widgets[-1], button_widgets[0])
        key_filter = _StyledMessageButtonKeyFilter(button_widgets, dialog)
        dialog._button_key_filter = key_filter
        dialog.installEventFilter(key_filter)
        for btn in button_widgets:
            btn.installEventFilter(key_filter)


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


def _apply_styled_message_proceed_note(
    dialog: QDialog,
    text_label: QLabel,
    button_widgets: List[QPushButton],
    note: str,
    *,
    has_icon: bool,
) -> None:
    """Show in-dialog status after the user chooses a proceed action (before dialog closes)."""
    from PySide6.QtGui import QTextDocument

    text_label.setText(note)
    font_metrics = text_label.fontMetrics()
    available_width = 240 if has_icon else 296
    doc = QTextDocument()
    doc.setDefaultFont(text_label.font())
    doc.setTextWidth(available_width)
    doc.setPlainText(note)
    ideal_height = doc.size().height()
    descent = font_metrics.descent()
    leading = font_metrics.leading()
    padding = max(14, descent + leading + 10)
    calculated_height = max(int(ideal_height) + padding, font_metrics.height() + padding)
    text_label.setMinimumHeight(calculated_height)
    for btn in button_widgets:
        btn.setEnabled(False)
        btn.hide()
    dialog.adjustSize()
    _center_styled_dialog_on_screen(dialog, dialog.parentWidget())
    dialog.activateWindow()
    dialog.raise_()
    QApplication.processEvents()


def styled_message_box(
    parent,
    icon,
    title,
    text,
    buttons=None,
    default_button=None,
    button_label_overrides=None,
    proceed_handlers: Optional[Dict[int, Tuple[str, Callable[[], None]]]] = None,
    middle_widget=None,
):
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
        proceed_handlers: optional map of QMessageBox.StandardButton to (proceed_note, action)
            called after the user clicks that button, before the dialog closes
        middle_widget: optional QWidget inserted between message text and buttons

    Returns:
        Dialog object (call .exec()/.exec_() on it, and check dialog.result_data['button'] for result)
        The result will be a QMessageBox.StandardButton enum value
    """
    from PySide6.QtWidgets import (
        QHBoxLayout,
        QLabel,
        QMessageBox,
        QPushButton,
        QSizePolicy,
        QStyle,
        QVBoxLayout,
    )
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
    dialog.setStyleSheet(
        get_dialog_shell_stylesheet() + get_button_style()
    )
    dialog.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    _DIALOG_MARGIN_H = 44
    _ICON_PIXMAP_W = 44
    _MIDDLE_WIDGET_MIN_CONTENT_W = 336
    _MIDDLE_WIDGET_MAX_TEXT_W = 520
    dialog_content_width = 336

    main_layout = QVBoxLayout(dialog)
    main_layout.setSpacing(18 if middle_widget is None else 14)
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

    # Message text (parent to dialog so font metrics match rendered text)
    text_label = QLabel(text, dialog)
    text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    text_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    from PySide6.QtGui import QTextDocument

    font_metrics = text_label.fontMetrics()
    icon_text_spacing = 12
    text_width = 0
    if middle_widget is not None:
        icon_text_spacing = 16 if icon_label else 0
        lines = text.split("\n")
        line_widths = []
        for line in lines:
            probe = QLabel(line or " ")
            probe.setFont(text_label.font())
            probe.setWordWrap(False)
            line_widths.append(probe.sizeHint().width())
        max_line_w = max(line_widths, default=0)
        if max_line_w <= _MIDDLE_WIDGET_MAX_TEXT_W:
            text_label.setWordWrap(False)
            text_width = text_label.sizeHint().width()
        else:
            text_label.setWordWrap(True)
            text_width = _MIDDLE_WIDGET_MAX_TEXT_W
            text_label.setFixedWidth(text_width)
        if icon_label:
            dialog_content_width = max(
                _MIDDLE_WIDGET_MIN_CONTENT_W,
                _ICON_PIXMAP_W + icon_text_spacing + text_width,
            )
        else:
            dialog_content_width = max(
                _MIDDLE_WIDGET_MIN_CONTENT_W, text_width
            )
        dialog.setMinimumWidth(dialog_content_width + _DIALOG_MARGIN_H)
    else:
        text_label.setWordWrap(True)
        text_width = 240 if icon_label else 296
        dialog.setMinimumWidth(340)
    # Use QTextDocument for more accurate multi-line wrapped text measurement
    doc = QTextDocument()
    doc.setDefaultFont(text_label.font())
    measure_width = text_width if middle_widget is not None else (
        240 if icon_label else 296
    )
    doc.setTextWidth(measure_width)
    doc.setPlainText(text)
    # Get the ideal height from the document
    ideal_height = doc.size().height()
    if middle_widget is not None and not text_label.wordWrap():
        ideal_height = text_label.sizeHint().height()
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
    if middle_widget is not None:
        text_label.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred
        )
    elif icon_label:
        text_label.setMinimumWidth(240)
    else:
        text_label.setMinimumWidth(296)
    # Don't set maximum height - allow the label to size naturally if text is very long
    if icon_label:
        icon_layout.setSpacing(icon_text_spacing)
        icon_layout.addWidget(
            text_label,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        icon_layout.addStretch(1)
        main_layout.addLayout(icon_layout)
    else:
        main_layout.addWidget(text_label)

    if middle_widget is not None:
        setter = getattr(middle_widget, "set_layout_width_px", None)
        if callable(setter):
            setter(dialog_content_width)
        main_layout.addWidget(middle_widget, 0, Qt.AlignmentFlag.AlignHCenter)

    # Button bar: dismiss on the left, affirmative actions on the right
    _LEFT_DIALOG_BUTTONS = frozenset({
        QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Close,
        QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Abort,
    })

    left_defs = [(v, l) for v, l in button_defs if v in _LEFT_DIALOG_BUTTONS]
    right_defs = [(v, l) for v, l in button_defs if v not in _LEFT_DIALOG_BUTTONS]

    button_bar = QHBoxLayout()

    dialog.result_data = {'button': None}
    dialog.message_label = text_label
    dialog.button_widgets = []

    # Helper: for PyQt compatibility with exec_(), set 'done' to code
    def _set_dialog_result(value):
        dialog.result_data['button'] = value
        dialog.done(value)

    def _on_button_clicked(button_value):
        handler = (proceed_handlers or {}).get(button_value)
        if handler is not None:
            note, action = handler
            _apply_styled_message_proceed_note(
                dialog,
                text_label,
                button_widgets,
                note,
                has_icon=icon_label is not None,
            )
            action()
        _set_dialog_result(button_value)

    button_widgets = []
    default_btn_widget = None

    def _add_button_defs(defs):
        nonlocal default_btn_widget
        for b_val, b_label in defs:
            btn = QPushButton(b_label)
            btn.setAutoDefault(False)
            is_default = default_button == b_val or (default_button is None and b_val == QMessageBox.StandardButton.Ok)
            if is_default:
                btn.setDefault(True)
                default_btn_widget = btn
            btn.clicked.connect(lambda _checked=False, v=b_val: _on_button_clicked(v))
            button_bar.addWidget(btn)
            button_widgets.append(btn)

    _add_button_defs(left_defs)
    button_bar.addStretch()
    _add_button_defs(right_defs)
    dialog.button_widgets = button_widgets

    main_layout.addLayout(button_bar)

    _install_styled_message_button_navigation(dialog, button_widgets)

    if default_btn_widget is not None:
        def _focus_default():
            dialog.activateWindow()
            dialog.raise_()
            default_btn_widget.setFocus(Qt.FocusReason.TabFocusReason)
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
    from thumbnails.thumbnail_constants import BORDER_DEFAULT_HEX, MULTISELECT_BORDER_COLOR_HEX

    color = (MULTISELECT_BORDER_COLOR_HEX or BORDER_DEFAULT_HEX or "#808080").strip()
    return color if color else "#808080"


def job_status_thumbnail_stylesheet() -> str:
    """Hover-only border for clickable job-status thumbnails (transparent keeps box size)."""
    color = _dialog_thumbnail_border_color()
    return (
        "QLabel { border: 1px solid transparent; }"
        f"QLabel:hover {{ border: 1px solid {color}; }}"
    )


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


def create_job_status_thumbnail_label(
    file_path: str, size: int, ignore_exif: bool = False
):
    """Job queue / sidebar thumbnail: 1px border on hover only (transparent otherwise)."""
    from PySide6.QtWidgets import QLabel

    thumb = QLabel()
    thumb.setFixedSize(size, size)
    thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    thumb.setStyleSheet(job_status_thumbnail_stylesheet())
    thumb.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
    px = load_dialog_thumbnail(file_path, size, ignore_exif)
    if px and not px.isNull():
        thumb.setPixmap(px)
    return thumb


def load_dialog_thumbnail(file_path: str, size: int, ignore_exif: bool = False):
    """Load a thumbnail for use in dialogs. For image files uses EXIF-corrected load;
    for non-image files returns the noimage placeholder.
    """
    if not file_path or not os.path.isfile(file_path):
        from exif.exif_image_loader import load_noimage_thumbnail
        return load_noimage_thumbnail(size)
    if not is_image_extension(get_file_extension(file_path)):
        from exif.exif_image_loader import load_noimage_thumbnail
        return load_noimage_thumbnail(size)
    try:
        from exif.exif_image_loader import load_thumbnail_with_exif_correction
        px = load_thumbnail_with_exif_correction(file_path, size, ignore_exif=ignore_exif)
        if px and not px.isNull():
            return px
    except Exception:
        pass
    from exif.exif_image_loader import load_noimage_thumbnail
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

def create_titled_progress_dialog(
    parent,
    title: str,
    total: int,
    *,
    label: Optional[str] = None,
    cancellable: bool = True,
    indeterminate: bool = False,
) -> QProgressDialog:
    """Create a progress dialog with a visible title bar (macOS-friendly setup).

    Uses the same pattern as file-operation progress dialogs: title on the window,
    optional detail text in the label, ApplicationModal, and explicit show/raise.
    """
    cancel_text = "Cancel" if cancellable else None
    label_text = label if label is not None else title
    maximum = 0 if indeterminate else total
    progress_dialog = QProgressDialog(label_text, cancel_text, 0, maximum, parent)
    progress_dialog.setWindowTitle(title)
    progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    if not cancellable:
        progress_dialog.setCancelButton(None)
    progress_dialog.setMinimumDuration(0)
    progress_dialog.setValue(0)
    if indeterminate:
        progress_dialog.setMaximum(0)

    progress_bar = progress_dialog.findChild(QProgressBar)
    if progress_bar and not indeterminate and total > 0:
        progress_bar.setFormat("%p%")

    wrap_progress_dialog_label_elision(progress_dialog)
    progress_dialog.show()
    progress_dialog.raise_()
    progress_dialog.activateWindow()
    QApplication.processEvents()
    return progress_dialog


def create_file_operation_progress_dialog(parent, title: str, total_files: int) -> QProgressDialog:
    """Create a progress dialog for file operations (deletions, moves, copies)."""
    return create_titled_progress_dialog(
        parent, title, total_files, cancellable=False
    )

def show_styled_question(
    parent,
    title,
    text,
    default_no=True,
    *,
    proceed_note: Optional[str] = None,
    on_proceed: Optional[Callable[[], None]] = None,
):
    """
    Show a styled question message box with Yes/No buttons
    
    Args:
        parent: Parent widget (can be None)
        title: Dialog window title
        text: Message body text
        default_no: If True, No button is default; if False, Yes button is default
        proceed_note: If set with on_proceed, shown after Yes before on_proceed runs
        on_proceed: Callable run after proceed_note is shown (e.g. slow cancel)
    
    Returns:
        QMessageBox.StandardButton.Yes or QMessageBox.StandardButton.No
    """
    from PySide6.QtWidgets import QMessageBox
    default_button = QMessageBox.StandardButton.No if default_no else QMessageBox.StandardButton.Yes
    proceed_handlers = None
    if proceed_note and on_proceed is not None:
        proceed_handlers = {QMessageBox.StandardButton.Yes: (proceed_note, on_proceed)}
    msg_box = styled_message_box(
        parent,
        QMessageBox.Question,
        title,
        text,
        buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        default_button=default_button,
        proceed_handlers=proceed_handlers,
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


def folder_basename_for_display(path: str) -> str:
    """Last path segment for brief status messages; safe when path ends with '/'."""
    if not path or not path.strip():
        return ""
    p = path.strip().rstrip("/")
    segment = os.path.basename(p) if p else ""
    return segment or normalize_path_for_display(path.strip())


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
    from thumbnails.thumbnail_constants import get_image_extensions
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
        from thumbnails.thumbnail_constants import get_image_extensions
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


def path_matches_active_filter(main_window, file_path: str) -> bool:
    """Return True if file_path's basename matches the active filter_pattern."""
    if not hasattr(main_window, 'filter_pattern') or not main_window.filter_pattern:
        return True
    from config import ImageBrowserConfig
    match_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(main_window.filter_pattern)
    if not match_pattern or match_pattern == '*':
        return True
    filename = os.path.basename(file_path)
    return fnmatch.fnmatch(filename.lower(), match_pattern.lower())


def handle_filter_pattern_mismatch(main_window, displayed_images: List[str], non_matching_images: List[str],
                                   recursive: bool):
    """Exclude images that do not match the active filter pattern."""
    if not non_matching_images:
        return displayed_images
    non_matching_set = set(non_matching_images)
    return [img for img in displayed_images if img not in non_matching_set]
