#!/usr/bin/env python3
"""FLUX.1 text-to-image (Schnell/Dev) LoRA catalog."""

from __future__ import annotations

from typing import Dict

from imagegen_plugins.lora_catalogs._common import t2i_entry
from imagegen_plugins.lora_entry import FluxLoraEntry, PAPER_CUTOUT_LORA_PATH

FLUX1_T2I_LORAS: Dict[str, FluxLoraEntry] = {
    "mspaint1": t2i_entry(
        "mspaint1",
        "MS Paint style",
        "glif-loradex-trainer/fabian3000_mspaint1",
        "mspaint1.safetensors",
        mflux_compatible=True,
    ),
    "super_realism": t2i_entry(
        "super_realism",
        "Realism (arch)",
        "mnml-ai/flux-arch-realism-lora",
        "flux-arch-realism-lora_v1.safetensors",
        mflux_compatible=True,
    ),
    "sldr_nsfw_v2": t2i_entry(
        "sldr_nsfw_v2",
        "SLDR NSFW v2 (studio)",
        "aifeifei798/sldr_flux_nsfw_v2-studio",
        "sldr_flux_nsfw_v2-studio.safetensors",
        mflux_compatible=True,
    ),
    "pola_photo_flux": t2i_entry(
        "pola_photo_flux",
        "Pola photo",
        "alvdansen/pola-photo-flux",
        "pola_photo_araminta_k.safetensors",
        mflux_compatible=True,
    ),
    "paper_cutout": FluxLoraEntry(
        host_id="flux1_t2i",
        lora_id="paper_cutout",
        display_name="Paper cutout (local)",
        local_path=str(PAPER_CUTOUT_LORA_PATH),
        scale=1.0,
        mflux_model="dev",
        mflux_compatible=True,
    ),
    "flux_uncensored": t2i_entry(
        "flux_uncensored",
        "Flux uncensored",
        "kenerateai/Flux-uncensored",
        "lora.safetensors",
    ),
    "ms_paint_drawing": t2i_entry(
        "ms_paint_drawing",
        "MS Paint drawing",
        "multimodalart/ms-paint-drawing-flux",
        "ms_paint_flux_lora_aitoolkit_000003000.safetensors",
    ),
    "pixar_3d": t2i_entry(
        "pixar_3d",
        "Pixar 3D",
        "prithivMLmods/Canopus-Pixar-3D-Flux-LoRA",
        "Canopus-Pixar-3D-FluxDev-LoRA.safetensors",
    ),
    "sadie_sink": t2i_entry(
        "sadie_sink",
        "Sadie Sink",
        "playboy40k/flux-SadieSinkLora",
        "sadie-sink.safetensors",
    ),
    "minimal_futuristic": t2i_entry(
        "minimal_futuristic",
        "Minimal futuristic",
        "prithivMLmods/Minimal-Futuristic-Flux-LoRA",
        "Minimal-Futuristic.safetensors",
    ),
    "engrave": t2i_entry(
        "engrave",
        "Engrave",
        "gokaygokay/Flux-Engrave-LoRA",
        "engrave.safetensors",
    ),
    "ghibli": t2i_entry(
        "ghibli",
        "Ghibli",
        "InstantX/FLUX.1-dev-LoRA-Ghibli",
        "ghibli_style.safetensors",
    ),
    "makoto_shinkai": t2i_entry(
        "makoto_shinkai",
        "Makoto Shinkai",
        "InstantX/FLUX.1-dev-LoRA-Makoto-Shinkai",
        "Makoto_Shinkai_style.safetensors",
    ),
    "retro_anime": t2i_entry(
        "retro_anime",
        "Retro anime",
        "Muapi/retro-anime-flux-style",
        "retro-anime-flux-style.safetensors",
    ),
    "sailor_moon_anime": t2i_entry(
        "sailor_moon_anime",
        "Sailor moon anime",
        "Muapi/sailor-moon-esque-retro-anime-style-lora-flux",
        "sailor-moon-esque-retro-anime-style-lora-flux.safetensors",
    ),
    "dnd_covers": t2i_entry(
        "dnd_covers",
        "D&D covers",
        "Muapi/dungeons-and-dragons-covers-dnd-5e",
        "dungeons-and-dragons-covers-dnd-5e.safetensors",
    ),
    "art_deco": t2i_entry(
        "art_deco",
        "Art deco",
        "Muapi/art-deco-style-flux1.d",
        "art-deco-style-flux1.d.safetensors",
    ),
    "klimt": t2i_entry(
        "klimt",
        "Klimt ornamental",
        "Mari-ano/Gustav-Klimt-Ornamental-Symbolist-Aesthetic",
        "gustklim.safetensors",
    ),
    "midsummer_blues": t2i_entry(
        "midsummer_blues",
        "Midsummer blues",
        "Muapi/flux-midsummer-blues",
        "flux-midsummer-blues.safetensors",
    ),
    "microworld_nft": t2i_entry(
        "microworld_nft",
        "Microworld NFT",
        "strangerzonehf/Flux-Microworld-NFT-LoRA",
        "Microworld-NFT.safetensors",
    ),
    "big_boobs_clothed": t2i_entry(
        "big_boobs_clothed",
        "Big boobs clothed",
        "DavidBaloches/Big_Boobs_Clothed",
        "big-boobs-clothed-v2.safetensors",
    ),
    "big_boobs_clothed_v2": t2i_entry(
        "big_boobs_clothed_v2",
        "Big boobs clothed (v2)",
        "aifeifei798/big-boobs-clothed",
        "big-boobs-clothed-v2.safetensors",
    ),
    "sideboob": t2i_entry(
        "sideboob",
        "Sideboob",
        "Genner2025/sideboob",
        "Candid_Armhole_Sideboob_Nipslip-000003.safetensors",
    ),
    "fluxpony": t2i_entry(
        "fluxpony",
        "Fluxpony",
        "uriel353/fluxpony-perfect-full-round-breasts-and-slim-waist_V3_R128",
        "fluxpony-perfect-full-round-breasts-and-slim-waist.safetensors",
    ),
    "pizzacake_art": t2i_entry(
        "pizzacake_art",
        "Pizzacake art style",
        "Muapi/pizzacake-ellen-woodbury-art-style-flux-illustrious-pony",
        "pizzacake-ellen-woodbury-art-style-flux-illustrious-pony.safetensors",
    ),
    "feifei_v1": t2i_entry(
        "feifei_v1",
        "Feifei v1",
        "aifeifei798/feifei-flux-lora-v1",
        "mj.safetensors",
    ),
    "sarah_mcdaniel": t2i_entry(
        "sarah_mcdaniel",
        "Sarah McDaniel",
        "Keltezaa/SarahMcDaniel",
        "SarahMcDaniel_rank16_bf16-step00750.safetensors",
    ),
    "ms_paint_alt": t2i_entry(
        "ms_paint_alt",
        "MS Paint drawing (alt)",
        "multimodalart/ms-paint-drawing-flux",
        "ms_paint_flux_lora_aitoolkit_000003000.safetensors",
    ),
}
