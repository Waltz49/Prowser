#!/usr/bin/env python3
"""Back-compat re-exports for LoRA catalog (prefer imagegen_plugins.lora_catalog)."""

from imagegen_plugins.lora_catalog import *  # noqa: F403
from imagegen_plugins.lora_catalog import (  # explicit: import * skips _-prefixed names
    _lora_download_local_dir,
    sample_flux_lora_download_entries,
)
from imagegen_plugins.lora_catalog_settings import migrate_lora_catalog
from imagegen_plugins.lora_entry import (
    DEFAULT_CACHE,
    DEFAULT_ENABLED_LORA_IDS,
    FluxLoraEntry,
    LORA_MIN_STEPS,
    PAPER_CUTOUT_LORA_PATH,
    _ALT_CACHE,
)
from imagegen_plugins.hf_model_ids import (
    LORA_MODEL_DISPLAY_NAMES,
    LORA_PROBE_MODEL_ORDER,
    lora_model_display_name,
)

# Back-compat alias.
LORA_MODEL_ABBREV = LORA_MODEL_DISPLAY_NAMES
