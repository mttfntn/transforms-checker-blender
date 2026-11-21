"""Launch Blender headless in an isolated scratch profile and run a script in it.

Usage:
    python tests/run.py [--blender PATH] [--addon PATH] [--script FILE] [-- extra args]

--addon   add-on to load: the package folder (default: ./transforms_checker) or a
          single-file legacy add-on (.py). The script reads it from TC_ADDON_PATH.
--script  script to run inside Blender (default: tests/test_transforms_checker.py).

Blender is started with --factory-startup and every BLENDER_USER_* path points at a
temporary folder, so the user's real preferences, add-ons and open sessions are
never read or modified. The exit code is Blender's (non-zero if the script fails).
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def find_blender():
    """Return a Blender executable from $BLENDER, PATH or the default Windows install."""
    candidates = [
        os.environ.get("BLENDER"),
        shutil.which("blender"),
        r"C:\Program Files\Blender Foundation\Blender 5.3\blender.exe",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    sys.exit("Blender not found: pass --blender or set $BLENDER")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blender", default=None)
    ap.add_argument("--addon", default=os.path.join(ROOT, "transforms_checker"))
    ap.add_argument("--script", default=os.path.join(HERE, "test_transforms_checker.py"))
    args, extra = ap.parse_known_args()
    if extra and extra[0] == "--":
        extra = extra[1:]

    blender = args.blender or find_blender()
    profile = tempfile.mkdtemp(prefix="tc_blender_profile_")
    env = dict(os.environ)
    env["TC_ADDON_PATH"] = os.path.abspath(args.addon)
    env["BLENDER_USER_RESOURCES"] = profile
    for sub in ("CONFIG", "SCRIPTS", "DATAFILES", "EXTENSIONS"):
        env[f"BLENDER_USER_{sub}"] = os.path.join(profile, sub.lower())

    cmd = [blender, "-b", "--factory-startup", "--python-exit-code", "1",
           "--python", os.path.abspath(args.script), "--", *extra]
    try:
        return subprocess.call(cmd, env=env)
    finally:
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
