#!/usr/bin/env python3
"""FLUX.2 Klein edit LoRAs (curated Hugging Face adapters; install via Settings)."""

from __future__ import annotations

from typing import Dict

from imagegen_plugins.lora_catalogs._common import klein_entry
from imagegen_plugins.lora_entry import FluxLoraEntry

# klein_variant must match the edit model (flux2-klein-4b vs flux2-klein-9b).
# Mixing 9B LoRA with 4B model causes MLX broadcast_shapes (3072) vs (4096) errors.

FLUX2_KLEIN_LORAS: Dict[str, FluxLoraEntry] = {
    "klein_consistency_v2": klein_entry(
        "klein_consistency_v2",
        "Klein consistency V2 (9B)",
        "dx8152/Flux2-Klein-9B-Consistency",
        "Flux2-Klein-9B-consistency-V2.safetensors",
        klein_variant="9b",
        scale=1.0,
    ),
    "klein_consistency_v1": klein_entry(
        "klein_consistency_v1",
        "Klein consistency V1 (9B)",
        "dx8152/Flux2-Klein-9B-Consistency",
        "Klein-consistency.safetensors",
        klein_variant="9b",
        scale=1.0,
    ),
    "klein_pixel_art": klein_entry(
        "klein_pixel_art",
        "Pixel art sprites (4B)",
        "Limbicnation/pixel-art-lora",
        "pytorch_lora_weights.safetensors",
        klein_variant="4b",
        scale=1.0,
    ),
    "klein_delight": klein_entry(
        "klein_delight",
        "Delight lighting (9B)",
        "linoyts/Flux2-Klein-Delight-LoRA",
        "pytorch_lora_weights_v2.safetensors",
        klein_variant="9b",
        scale=1.0,
    ),
    "klein_delight_v1": klein_entry(
        "klein_delight_v1",
        "Delight lighting v1 (9B)",
        "linoyts/Flux2-Klein-Delight-LoRA",
        "pytorch_lora_weights.safetensors",
        klein_variant="9b",
        scale=1.0,
    ),
    "klein_bbox_edit": klein_entry(
        "klein_bbox_edit",
        "BBox drag-drop edit (9B)",
        "linoyts/flux2-klein-bbox-drag-drop-lora",
        "pytorch_lora_weights.safetensors",
        klein_variant="9b",
        scale=1.0,
    ),
    "klein_ac_style": klein_entry(
        "klein_ac_style",
        "AC style low-res (9B)",
        "joyfox/FLUX.2-klein-AC-Style-LORA",
        "flux2_klein_lowres.safetensors",
        klein_variant="9b",
        scale=1.0,
    ),
    "klein_vintage_cover_4b": klein_entry(
        "klein_vintage_cover_4b",
        "Vintage book cover (4B)",
        "Norod78/flux2-klein-4b-base-lora-vintage-book-cover",
        "flux2-klein-4b-base-lora-vintage-book-cover.safetensors",
        klein_variant="4b",
        scale=1.0,
    ),
    "klein_light_fantasy_4b": klein_entry(
        "klein_light_fantasy_4b",
        "Light fantasy painting (4B)",
        "giannisan/light-fantasy-flux2-klein-lora",
        "pytorch_lora_weights.safetensors",
        klein_variant="4b",
        scale=1.0,
    ),
    "klein_dog_4b": klein_entry(
        "klein_dog_4b",
        "Dog subject (4B DreamBooth)",
        "MarioAlviano/lora-dog-flux2-klein-4b",
        "pytorch_lora_weights.safetensors",
        klein_variant="4b",
        scale=1.0,
    ),
    "klein_dever_arcane": klein_entry(
        "klein_dever_arcane",
        "Dever arcane visual (9B)",
        "DeverStyle/Flux.2-Klein-Loras",
        "dever_arcane_f2k_9b (arcane_visual_style).safetensors",
        klein_variant="9b",
        scale=1.0,
    ),
    "klein_dever_wireframe": klein_entry(
        "klein_dever_wireframe",
        "Dever blueprint wireframe (9B)",
        "DeverStyle/Flux.2-Klein-Loras",
        "dever_blueprint_wireframe_f2k_9b (dvr_wf_style).safetensors",
        klein_variant="9b",
        scale=1.0,
    ),
    "klein_dever_dmc": klein_entry(
        "klein_dever_dmc",
        "Dever Devil May Cry style (9B)",
        "DeverStyle/Flux.2-Klein-Loras",
        "dever_devil_may_cry_f2k_9b (dmc_style).safetensors",
        klein_variant="9b",
        scale=1.0,
    ),
    "klein_dever_sts2": klein_entry(
        "klein_dever_sts2",
        "Dever Slay the Spire 2 (9B)",
        "DeverStyle/Flux.2-Klein-Loras",
        "dever_slay_the_spire2_with_cards_f2k_9b (sts2_style).safetensors",
        klein_variant="9b",
        scale=1.0,
    ),
    "klein_distill_extract_128": klein_entry(
        "klein_distill_extract_128",
        "Distilled 9B extract rank-128",
        "vafipas663/flux2-klein-base-9b-distill-lora",
        "flux-2-klein-9b_extracted_lora_rank_128-fp32.safetensors",
        klein_variant="9b",
        scale=1.0,
    ),
}
