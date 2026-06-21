# PyInstaller hook: bundle MLX native libs and Python modules (mlx.core imports mlx._reprlib_fix).
import os

if os.environ.get("PYINSTALLER_MIN_BUILD", "").strip() in ("1", "true", "yes"):
    binaries: list[tuple[str, str]] = []
    datas: list[tuple[str, str]] = []
    hiddenimports: list[str] = []
else:
    from pathlib import Path

    from PyInstaller.utils.hooks import collect_submodules

    binaries: list[tuple[str, str]] = []
    datas: list[tuple[str, str]] = []
    hiddenimports = collect_submodules("mlx")
    if "mlx._reprlib_fix" not in hiddenimports:
        hiddenimports.append("mlx._reprlib_fix")

    def _mlx_lib_dir():
        try:
            import mlx
        except ImportError:
            return None
        roots = [Path(p).resolve() for p in mlx.__path__]
        for root in roots:
            lib = root / "lib"
            if (lib / "libmlx.dylib").is_file():
                return lib
        return None

    try:
        mlx_lib = _mlx_lib_dir()
        if mlx_lib is None:
            raise ImportError("mlx lib dir not found")
        for dylib in sorted(mlx_lib.glob("*.dylib")):
            binaries.append((str(dylib), "mlx/lib"))
        metallib = mlx_lib / "mlx.metallib"
        if metallib.is_file():
            datas.append((str(metallib), "mlx/lib"))
    except Exception:
        pass
