"""
PyInstaller runtime hook.
Runs before the main script in every frozen process (GUI and --model-tasks-worker).
"""
import os

# Enable JIT before the interpreter fully starts (existing Prowser behavior).
os.environ.setdefault("PYTHON_JIT", "1")

try:
    import importlib.util
    import sys

    if getattr(sys, "frozen", False):
        from pyinstaller_frozen_support import configure_frozen_native_paths

        configure_frozen_native_paths()
        try:
            if importlib.util.find_spec("imagegen_plugins") is None:
                os.environ.setdefault("PROWSER_MIN_BUNDLE", "1")
        except Exception:
            os.environ.setdefault("PROWSER_MIN_BUNDLE", "1")
        # Backend availability logging is deferred to log_frozen_imagegen_availability_once()
        # (first Image menu open) so mflux/sdnq/whisper are not probed at process start.
except Exception:
    pass
