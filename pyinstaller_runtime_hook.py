"""
PyInstaller runtime hook.
Runs before the main script in every frozen process (GUI and --model-tasks-worker).
"""
import os

# Enable JIT before the interpreter fully starts (existing Prowser behavior).
os.environ.setdefault("PYTHON_JIT", "1")

try:
    import sys

    if getattr(sys, "frozen", False):
        from pyinstaller_frozen_support import configure_frozen_native_paths, log_frozen_diagnostic

        configure_frozen_native_paths()
        try:
            from pyinstaller_frozen_support import diffusers_is_installed, mflux_is_installed

            log_frozen_diagnostic(
                f"[imagegen] startup availability mflux={mflux_is_installed()} "
                f"diffusers={diffusers_is_installed()}"
            )
            try:
                from pyinstaller_frozen_support import whisper_voice_input_is_bundled

                log_frozen_diagnostic(
                    f"[voice] whisper bundled={whisper_voice_input_is_bundled()}"
                )
            except Exception as exc:
                log_frozen_diagnostic(f"[voice] whisper bundle check failed: {exc!r}")
        except Exception as exc:
            log_frozen_diagnostic(f"[imagegen] startup availability check failed: {exc!r}")
except Exception:
    pass
