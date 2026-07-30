#!/usr/bin/env python3
"""Subprocess entry for image generation when running as a PyInstaller frozen app."""

from __future__ import annotations

import sys


def run_worker_main(pipeline_id: str) -> int:
    if pipeline_id == "flux_schnell_mflux_play":
        from imagegen_plugins.pipelines.mflux_schnell import main as mflux_main

        return int(mflux_main())
    if pipeline_id == "sana_sprint_600m":
        from imagegen_plugins.pipelines.sana_sprint import main as sana_main

        return int(sana_main())
    if pipeline_id == "sd15_diffusers":
        from imagegen_plugins.pipelines.sd15_diffusers import main as sd15_main

        return int(sd15_main())
    if pipeline_id == "sdxl_diffusers":
        from imagegen_plugins.pipelines.sdxl_diffusers import main as sdxl_main

        return int(sdxl_main())
    if pipeline_id in ("mflux_fill_expand", "mflux_fill_infill"):
        from imagegen_plugins.pipelines.mflux_fill_expand import main as fill_main

        return int(fill_main())
    if pipeline_id == "mflux_flux2_klein_create":
        from imagegen_plugins.pipelines.mflux_flux2_klein_create import (
            main as klein_create_main,
        )

        return int(klein_create_main())
    if pipeline_id in ("mflux_flux2_klein_edit", "mflux_flux2_klein_expand"):
        from imagegen_plugins.pipelines.mflux_flux2_klein_edit import main as klein_edit_main

        return int(klein_edit_main())
    if pipeline_id == "mflux_z_image_turbo":
        from imagegen_plugins.pipelines.mflux_z_image_turbo import main as z_image_mflux_main

        return int(z_image_mflux_main())
    if pipeline_id == "z_image_turbo_sdnq":
        from imagegen_plugins.pipelines.z_image_turbo import main as z_image_sdnq_main

        return int(z_image_sdnq_main())
    print(f"Unknown imagegen pipeline: {pipeline_id}", file=sys.stderr)
    return 2
