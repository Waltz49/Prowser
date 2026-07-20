# Image Create Plugins — User Guide

Prowser can generate and modify images locally from the **Image** menu. Each model (for example “FLUX.1 Schnell MFLUX” or “SANA Sprint 0.6B 1024px”) is a **model plugin**. Plugins are optional: if nothing is installed, menu items are disabled with install hints. The **Image** menu itself is hidden in `--min` PyInstaller builds.

This guide explains how the system works and how to add a new model without touching unrelated parts of the app.

---

## Using the Image menu in Prowser

1. Open Prowser with at least one plugin's dependencies installed (see [Dependencies](#dependencies) below).
2. Use the menu bar: **Image → [function]** (for example “Create an image from text…”).
   - Pick the model in the dialog dropdown for that function.
   - **Image → Create or Modify — …** (or **⌥/**) opens the dialog for the **last-used function**.
3. Fill in the prompt and settings, then click **Generate**.
4. When generation finishes, the new image opens in browse view. Files are named `imagegen-0001.png`, `imagegen-0002.png`, and so on, in your image creation folder (by default `~/Downloads`, or a custom folder from settings).
5. While a job runs, use **Image → Cancel Generation / Caption** or the status-bar indicator to cancel.
6. **Image → Job Queue…** (**Cmd+J**) shows queued and running jobs.

### Functions

| Function | Menu item | Purpose |
|----------|-----------|---------|
| `create` | Create an image from text… | Text-to-image |
| `edit` | Edit an image with AI… | Image-to-image edit |
| `expand` | Expand existing image… | Outpaint / expand canvas |
| `infill` | Infill with Pixelmator… | Mask-based infill via Pixelmator Pro |
| `infill_paint` | Infill by painting… | Paint a mask in-app, then infill |

Settings for each model (sliders, seed, etc.) are saved per function and plugin in `~/.prowser/data/settings.json` under `imagegen.dialogs.<function>.<plugin_id>` (legacy keys under `imagegen.models.<plugin_id>` are migrated on load). The active model per function is stored in `imagegen.active_plugin_by_function`; the last-used function (for ⌥/) is `imagegen.last_function`.

---

## Architecture in plain terms

The design splits **what the user sees** (plugin) from **how images are actually generated** (pipeline).

| Layer | Role | Typical files |
|--------|------|----------------|
| **Plugin** | One model entry: display name, default parameters, Hugging Face model id, function (`create` / `edit` / …) | `imagegen_plugins/flux_schnell_mflux.py` |
| **Pipeline** | Shared backend: UI field rules, worker script, availability check | `image_gen_pipeline_modes.py`, `imagegen_plugins/pipelines/my_backend.py` |
| **Worker** | Runs in a background process so the UI stays responsive | `workers/model_tasks_worker.py` dispatches by `pipeline_id` |

```text
  Image menu                   Main window (Qt)
       │                              │
       ▼                              ▼
  discover_plugins()          ImageGenUnifiedDialog (stacked panels)
       │                      ├─ ImageGenDialog (create)
       │                      ├─ ImageGenEditDialog
       │                      ├─ ImageGenExpandDialog
       │                      ├─ ImageGenInfillDialog
       │                      └─ ImageGenInfillPaintDialog
       ▼                              │
  ImageGenModelPlugin  ──────►  ImageGenController
       │                              │
       │ build_payload()              │ start_generate_job()
       ▼                              ▼
  JSON payload  ──────────────►  workers/model_tasks_worker (subprocess)
                                        │
                                        ▼
                                 pipelines/*.py → run_from_payload()
```

**Isolation:** Model-specific code (loading weights, calling diffusers or MFLUX, etc.) should live only under `imagegen_plugins/pipelines/`. The rest of Prowser talks to plugins through the small `ImageGenModelPlugin` API and JSON payloads.

**One worker:** Image generation, LM Studio captions, and flux-prompt refinement share a single background worker process. Only one job runs at a time. After each generate job, the worker unloads the image model to free memory.

---

## Directory layout

```text
imagegen_plugins/
  __init__.py                 # discover_plugins() — register menu entries here
  image_gen_registry.py       # ImageGenModelPlugin class
  image_gen_pipeline_modes.py # PipelineMode table, dialog fields, payload builder
  image_gen_menu.py           # Image menu, ⌥/ shortcut
  image_gen_unified_dialog.py # Single window; stacked per-function panels
  image_gen_dialog.py         # Create (text-to-image) panel
  image_gen_edit_dialog.py    # Edit panel
  image_gen_expand_dialog.py  # Expand / outpaint panel
  image_gen_infill_dialog.py  # Pixelmator infill panel
  image_gen_infill_paint_dialog.py  # Paint-mask infill panel
  image_gen_controller.py     # Start/cancel jobs, open result in browse
  image_gen_persistence.py    # Save/load per-model settings (thread-safe)
  image_gen_active_model.py   # active_plugin_by_function, last_function
  image_gen_model_selector.py # Model dropdown; installed vs available
  image_gen_model_availability.py  # “Download model?” before first run
  image_gen_install_hint.py   # Message when backend package is missing
  image_gen_job_queue_dialog.py  # Job queue UI
  lora_catalogs/              # Per-host LoRA catalogs (FLUX1 T2I/Fill, Klein, SD15)
  lora_catalog.py             # Unified catalog facade
  lora_catalog_settings.py    # by_host / by_model state in settings.json
  lora_host_registry.py       # Which catalog applies to which pipeline
  lora_model_registry.py      # Per-base-model LoRA compatibility
  mflux_lora_presets.py       # MFLUX LoRA download, key check, payload wiring
  sd15_lora_presets.py        # SD 1.5 LoRA (peft) download and payload wiring
  sd15_plugin_shared.py       # Shared SD 1.5 create dialog field layout
  sceneworks_klein_mlx.py     # SceneWorks MLX tier helpers (Q4/Q8/BF16)
  flux_schnell_mflux.py       # Example create plugin (thin)
  sana_sprint_600m.py         # Example create plugin (thin)
  flux_klein_create.py        # FLUX.2 Klein create variants
  flux_klein_edit.py            # FLUX.2 Klein edit variants
  flux_klein_expand.py          # FLUX.2 Klein expand variants
  flux_klein_sceneworks.py      # SceneWorks pre-quantized Klein 9B KV MLX
  flux_fill_expand.py           # FLUX.1 Fill expand
  flux_fill_infill.py           # FLUX.1 Fill infill
  realistic_vision_v4_sd15.py    # SD 1.5 example
  anything_furry_sd15.py        # SD 1.5 anime/furry example
  pipelines/
    mflux_schnell.py            # FLUX via MFLUX/MLX
    sana_sprint.py              # SANA via diffusers
    sd15_diffusers.py           # Stable Diffusion 1.5 (+ peft LoRA)
    z_image_turbo.py            # Z-Image Turbo SDNQ
    mflux_fill_expand.py        # FLUX Fill expand/infill
    mflux_flux2_klein_create.py # FLUX.2 Klein create
    mflux_flux2_klein_edit.py   # FLUX.2 Klein edit/expand
```

At the app root:

- `workers/model_tasks_worker.py` — routes `payload["pipeline_id"]` to the right `run_from_payload()`.
- `workers/model_tasks_controller.py` — Qt wrapper around the worker process.

---

## Plugins vs pipelines

- **`plugin_id`** — Unique id for settings and the model dropdown (e.g. `sana_sprint_600m`). One plugin row per model.
- **`pipeline_id`** — Which backend implementation to run (e.g. `sana_sprint_600m`). Several plugins can share one pipeline with different defaults (for example three FLUX.2 Klein sizes on `mflux_flux2_klein_create`).
- **`function`** — Which Image menu function this plugin appears under (`create`, `edit`, `expand`, `infill`).

A **plugin file** is usually short: it constructs one or more `ImageGenModelPlugin` instances with display name, `hf_model_id`, `model_defaults`, and optional `field_layout_builder`.

A **pipeline** defines step/guidance/dimension limits, the worker script under `pipelines/`, and how to test if the backend is installed (`pipeline_is_available`).

The model dropdown (`image_gen_model_selector.py`) lists only **installed** plugins for each function: the pipeline backend must be present and model weights must already be in the Hugging Face cache. Plugins with missing deps or weights show as unavailable with install/download hints.

---

## Dialog fields

Fields are declared with `FieldSpec` in `image_gen_fields.py` and composed via `image_gen_field_blocks.py`. Supported kinds:

| Kind | UI control |
|------|------------|
| `text` | Multi-line text (prompt, negative prompt) |
| `int_slider` | Slider + spin box |
| `float_slider` | Slider + label |
| `bool` | Checkbox |
| `choice` | Dropdown |
| `seed` | Integer seed |

Common fields (prompt, width, height, steps, guidance, seed, random seed) are added automatically from `PipelineMode`. Pipeline-specific fields are added in per-plugin `field_layout_builder` functions or `field_specs_for_pipeline()`.

---

## LoRA adapters

LoRA dropdowns appear when a plugin declares a `lora_host_id`. Which adapters appear is controlled in **Settings → LoRA** (per base model).

| Piece | Role |
|-------|------|
| `imagegen_plugins/lora_catalogs/` | Curated catalogs per host (FLUX1 T2I, FLUX1 Fill, FLUX2 Klein, SD15) |
| `imagegen_plugins/lora_catalog_settings.py` | `by_host`, `by_model`, `user_entries`, `entry_overrides` in settings |
| `settings.json` → `imagegen.lora_catalog` | Enabled/hidden ids per host and per base model |
| `imagegen_plugins/mflux_lora_presets.py` / `sd15_lora_presets.py` | Download weights, compatibility check, payload wiring |

**Behavior:**

- Enable LoRAs in **Settings → LoRA**. Checked entries (plus any already downloaded) appear in the dialog when compatible with that pipeline and base model.
- Trash an entry to hide it; hidden ids are stored in `hidden_ids` (per host and per model slice).
- Weights download from Hugging Face on first generate.
- Only **MFLUX verified** entries are known good for MFLUX pipelines; untested entries need a successful local run.
- SD 1.5 LoRAs use **peft** in `sd15_diffusers.py`; Klein Edit does not expose LoRA (different architecture).
- Import custom LoRAs via **Settings → LoRA → Import** (`lora_import_dialog.py`).

To add catalog entries at dev time, inspect repos with `scripts/build_flux_lora_catalog_snippet.py` and edit the appropriate file under `lora_catalogs/`.

---

## Worker contract

Each pipeline module should implement:

1. **`run_from_payload(payload: dict) -> dict`**  
   Required keys include at least:
   - `prompt` (non-empty string for create; may differ for edit/expand)
   - `width`, `height`, `steps`, `guidance_scale`
   - `output_path` — where to write the PNG
   - `pipeline_id`, `hf_model_id`
   - `random_seed` / `seed`

   Return value should include:
   - `output_path`
   - `seed` (actual seed used, especially when `random_seed` is true)

2. **Optional: availability helper**  
   e.g. `mflux_is_installed()` or `diffusers_is_installed()` for `pipeline_is_available()`.

3. **Optional: `unload_pipeline()`**  
   Release GPU/MPS memory when the worker finishes a job.

For progressive preview (MFLUX stepwise PNGs), the worker may print JSON lines to stdout with `"type": "progress"` and `"path"`.

`workers/model_tasks_worker.py` must include a branch for your `pipeline_id`. Without that branch, generation fails with “Unknown imagegen pipeline_id”.

---

## Dependencies

Install from the Prowser project directory with your venv activated:

```bash
pip install -r requirements.txt
```

(`setup.sh` installs from `minimal_requirements.txt`, which is kept in sync with `requirements.txt`.)

| Backend | Packages | Used by |
|---------|----------|---------|
| MFLUX / MLX | `mflux` (and MLX stack it pulls in) | FLUX Schnell, Fill, Klein, SceneWorks plugins |
| diffusers | `diffusers`, `accelerate`, `torch` | SANA Sprint, SD 1.5 plugins |
| SD 1.5 LoRA | `peft` | SD 1.5 pipelines with LoRA adapters |
| SDNQ | `sdnq` (via Z-Image pipeline) | Z-Image Turbo plugin |

If a backend is missing, that model appears disabled with a tooltip pointing at `requirements.txt`.

**First-time model weights:** On first generate, Prowser may ask to download several gigabytes from Hugging Face. Weights are cached in the standard Hugging Face hub cache. For gated models, set `HF_TOKEN` or run `hf auth login`.

---

## How to add a new model (checklist)

### 1. Implement the pipeline worker

Create `imagegen_plugins/pipelines/your_backend.py`:

- Implement `run_from_payload(payload)`.
- Keep all imports of heavy libraries inside functions so the main app can start without them.
- Align width/height to what your model expects (see `align_mflux_dims` / `align_sana_sprint_dims` in existing files).
- Write the final image to `payload["output_path"]`.

### 2. Register the pipeline mode

In `imagegen_plugins/image_gen_pipeline_modes.py`:

1. Add a `PipelineMode(...)` entry to `PIPELINE_MODES`.
2. Extend `pipeline_is_available()` to call your install check.
3. Extend `field_specs_for_pipeline()` for any extra dialog fields.

### 3. Add the plugin entry

Create `imagegen_plugins/your_model.py` with one or more `ImageGenModelPlugin` instances. Set `function=` to the appropriate Image menu function.

Register in `imagegen_plugins/__init__.py` inside `discover_plugins()` (wrap imports in `try/except ImportError`).

### 4. Wire the worker router

In `workers/model_tasks_worker.py`, inside `_run_generate()`, add a branch for your `pipeline_id`.

If your backend needs cleanup after each job, hook it in `_unload_image_model()`.

For PyInstaller bundles, also add a branch in `imagegen_plugins/image_gen_worker_entry.py` if you use the `--imagegen-worker` entry point.

### 5. User-facing messages

- **`image_gen_install_hint.py`** — Short message if `pipeline_is_available()` is false.
- **`image_gen_model_availability.py`** — Download confirmation before first run.

### 6. Dependencies

Add new Python packages to `requirements.txt` (and regenerate `minimal_requirements.txt` with `generate_minimal_requirements.py` if needed) with a one-line comment.

### 7. Test in Prowser

1. Restart Prowser.
2. Confirm **Image** lists your function and model is enabled when deps are installed.
3. Generate an image; confirm `imagegen-NNNN.png` appears and browse opens.
4. Test ⌥/ and per-function model persistence.

---

## Built-in models (summary)

### Create (`function=create`)

| Display name | Plugin id | Pipeline |
|--------------|-----------|----------|
| FLUX.1 Schnell MFLUX | `flux_schnell_mflux` | `flux_schnell_mflux_play` |
| FLUX.1-dev (LoRA preset) | `flux_sldr_nsfw_v2_lora` | `flux_schnell_mflux_play` |
| SANA Sprint 0.6B 1024px | `sana_sprint_600m` | `sana_sprint_600m` |
| Z-Image Turbo (8-bit) | `z_image_turbo_sdnq_int8` | `z_image_turbo_sdnq` |
| Realistic Vision V4.0 | `realistic_vision_v4_sd15` | `sd15_diffusers` |
| Anything Furry | `anything_furry_sd15` | `sd15_diffusers` |
| FLUX.2-klein-4B / 9B / 9b-kv | `flux_klein_*_create` | `mflux_flux2_klein_create` |
| FLUX.2 Klein 9B KV MLX (SceneWorks) | `sceneworks_klein_9b_kv_mlx_create` | `mflux_flux2_klein_create` |

### Edit / expand / infill

| Function | Plugin ids | Pipeline |
|----------|------------|----------|
| Edit | `flux_klein_*_edit`, `sceneworks_klein_9b_kv_mlx_edit` | `mflux_flux2_klein_edit` |
| Expand | `flux_fill_expand`, `flux_klein_*_expand`, `sceneworks_klein_9b_kv_mlx_expand` | `mflux_fill_expand`, `mflux_flux2_klein_expand` |
| Infill | `flux_fill_infill` | `mflux_fill_infill` |

SceneWorks plugins share Klein pipelines but use pre-quantized MLX tiers (Q4/Q8/BF16) from `SceneWorks/flux2-klein-9b-kv-mlx` instead of on-the-fly MFLUX quantization.

Use `flux_schnell_mflux.py` and `sana_sprint_600m.py` as templates for thin plugins.

---

## Settings storage

Relevant keys in `~/.prowser/data/settings.json`:

```json
{
  "imagegen": {
    "last_function": "create",
    "active_plugin_by_function": {
      "create": "flux_schnell_mflux",
      "edit": "flux_klein_4b_edit",
      "expand": "flux_fill_expand",
      "infill": "flux_fill_infill"
    },
    "dialog_geometry": "...",
    "dialogs": {
      "create": { "flux_schnell_mflux": { "steps": 4, "mflux_quantize": 3 } },
      "edit": { }
    },
    "lora_catalog": {
      "by_host": {
        "flux1_t2i": { "enabled_ids": [], "hidden_ids": [] }
      },
      "by_model": {
        "flux1_schnell": { "enabled_ids": [], "hidden_ids": [] }
      },
      "user_entries": {},
      "entry_overrides": {}
    },
    "models": {
      "flux_schnell_mflux": { "steps": 4, "mflux_quantize": 3 },
      "sana_sprint_600m": { "steps": 2, "guidance_scale": 4.5 }
    }
  }
}
```

Per-function dialog values are stored under `imagegen.dialogs.<function>.<plugin_id>`. Legacy flat `imagegen.models` keys are still read for migration. LoRA state migrates from legacy `enabled_ids` / `deleted_ids` to `by_host` / `by_model` with `hidden_ids` on load.

---

## PyInstaller / frozen app notes

- The Image menu and plugins are bundled via `imagegen_plugins` hooks (see `pyinstaller_hooks/hook-imagegen_plugins.py`).
- Generation runs in a subprocess (`--model-tasks-worker` on the frozen binary).
- MFLUX requires MLX native extensions in the build venv; diffusers pipelines require **diffusers** and **accelerate**.
- `./pyInstallerBuild.sh --min` omits the Image menu entirely.
- After adding a pipeline, rebuild with `./pyInstallerBuild.sh` and test **Tools → Debug → View log** if the worker fails.

---

## Design rules (short)

1. **No cross-app imports** — Keep generation code inside `imagegen_plugins/`.
2. **Thin plugins, fat pipelines** — Menu entry + defaults only in the plugin file.
3. **JSON payload is the contract** — UI and worker communicate through `build_worker_payload()`; include `pipeline_id` on every job.
4. **Fail soft at discovery** — Missing optional deps should disable a model, not crash Prowser.
5. **Unload after each job** — Avoid holding two large models in the worker at once.

---

## Troubleshooting

| Symptom | Things to check |
|---------|------------------|
| No Image menu | `--min` build, or `bundle_capabilities.imagegen_ui_enabled()` false |
| Model grayed out | Backend not installed, or weights not in HF cache; install packages from `requirements.txt` |
| Dialog never appears | Dependencies OK? Try ⌥/; check terminal / `~/.prowser/logs` |
| “Unknown pipeline_id” | `model_tasks_worker._run_generate` not updated for your pipeline |
| Download prompt every time | HF cache path for your `hf_model_id` |
| OOM or hang after switch | Ensure `unload_pipeline()` runs in worker `finally` block |

For worker errors, run Prowser from a terminal or open **Tools → Debug → View log** to see `[model_tasks_worker]` tracebacks.
