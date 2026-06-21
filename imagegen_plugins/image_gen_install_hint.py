#!/usr/bin/env python3
"""User-facing hint when optional image-generation backends are not installed."""

from __future__ import annotations

import sys

from imagegen_plugins.image_gen_registry import ImageGenModelPlugin


def imagegen_backend_missing_message(plugin: ImageGenModelPlugin) -> str:
    name = plugin.display_name
    if plugin.pipeline_id == "sana_sprint_600m":
        if getattr(sys, "frozen", False):
            return (
                f"{name} requires diffusers (PyTorch), which could not be loaded from this app bundle.\n\n"
                "Rebuild with ./pyInstallerBuild.sh (ensure diffusers and torch are in the build venv).\n\n"
                "Or run from source after:\n"
                "  pip install -r minimal_requirements.txt"
            )
        return (
            f"{name} requires the diffusers Python package, which is not installed in this environment.\n\n"
            "From the Prowser project directory, with your virtual environment activated:\n"
            "  pip install -r minimal_requirements.txt\n\n"
            "Then restart Prowser."
        )
    if plugin.pipeline_id == "z_image_turbo_sdnq":
        if getattr(sys, "frozen", False):
            return (
                f"{name} requires diffusers and sdnq (PyTorch), which could not be loaded from this app bundle.\n\n"
                "Rebuild with ./pyInstallerBuild.sh (ensure diffusers, sdnq, and torch are in the build venv).\n\n"
                "Or run from source after:\n"
                "  pip install -r minimal_requirements.txt"
            )
        return (
            f"{name} requires diffusers and sdnq, which are not installed in this environment.\n\n"
            "From the Prowser project directory, with your virtual environment activated:\n"
            "  pip install -r minimal_requirements.txt\n\n"
            "Then restart Prowser."
        )
    if plugin.pipeline_id in (
        "mflux_fill_expand",
        "mflux_fill_infill",
        "mflux_flux2_klein_edit",
        "mflux_flux2_klein_create",
    ):
        if plugin.pipeline_id in ("mflux_fill_expand", "mflux_fill_infill"):
            product = "FLUX Fill"
        elif plugin.hf_model_id and "/" in plugin.hf_model_id:
            product = plugin.hf_model_id.split("/")[-1].replace(".", " ").replace("-", " ")
        else:
            product = "FLUX.2 Klein"
        if getattr(sys, "frozen", False):
            return (
                f"{name} requires the MFLUX/MLX backend for {product}, which could not be loaded "
                "from this app bundle.\n\n"
                "Rebuild with ./pyInstallerBuild.sh (ensure mflux and mlx are installed in the build venv).\n\n"
                "Or run from source after:\n"
                "  pip install -r minimal_requirements.txt"
            )
        return (
            f"{name} requires the MFLUX Python package for {product}, which is not installed "
            "in this environment.\n\n"
            "From the Prowser project directory, with your virtual environment activated:\n"
            "  pip install -r minimal_requirements.txt\n\n"
            "Then restart Prowser."
        )
    if getattr(sys, "frozen", False):
        return (
            f"{name} requires the MFLUX/MLX backend, which could not be loaded from this app bundle.\n\n"
            "Rebuild with ./pyInstallerBuild.sh (ensure mflux and mlx are installed in the build venv).\n"
            "If generation fails with an MLX extension error, open Tools > Debug > View log for details.\n\n"
            "Or run from source after:\n"
            "  pip install -r minimal_requirements.txt"
        )
    return (
        f"{name} requires the MFLUX Python package, which is not installed in this environment.\n\n"
        "From the Prowser project directory, with your virtual environment activated:\n"
        "  pip install -r minimal_requirements.txt\n\n"
        "Then restart Prowser."
    )
