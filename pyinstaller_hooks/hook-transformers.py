# PyInstaller hook: full transformers for Create-menu builds; CLIP subset for --min.
import os

if os.environ.get("PYINSTALLER_MIN_BUILD", "").strip() in ("1", "true", "yes"):
    from PyInstaller.utils.hooks import copy_metadata

    hiddenimports = [
        "transformers",
        "transformers.models.clip",
        "transformers.models.clip.configuration_clip",
        "transformers.models.clip.modeling_clip",
        "transformers.models.clip.processing_clip",
        "transformers.image_processing_utils",
        "transformers.image_transforms",
        "transformers.feature_extraction_utils",
        "transformers.tokenization_utils_base",
        "transformers.processing_utils",
    ]
    datas: list[tuple[str, str]] = []
    binaries: list[tuple[str, str]] = []
    for _pkg in (
        "transformers",
        "packaging",
        "filelock",
        "tqdm",
        "regex",
        "PyYAML",
        "tokenizers",
        "huggingface-hub",
        "safetensors",
    ):
        try:
            datas += copy_metadata(_pkg)
        except Exception:
            pass
else:
    from PyInstaller.utils.hooks import collect_all

    datas, binaries, hiddenimports = collect_all("transformers")
