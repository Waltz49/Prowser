#!/usr/bin/env python3
"""Benchmark ImageGen pipeline availability probes (for cProfile)."""

from __future__ import annotations

from imagegen_plugins import discover_plugins
from imagegen_plugins.image_gen_pipeline_modes import (
    PIPELINE_MODES,
    pipeline_is_available,
    warm_pipeline_availability_cache,
)


def main() -> None:
    plugins = discover_plugins()
    warm_pipeline_availability_cache(plugins)
    for pipeline_id in PIPELINE_MODES:
        pipeline_is_available(pipeline_id)


if __name__ == "__main__":
    main()
