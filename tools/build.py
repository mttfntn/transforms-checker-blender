"""Build the installable extension zip into dist/ and validate it.

Usage:
    python tools/build.py [--blender PATH]

Copies transforms_checker/ plus the repo's LICENSE into a temporary folder (so the
license ships in the zip without keeping a second copy in git), then runs
Blender's own builder and validator:
    blender --command extension build    (writes dist/transforms_checker-<version>.zip)
    blender --command extension validate
Prints the path of the zip. Exits non-zero if either step fails.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from run import find_blender  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blender", default=None)
    args = ap.parse_args()
    blender = args.blender or find_blender()

    dist = os.path.join(ROOT, "dist")
    os.makedirs(dist, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tc_build_") as tmp:
        src = os.path.join(tmp, "transforms_checker")
        shutil.copytree(os.path.join(ROOT, "transforms_checker"), src,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy(os.path.join(ROOT, "LICENSE"), os.path.join(src, "LICENSE"))
        before = set(os.listdir(dist))
        subprocess.check_call([blender, "--factory-startup", "--command", "extension", "build",
                               "--source-dir", src, "--output-dir", dist])
    built = sorted(set(os.listdir(dist)) - before) or sorted(
        f for f in os.listdir(dist) if f.endswith(".zip"))
    zip_path = os.path.join(dist, built[-1])
    subprocess.check_call([blender, "--factory-startup", "--command", "extension", "validate",
                           zip_path])
    print(zip_path)


if __name__ == "__main__":
    main()
