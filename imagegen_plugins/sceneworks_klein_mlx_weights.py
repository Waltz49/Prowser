#!/usr/bin/env python3
"""Load SceneWorks HF MLX packed-quant Klein tiers (mflux omits scales/biases)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import mlx.core as mx
import mlx.nn as nn

from imagegen_plugins.sceneworks_klein_mlx import (
    DEFAULT_MLX_TIER,
    SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
    is_sceneworks_klein_mlx_repo,
    normalize_mlx_tier,
)

_KLEIN_VARIANT = Literal["create", "edit"]


def is_sceneworks_packed_tier_path(model_path: str | None) -> bool:
    if not model_path:
        return False
    path = Path(model_path).expanduser()
    if path.name not in {"q4", "q8"}:
        return False
    return "flux2-klein-9b-kv-mlx" in str(path)


def sceneworks_tier_quant_bits(tier_path: Path) -> int:
    tier = normalize_mlx_tier(tier_path.name)
    if tier == "q4":
        return 4
    if tier == "q8":
        return 8
    for subdir in ("transformer", "text_encoder", "vae"):
        cfg_path = tier_path / subdir / "config.json"
        if not cfg_path.is_file():
            continue
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        quant = data.get("quantization") or {}
        bits = quant.get("bits")
        if bits is not None:
            return int(bits)
    raise ValueError(f"Cannot determine quantization bits for SceneWorks tier: {tier_path}")


def _extend_quant_mapping(mapping: list) -> list:
    from mflux.models.common.weights.mapping.weight_mapping import WeightTarget

    extended = list(mapping)
    for target in mapping:
        if not target.to_pattern.endswith(".weight"):
            continue
        stem = target.to_pattern[: -len(".weight")]
        for suffix in ("scales", "biases"):
            from_patterns = [
                p[: -len(".weight")] + f".{suffix}"
                for p in target.from_pattern
                if p.endswith(".weight")
            ]
            if not from_patterns:
                continue
            extended.append(
                WeightTarget(
                    to_pattern=f"{stem}.{suffix}",
                    from_pattern=from_patterns,
                    required=False,
                    transform=target.transform,
                )
            )
    return extended


def _load_safetensors_dir(component_path: Path) -> dict[str, mx.array]:
    weights: dict[str, mx.array] = {}
    for shard in sorted(component_path.glob("*.safetensors")):
        if shard.name.endswith(".index.json"):
            continue
        data = mx.load(str(shard))
        weights.update(dict(data.items()))
    if not weights:
        raise RuntimeError(f"No safetensors weights found in {component_path}")
    return weights


def _load_sceneworks_component(component_path: Path, *, mapping_getter) -> dict:
    from mflux.models.common.weights.mapping.weight_mapper import WeightMapper

    raw = _load_safetensors_dir(component_path)
    mapping = _extend_quant_mapping(mapping_getter())
    return WeightMapper.apply_mapping(raw, mapping)


def _load_sceneworks_tier_weights(tier_path: Path, *, bits: int):
    from mflux.models.common.weights.loading.loaded_weights import LoadedWeights, MetaData
    from mflux.models.flux2.weights.flux2_weight_mapping import Flux2WeightMapping

    tier_path = tier_path.expanduser()
    return LoadedWeights(
        components={
            "vae": _load_sceneworks_component(
                tier_path / "vae",
                mapping_getter=Flux2WeightMapping.get_vae_mapping,
            ),
            "transformer": _load_sceneworks_component(
                tier_path / "transformer",
                mapping_getter=Flux2WeightMapping.get_transformer_mapping,
            ),
            "text_encoder": _load_sceneworks_component(
                tier_path / "text_encoder",
                mapping_getter=Flux2WeightMapping.get_text_encoder_mapping,
            ),
        },
        meta_data=MetaData(quantization_level=bits, mflux_version=None),
    )


def init_flux2_klein_from_sceneworks_tier(
    variant: _KLEIN_VARIANT,
    *,
    model_config: Any,
    model_path: str,
    lora_paths: list[str] | None,
    lora_scales: list[float] | None,
) -> Any:
    from mflux.models.common.weights.loading.weight_applier import WeightApplier
    from mflux.models.flux2.flux2_initializer import Flux2Initializer
    from mflux.models.flux2.model.flux2_text_encoder.qwen3_text_encoder import Qwen3TextEncoder
    from mflux.models.flux2.model.flux2_transformer.transformer import Flux2Transformer
    from mflux.models.flux2.model.flux2_vae.vae import Flux2VAE
    from mflux.models.flux2.variants.edit.flux2_klein_edit import Flux2KleinEdit
    from mflux.models.flux2.variants.txt2img.flux2_klein import Flux2Klein
    from mflux.models.flux2.weights.flux2_weight_definition import Flux2KleinWeightDefinition

    tier_path = Path(model_path).expanduser()
    bits = sceneworks_tier_quant_bits(tier_path)
    weights = _load_sceneworks_tier_weights(tier_path, bits=bits)

    model_cls = Flux2KleinEdit if variant == "edit" else Flux2Klein
    model = model_cls.__new__(model_cls)
    nn.Module.__init__(model)

    Flux2Initializer._init_config(model, model_config)
    Flux2Initializer._init_tokenizers(model, str(tier_path))
    model.vae = Flux2VAE()
    model.transformer = Flux2Transformer(**model_config.transformer_overrides)
    model.text_encoder = Qwen3TextEncoder(**model_config.text_encoder_overrides)

    components = {c.name: c for c in Flux2KleinWeightDefinition.get_components()}
    models = {
        "vae": model.vae,
        "transformer": model.transformer,
        "text_encoder": model.text_encoder,
    }
    # SceneWorks quantizes the transformer only; TE + VAE stay dense bf16.
    WeightApplier._quantize(
        {"transformer": model.transformer},
        bits,
        {"transformer": components["transformer"]},
        Flux2KleinWeightDefinition,
    )
    WeightApplier._set_weights(weights, models, components)
    model.bits = bits
    Flux2Initializer._apply_lora(model, lora_paths, lora_scales)
    return model


