#!/usr/bin/env python3
import argparse
import subprocess
from pathlib import Path

import torch
from diffusers import DiffusionPipeline

STEPS_MIN = 1
STEPS_MAX = 30
DEFAULT_SEED = 1316253061
DEFAULT_SIZE = 512
DEFAULT_PROMPT = "Astronaut in a jungle, cold color palette, muted colors, detailed, 8k"

parser = argparse.ArgumentParser(description="Generate Realistic Vision V4.0 images for a step/seed sweep")
parser.add_argument("-p", "--prompt", default=DEFAULT_PROMPT, help="text prompt (default: astronaut jungle scene)")
parser.add_argument(
    "--range",
    nargs=2,
    type=int,
    metavar=("MIN", "MAX"),
    default=[STEPS_MIN, STEPS_MAX],
    help=f"inference step range inclusive (default: {STEPS_MIN} {STEPS_MAX})",
)
parser.add_argument(
    "--seed",
    nargs=2,
    type=int,
    metavar=("MIN", "MAX"),
    default=[DEFAULT_SEED, DEFAULT_SEED],
    help=f"seed range inclusive (default: {DEFAULT_SEED} {DEFAULT_SEED})",
)
parser.add_argument(
    "--size",
    nargs=2,
    type=int,
    metavar=("WIDTH", "HEIGHT"),
    default=[DEFAULT_SIZE, DEFAULT_SIZE],
    help=f"image width height in pixels (default: {DEFAULT_SIZE} {DEFAULT_SIZE})",
)
args = parser.parse_args()

steps_min, steps_max = args.range
seed_min, seed_max = args.seed
width, height = args.size
if steps_min > steps_max:
    parser.error(f"--range MIN must be <= MAX (got {steps_min} {steps_max})")
if seed_min > seed_max:
    parser.error(f"--seed MIN must be <= MAX (got {seed_min} {seed_max})")
for label, dim in (("width", width), ("height", height)):
    if dim < 64 or dim % 8 != 0:
        parser.error(f"--size {label} must be >= 64 and divisible by 8 (got {dim})")

# Apple Silicon GPU (Metal); fall back to CPU if MPS is unavailable.
# float16 on MPS often decodes to all-black images for SD1.5 — use float32.
device = "mps" if torch.backends.mps.is_available() else "cpu"
dtype = torch.float32

# Local Hugging Face hub cache (already downloaded)
model_path = (
    Path.home()
    / ".cache/huggingface/hub/models--SG161222--Realistic_Vision_V4.0_noVAE"
    / "snapshots/1685907c0283c7278ba26c5fe561506f564b48d3"
)
if not model_path.is_dir():
    raise FileNotFoundError(f"Local model not found: {model_path}")

pipe = DiffusionPipeline.from_pretrained(
    str(model_path),
    torch_dtype=dtype,
    local_files_only=True,
)
pipe = pipe.to(device)

# Reduces memory pressure on Macs with < 64 GB RAM
if device == "mps":
    pipe.enable_attention_slicing()

prompt = args.prompt

for seed in range(seed_min, seed_max + 1):
    for steps in range(steps_min, steps_max + 1):
        # CPU generator (MPS RNG is flaky)
        generator = torch.Generator(device="mps").manual_seed(seed)
        image = pipe(
            prompt,
            num_inference_steps=steps,
            generator=generator,
            width=width,
            height=height,
        ).images[0]
        out_path = f"rv40_seed_{seed}_steps_{steps:02d}_{width}x{height}.png"
        image.save(out_path)
        # subprocess.run(["open", out_path], check=False)
        # print(f"Saved {out_path} (seed={seed}, steps={steps}, size={width}x{height}, device={device})")
