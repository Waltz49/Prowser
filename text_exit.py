#!/usr/bin/env python3
"""Example text/image AI exit hook script (configure in Settings → Exit Scripts)."""
import argparse

p = argparse.ArgumentParser()
p.add_argument("-p", required=True)
args = p.parse_args()
print("[EXIT]" + args.p)
