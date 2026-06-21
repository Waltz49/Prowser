# Image Create Plugins — User Guide

Prowser can generate images locally from the **Create** menu. Each entry (for example “Local FLUX.1 Schnell MFLUX Q3” or “Local SANA Sprint 0.6B 1024px”) is a **model plugin**. Plugins are optional: if nothing is installed, the Create menu does not appear.

This guide explains how the system works and how to add a new model without touching unrelated parts of the app.

---

## Using Create in Prowser

1. Open Prowser with at least one plugin’s dependencies installed (see [Dependencies](#dependencies) below).
2. Use the menu bar: **Create → [model name]**.
   - Clicking a model selects it **and** opens the generation dialog for that model.
   - You can click the same model again to reopen the dialog.
3. Or press **⌥/** (Option + slash) to open the dialog for the **currently active** model (the one with the checkmark).
4. Fill in the prompt and settings, then click **Generate**.
5. When generation finishes, the new image opens in browse view (usually fullscreen). Files are named `imagegen-0001.png`, `imagegen-0002.png`, and so on, in your image creation folder (by default `~/Downloads`, or a custom folder from settings).
6. While a job runs, use **Create → Cancel Generation / Caption** or the status-bar indicator to cancel.

Settings for each model (sliders, seed, etc.) are saved per model in `~/.prowser/data/settings.json` under `imagegen.models.<plugin_id>`.

---

## Architecture in plain terms

The design splits **what the user sees** (plugin) from **how images are actually generated** (pipeline).

| Layer | Role | Typical files |
|--------|------|----------------|
| **Plugin** | One Create menu item: display name, default parameters, Hugging Face model id | `imagegen_plugins/my_model.py` |
| **Pipeline** | Shared backend: UI field rules, worker script, availability check | `image_gen_pipeline_modes.py`, `imagegen_plugins/pipelines/my_backend.py` |
| **Worker** | Runs in a background process so the UI stays responsive | `model_tasks_worker.py` dispatches by `pipeline_id` |

```text
  Create menu                    Main window (Qt)
       │                              │
       ▼                              ▼
  discover_plugins()          ImageGenDialog (built from FieldSpecs)
       │                              │
       ▼                              ▼
  ImageGenModelPlugin  ──────►  ImageGenController
       │                              │
       │ build_payload()              │ start_generate_job()
       ▼                              ▼
  JSON payload  ──────────────►  model_tasks_worker (subprocess)
                                        │
                                        ▼
                                 pipelines/*.py → run_from_payload()
```

**Isolation:** Model-specific code (loading weights, calling diffusers or MFLUX, etc.) should live only under `imagegen_plugins/pipelines/`. The rest of Prowser talks to plugins through the small `ImageGenModelPlugin` API and JSON payloads. Do not import testchat or other apps into the browser.

**One worker:** Image generation and LM Studio captions share a single background worker process. Only one job runs at a time. After each generate job, the worker unloads the image model to free memory.

---

## Directory layout

```text
imagegen_plugins/
  __init__.py                 # discover_plugins() — register menu entries here
  image_gen_registry.py       # ImageGenModelPlugin class
  image_gen_pipeline_modes.py # PipelineMode table, dialog fields, payload builder
  image_gen_menu.py           # Create menu, ⌥/ shortcut
  image_gen_dialog.py         # Dynamic settings UI
  image_gen_controller.py     # Start/cancel jobs, open result in browse
  image_gen_persistence.py    # Save/load per-model settings
  image_gen_model_availability.py  # “Download model?” before first run
  image_gen_install_hint.py   # Message when backend package is missing
  flux_schnell_mflux.py       # Example plugin (thin)
  sana_sprint_600m.py         # Example plugin (thin)
  pipelines/
    mflux_schnell.py          # FLUX via MFLUX/MLX
    sana_sprint.py              # SANA via diffusers
```

At the app root:

- `model_tasks_worker.py` — routes `payload["pipeline_id"]` to the right `run_from_payload()`.
- `model_tasks_controller.py` — Qt wrapper around the worker process.

---

## Plugins vs pipelines

- **`plugin_id`** — Unique id for settings and the menu (e.g. `sana_sprint_600m`). One plugin row in Create.
- **`pipeline_id`** — Which backend implementation to run (e.g. `sana_sprint_600m`). Several plugins could share one pipeline with different defaults; today each plugin has its own pipeline id.

A **plugin file** is usually short: it constructs one `ImageGenModelPlugin` with:

- `display_name` — Menu label (may include placeholders like `Q3` for MFLUX quant).
- `hf_model_id` — Hugging Face repo id or MFLUX alias (e.g. `schnell`).
- `model_defaults` — Default width, height, steps, guidance, and any extra keys your pipeline expects.

A **pipeline** defines:

- Sliders and checkboxes in the dialog (`field_specs_for_pipeline`).
- Min/max for steps, guidance, dimensions.
- The worker script filename under `pipelines/`.
- How to test if the backend is installed (`pipeline_is_available`).

---

## Dialog fields

Fields are declared with `FieldSpec` in `image_gen_fields.py`. Supported kinds:

| Kind | UI control |
|------|------------|
| `text` | Multi-line text (prompt, negative prompt) |
| `int_slider` | Slider + spin box |
| `float_slider` | Slider + label |
| `bool` | Checkbox |
| `choice` | Dropdown |
| `seed` | Integer seed |

Common fields (prompt, width, height, steps, guidance, seed, random seed) are added automatically from `PipelineMode`. Pipeline-specific fields (e.g. MFLUX quantization, SANA `clean_caption`) are added in `field_specs_for_pipeline()` with `if pipeline_id == "..."` blocks.

---

## FLUX LoRA adapters

FLUX Create, Expand, and Infill dialogs include a **LoRA** dropdown when using MFLUX pipelines. Which adapters appear is controlled in **Settings → LoRA** (not on the Directories tab).

| Piece | Role |
|-------|------|
| `imagegen_plugins/flux_lora_catalog.py` | Static catalog (~30 curated HF repos): repo id, filename, base model, pipeline compatibility, MFLUX verified flag |
| `settings.json` → `imagegen.lora_catalog.enabled_ids` | User-enabled LoRA ids from the Settings tab |
| `imagegen_plugins/mflux_lora_presets.py` | Download weights on first use, key-layout check, payload wiring |

**Behavior:**

- Enable LoRAs in **Settings → LoRA**. Checked entries (plus any already downloaded to `~/.cache/image_browser/mflux_loras/`) appear in the dialog dropdown when compatible with that pipeline and base model.
- Trash an entry to hide it from the list and from Create dropdowns. Hidden ids are stored in `imagegen.lora_catalog.deleted_ids` in `~/.prowser/data/settings.json`. Remove an id from that array to show the LoRA again after a catalog refresh.
- Weights download from Hugging Face on first generate (same as before for built-in presets).
- Many [HF FLUX.1-dev adapters](https://huggingface.co/models?other=base_model:adapter:black-forest-labs/FLUX.1-dev) use ComfyUI/XLabs key layouts and **crash MFLUX**; only entries marked **MFLUX verified** in the catalog are known good. Untested entries are listed in Settings but need a successful local run before they are trusted.
- Dev-trained LoRAs selected from the Schnell plugin switch the run to the **dev** base model (existing MFLUX behavior).
- Klein Edit does not expose LoRA (different architecture).

To add catalog entries at dev time, inspect repos with `scripts/build_flux_lora_catalog_snippet.py` and edit `flux_lora_catalog.py` (never scrape HF at runtime).

---

## Worker contract

Each pipeline module should implement:

1. **`run_from_payload(payload: dict) -> dict`**  
   Required keys in `payload` include at least:
   - `prompt` (non-empty string)
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
   Release GPU/MPS memory when the worker finishes a job (see `sana_sprint.py`).

For progressive preview (MFLUX stepwise PNGs), the worker may print JSON lines to stdout with `"type": "progress"` and `"path"`. The UI refreshes browse view when it sees those.

`model_tasks_worker.py` must include a branch for your `pipeline_id` that imports and calls your `run_from_payload`. Without that branch, generation will fail with “Unknown imagegen pipeline_id”.

---

## Dependencies

Install from the Prowser project directory with your venv activated:

```bash
pip install -r minimal_requirements.txt
```

| Backend | Packages | Used by |
|---------|----------|---------|
| MFLUX / MLX | `mflux` (and MLX stack it pulls in) | FLUX Schnell plugin |
| diffusers | `diffusers`, `accelerate`, `torch` | SANA Sprint plugin |

If a backend is missing, that model appears in Create but is **disabled**, with a tooltip pointing at `minimal_requirements.txt`.

**First-time model weights:** On first generate, Prowser may ask to download several gigabytes from Hugging Face. Weights are cached in the standard Hugging Face hub cache. For gated models, set `HF_TOKEN` or run `hf auth login`.

---

## How to add a new model (checklist)

Follow these steps when adding a new local generator. Adapt names to your model.

### 1. Implement the pipeline worker

Create `imagegen_plugins/pipelines/your_backend.py`:

- Implement `run_from_payload(payload)`.
- Keep all imports of heavy libraries (diffusers, mflux, torch) inside functions so the main app can start without them.
- Align width/height to what your model expects (see `align_mflux_dims` / `align_sana_sprint_dims` in existing files).
- Write the final image to `payload["output_path"]`.

Test standalone (optional):

```bash
echo '{"prompt":"test","width":1024,"height":1024,"steps":4,"guidance_scale":3.5,"output_path":"/tmp/out.png","hf_model_id":"...","pipeline_id":"your_pipeline_id","random_seed":true}' | python -m imagegen_plugins.pipelines.your_backend
```

(Or run the module’s `main()` if it reads JSON from stdin.)

### 2. Register the pipeline mode

In `imagegen_plugins/image_gen_pipeline_modes.py`:

1. Add a `PipelineMode(...)` entry to `PIPELINE_MODES` with `pipeline_id`, `worker_script`, step/guidance/size limits, and flags like `supports_negative_prompt` / `supports_progressive_images`.
2. Extend `pipeline_is_available()` to call your install check.
3. Extend `field_specs_for_pipeline()` for any extra dialog fields not covered by the shared block.
4. If needed, adjust `merge_defaults()` base keys for your pipeline.

### 3. Add the plugin entry

Create `imagegen_plugins/your_model.py`:

```python
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin

YOUR_MODEL_PLUGIN = ImageGenModelPlugin(
    plugin_id="your_model",
    pipeline_id="your_pipeline_id",
    display_name="Local My Model",
    hf_model_id="org/repo-on-huggingface",
    model_defaults={
        "prompt": "",
        "width": 1024,
        "height": 1024,
        "steps": 20,
        "guidance_scale": 7.5,
        "seed": 0,
        "random_seed": True,
    },
)
```

Register it in `imagegen_plugins/__init__.py` inside `discover_plugins()` (wrap the import in `try/except ImportError` like existing plugins).

### 4. Wire the worker router

In `model_tasks_worker.py`, inside `_run_generate()`, add:

```python
elif pipeline_id == "your_pipeline_id":
    from imagegen_plugins.pipelines.your_backend import run_from_payload
```

If your backend needs cleanup after each job, hook it in `_unload_image_model()`.

For PyInstaller bundles, also add a branch in `imagegen_plugins/image_gen_worker_entry.py` if you use the `--imagegen-worker` entry point.

### 5. User-facing messages

- **`image_gen_install_hint.py`** — Short message if `pipeline_is_available()` is false (which package to `pip install`).
- **`image_gen_model_availability.py`** — If weights are not cached, implement or reuse `_hf_repo_snapshot_has_weights()` so the user gets a download confirmation before the first run.

### 6. Dependencies

Add any new Python packages to `minimal_requirements.txt` with a one-line comment describing which plugin needs them.

### 7. Test in Prowser

1. Restart Prowser.
2. Confirm **Create** lists your model and it is enabled when deps are installed.
3. Click the model — dialog should open with all parameters.
4. Generate an image; confirm `imagegen-NNNN.png` appears and browse opens.
5. Switch to another model and back; confirm ⌥/ and menu still open the dialog (including after a successful generation).
6. Toggle **Random seed** off and regenerate — last seed should persist in settings.

---

## Built-in examples

| Menu name | Plugin file | Pipeline | Backend |
|-----------|-------------|----------|---------|
| Local FLUX.1 Schnell MFLUX Q3 | `flux_schnell_mflux.py` | `flux_schnell_mflux_play` | `pipelines/mflux_schnell.py` |
| Local SANA Sprint 0.6B 1024px | `sana_sprint_600m.py` | `sana_sprint_600m` | `pipelines/sana_sprint.py` |

Use these as templates: copy the pipeline file structure and plugin registration pattern, then replace generation logic and defaults.

---

## Settings storage

Relevant keys in `~/.prowser/data/settings.json`:

```json
{
  "imagegen": {
    "active_plugin_id": "flux_schnell_mflux",
    "dialog_geometry": "...",
    "models": {
      "flux_schnell_mflux": { "steps": 4, "mflux_quantize": 3, ... },
      "sana_sprint_600m": { "steps": 2, "guidance_scale": 4.5, ... }
    }
  }
}
```

Do not duplicate “active image” or browse state here; plugins only own generation parameters.

---

## PyInstaller / frozen app notes

- The Create menu and plugins are bundled via `imagegen_plugins` hooks (see `pyinstaller_hooks/hook-imagegen_plugins.py`).
- Generation runs in a subprocess (`--model-tasks-worker` on the frozen binary).
- MFLUX requires MLX native extensions in the build venv; SANA requires **diffusers** and **accelerate** (listed in `minimal_requirements.txt` and `requirements.txt`).
- `pyInstallerBuild.sh` bundles them via `pyinstaller_hooks/hook-diffusers.py`, `hook-accelerate.py`, and mandatory hidden imports / `--collect-submodules`.
- After adding a pipeline, rebuild with `./pyInstallerBuild.sh` and test Tools → Debug → View log if the worker fails to start.

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
| No Create menu | `discover_plugins()` returns empty — import error in `__init__.py` |
| Model grayed out | Backend not installed; install packages from `minimal_requirements.txt` |
| Dialog never appears | Dependencies OK? Try ⌥/; check for errors in terminal / `~/.prowser/logs` |
| “Unknown pipeline_id” | `model_tasks_worker._run_generate` not updated for your pipeline |
| Download prompt every time | `pipeline_model_is_local()` / HF cache path for your `hf_model_id` |
| OOM or hang after switch | Ensure `unload_pipeline()` (or equivalent) runs in worker `finally` block |

For worker errors, run Prowser from a terminal or open **Tools → Debug → View log** to see `[model_tasks_worker]` tracebacks.
