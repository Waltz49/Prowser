#!/usr/bin/env python3
"""Pipeline availability and local-model check dispatch tables."""

from __future__ import annotations

from typing import Callable, Dict

_FLUX2_KLEIN_WEIGHT_SUBDIRS = ("vae", "transformer", "text_encoder")
_Z_IMAGE_WEIGHT_SUBDIRS = ("vae", "transformer", "text_encoder")
_SD15_WEIGHT_SUBDIRS = ("unet", "text_encoder")
_SDXL_WEIGHT_SUBDIRS = ("unet", "text_encoder", "text_encoder_2", "vae")

ModelLocalChecker = Callable[[str], bool]
AvailabilityChecker = Callable[[], bool]


def _check_flux_schnell_available() -> bool:
    from imagegen_plugins.pipelines.mflux_schnell import mflux_is_installed

    return mflux_is_installed()


def _check_sana_available() -> bool:
    from pyinstaller_frozen_support import sana_sprint_pipeline_is_installed

    return sana_sprint_pipeline_is_installed()


def _check_sd15_available() -> bool:
    from pyinstaller_frozen_support import sd15_diffusers_pipeline_is_installed

    return sd15_diffusers_pipeline_is_installed()


def _check_sdxl_available() -> bool:
    from pyinstaller_frozen_support import sdxl_diffusers_pipeline_is_installed

    return sdxl_diffusers_pipeline_is_installed()


def _check_z_image_sdnq_available() -> bool:
    from imagegen_plugins.pipelines.z_image_turbo import z_image_turbo_is_installed

    return z_image_turbo_is_installed()


def _check_mflux_z_image_available() -> bool:
    from imagegen_plugins.pipelines.mflux_z_image_turbo import mflux_is_installed

    return mflux_is_installed()


def _check_mflux_fill_available() -> bool:
    from imagegen_plugins.pipelines.mflux_fill_expand import mflux_is_installed

    return mflux_is_installed()


def _check_mflux_klein_available() -> bool:
    from imagegen_plugins.pipelines.mflux_flux2_klein_edit import mflux_is_installed

    return mflux_is_installed()


def _check_mflux_flux_local(hf_model_id: str) -> bool:
    from imagegen_plugins.image_gen_model_availability import _mflux_flux_weights_are_local

    return _mflux_flux_weights_are_local(hf_model_id)


def _check_hf_repo_complete_local(hf_model_id: str) -> bool:
    from imagegen_plugins.image_gen_model_availability import _hf_repo_snapshot_is_complete

    return _hf_repo_snapshot_is_complete(hf_model_id)


def _check_klein_local(hf_model_id: str) -> bool:
    from imagegen_plugins.image_gen_model_availability import _hf_repo_snapshot_is_complete
    from imagegen_plugins.sceneworks_klein_mlx import (
        is_sceneworks_klein_mlx_repo,
        sceneworks_model_is_local,
    )

    if is_sceneworks_klein_mlx_repo(hf_model_id):
        return sceneworks_model_is_local(hf_model_id)
    return _hf_repo_snapshot_is_complete(hf_model_id, _FLUX2_KLEIN_WEIGHT_SUBDIRS)


def _check_sana_local(hf_model_id: str) -> bool:
    from imagegen_plugins.image_gen_model_availability import _hf_repo_snapshot_has_weights

    return _hf_repo_snapshot_has_weights(hf_model_id)


def _check_z_image_local(hf_model_id: str) -> bool:
    from imagegen_plugins.image_gen_model_availability import _hf_repo_snapshot_is_complete

    return _hf_repo_snapshot_is_complete(hf_model_id, _Z_IMAGE_WEIGHT_SUBDIRS)


def _check_sd15_local(hf_model_id: str) -> bool:
    from imagegen_plugins.hf_model_ids import SD15_DEFAULT_VAE
    from imagegen_plugins.image_gen_model_availability import (
        _hf_repo_snapshot_has_weights,
        _hf_repo_snapshot_is_complete,
    )

    if not _hf_repo_snapshot_is_complete(hf_model_id, _SD15_WEIGHT_SUBDIRS):
        return False
    if _hf_repo_snapshot_is_complete(hf_model_id, ("vae",)):
        return True
    return _hf_repo_snapshot_has_weights(SD15_DEFAULT_VAE)


def _check_sdxl_local(hf_model_id: str) -> bool:
    from imagegen_plugins.image_gen_model_availability import _hf_repo_snapshot_is_complete

    return _hf_repo_snapshot_is_complete(hf_model_id, _SDXL_WEIGHT_SUBDIRS)


def _always_local(_hf_model_id: str) -> bool:
    return True


_PIPELINE_AVAILABILITY_CHECKERS: Dict[str, AvailabilityChecker] = {
    "flux_schnell_mflux_play": _check_flux_schnell_available,
    "sana_sprint_600m": _check_sana_available,
    "sd15_diffusers": _check_sd15_available,
    "sdxl_diffusers": _check_sdxl_available,
    "z_image_turbo_sdnq": _check_z_image_sdnq_available,
    "mflux_z_image_turbo": _check_mflux_z_image_available,
    "mflux_fill_expand": _check_mflux_fill_available,
    "mflux_fill_infill": _check_mflux_fill_available,
    "mflux_flux2_klein_edit": _check_mflux_klein_available,
    "mflux_flux2_klein_create": _check_mflux_klein_available,
    "mflux_flux2_klein_expand": _check_mflux_klein_available,
}

_PIPELINE_MODEL_LOCAL_CHECKERS: Dict[str, ModelLocalChecker] = {
    "flux_schnell_mflux_play": _check_mflux_flux_local,
    "mflux_fill_expand": _check_hf_repo_complete_local,
    "mflux_fill_infill": _check_hf_repo_complete_local,
    "mflux_flux2_klein_edit": _check_klein_local,
    "mflux_flux2_klein_create": _check_klein_local,
    "mflux_flux2_klein_expand": _check_klein_local,
    "sana_sprint_600m": _check_sana_local,
    "z_image_turbo_sdnq": _check_z_image_local,
    "mflux_z_image_turbo": _check_z_image_local,
    "sd15_diffusers": _check_sd15_local,
    "sdxl_diffusers": _check_sdxl_local,
}


def pipeline_availability_checker(pipeline_id: str) -> AvailabilityChecker | None:
    return _PIPELINE_AVAILABILITY_CHECKERS.get(pipeline_id)


def pipeline_model_local_checker(pipeline_id: str) -> ModelLocalChecker:
    return _PIPELINE_MODEL_LOCAL_CHECKERS.get(pipeline_id, _always_local)
