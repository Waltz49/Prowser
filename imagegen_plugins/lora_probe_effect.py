#!/usr/bin/env python3
"""Compare probe renders to detect LoRAs that load but have no visual effect."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import List, Optional

_retained_probe_temps: List[str] = []
_retained_lock = threading.Lock()

_cnn_sorter = None
_cnn_sorter_lock = threading.Lock()

# ResNet cosine similarity above this => baseline and with-LoRA renders match (no effect).
# Identical copies ~1.0; strong LoRA effects are often <0.9 (e.g. pillory ~0.6).
_DEFAULT_CNN_IDENTICAL_MIN_COSINE = 0.98


@dataclass(frozen=True)
class ProbeImageDelta:
    mean_diff: float
    max_diff: int
    phash_distance: Optional[int] = None
    cnn_cosine: Optional[float] = None


def _probe_cnn_identical_min_cosine() -> float:
    from config import get_config

    raw = (get_config().load_settings().get("imagegen") or {}).get("check_loras") or {}
    try:
        value = float(raw.get("cnn_identical_min_cosine", _DEFAULT_CNN_IDENTICAL_MIN_COSINE))
    except (TypeError, ValueError):
        value = _DEFAULT_CNN_IDENTICAL_MIN_COSINE
    return max(0.0, min(1.0, value))


def _probe_cnn_sorter():
    """Lazy ResNet feature extractor (same stack as ⌘K similarity search)."""
    global _cnn_sorter
    with _cnn_sorter_lock:
        if _cnn_sorter is not None:
            return _cnn_sorter
        from config import get_config

        settings = get_config().load_settings()
        resnet_model = str(settings.get("resnet_model") or "resnet18")
        cache_dir = str(get_config().image_recognition_cache_dir)
        from search.cnn_image_similarity_sorter import CNNImageSimilaritySorter

        _cnn_sorter = CNNImageSimilaritySorter(
            similarity_metric="cosine",
            cache_dir=cache_dir,
            resnet_model=resnet_model,
        )
        return _cnn_sorter


def measure_probe_cnn_cosine(path_a: str, path_b: str) -> Optional[float]:
    """
    Cosine similarity of ResNet features (0–1, higher = more alike).

    Returns None when CNN/torch cannot load or either image fails to encode.
    """
    if not path_a or not path_b:
        return None
    if not os.path.isfile(path_a) or not os.path.isfile(path_b):
        return None
    try:
        sorter = _probe_cnn_sorter()
        feat_a = sorter._get_feature(path_a)
        feat_b = sorter._get_feature(path_b)
        if feat_a is None or feat_b is None:
            return None
        return float(sorter._compute_similarity(feat_a, feat_b))
    except Exception as exc:
        print(f"[Check LoRAs] CNN probe compare failed: {exc}")
        return None


def measure_probe_image_delta(
    path_a: str,
    path_b: str,
    *,
    use_cnn: bool = True,
) -> ProbeImageDelta:
    """Pixel/phash delta plus optional CNN cosine (ResNet, same as ⌘K search)."""
    from PIL import Image, ImageChops, ImageStat

    with Image.open(path_a) as img_a, Image.open(path_b) as img_b:
        a = img_a.convert("RGB")
        b = img_b.convert("RGB")
        if a.size != b.size:
            b = b.resize(a.size, Image.Resampling.BILINEAR)
        diff = ImageChops.difference(a, b)
        stat = ImageStat.Stat(diff)
        mean_diff = sum(stat.mean) / max(1, len(stat.mean))
        max_diff = max(ext[1] for ext in stat.extrema)

    phash_distance: Optional[int] = None
    try:
        import imagehash

        with Image.open(path_a) as img_a, Image.open(path_b) as img_b:
            phash_distance = int(imagehash.phash(img_a) - imagehash.phash(img_b))
    except ImportError:
        pass

    cnn_cosine: Optional[float] = None
    if use_cnn:
        cnn_cosine = measure_probe_cnn_cosine(path_a, path_b)

    return ProbeImageDelta(
        mean_diff=float(mean_diff),
        max_diff=int(max_diff),
        phash_distance=phash_distance,
        cnn_cosine=cnn_cosine,
    )


def probe_images_effectively_identical(delta: ProbeImageDelta) -> bool:
    """
    True when two renders are effectively the same (LoRA had no effect).

    Prefers ResNet CNN cosine (⌘K stack) so color-matched but structurally
    different images are not treated as identical. Falls back to pixel/phash
    only when CNN is unavailable.
    """
    threshold = _probe_cnn_identical_min_cosine()
    if delta.cnn_cosine is not None:
        return delta.cnn_cosine >= threshold

    if delta.mean_diff < 0.01 and delta.max_diff < 1:
        return True
    if (
        delta.phash_distance is not None
        and delta.phash_distance == 0
        and delta.mean_diff < 0.1
        and delta.max_diff < 2
    ):
        return True
    return False


def retain_lora_probe_temp(path: Optional[str]) -> None:
    """Keep a probe render until app quit (for manual inspection)."""
    if not path or not str(path).strip():
        return
    ap = os.path.abspath(str(path))
    with _retained_lock:
        if ap not in _retained_probe_temps:
            _retained_probe_temps.append(ap)


def cleanup_lora_probe_temps() -> None:
    """Remove retained Check LoRAs probe images (call on app quit)."""
    with _retained_lock:
        paths = list(_retained_probe_temps)
        _retained_probe_temps.clear()
    for path in paths:
        try:
            if os.path.isfile(path):
                os.unlink(path)
        except OSError:
            pass


@dataclass
class LoraProbeBaselineCache:
    """One shared no-LoRA baseline render per model + probe prompt per Check LoRAs run."""

    model_key: str = ""
    prompt: str = ""
    width: int = 0
    height: int = 0
    steps: int = 0
    path: str = ""

    def lookup(
        self,
        *,
        model_key: str,
        prompt: str,
        width: int,
        height: int,
        steps: int,
    ) -> Optional[str]:
        if (
            self.path
            and self.model_key == model_key
            and self.prompt == prompt
            and self.width == width
            and self.height == height
            and self.steps == steps
            and os.path.isfile(self.path)
        ):
            return self.path
        return None

    def store(
        self,
        *,
        model_key: str,
        prompt: str,
        width: int,
        height: int,
        steps: int,
        path: str,
    ) -> None:
        self.model_key = model_key
        self.prompt = prompt
        self.width = width
        self.height = height
        self.steps = steps
        self.path = path
        retain_lora_probe_temp(path)

    def reset_for_model(self, model_key: str) -> None:
        if self.model_key != model_key:
            self.model_key = ""
            self.prompt = ""
            self.width = 0
            self.height = 0
            self.steps = 0
            self.path = ""


# Back-compat alias (Z-Image was the first consumer).
ZImageBaselineCache = LoraProbeBaselineCache
