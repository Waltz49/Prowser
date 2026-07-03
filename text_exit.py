#!/usr/bin/env python3
"""Example PROWSER_TEXT_AI_EXIT / PROWSER_IMAGE_AI_EXIT hook script."""
import argparse

p = argparse.ArgumentParser()
p.add_argument("-p", required=True)
args = p.parse_args()
print("[EXIT]" + args.p)
