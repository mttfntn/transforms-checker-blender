# Transforms Checker

![Blender 5.3](https://img.shields.io/badge/Blender-5.3-E87D0D?logo=blender&logoColor=white)
![Release](https://img.shields.io/badge/release-v1.0.0-blue)
[![Tests](https://github.com/mttfntn/transforms-checker-blender/actions/workflows/ci.yml/badge.svg)](https://github.com/mttfntn/transforms-checker-blender/actions/workflows/ci.yml)
![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-green)
![Python](https://img.shields.io/badge/language-Python-3776AB?logo=python&logoColor=white)

A Blender extension that finds objects whose **location, rotation or scale has
not been applied**, lists them, and can select them or apply their transforms.

Supports **Blender 5.3** only.

## Install

1. Download `transforms_checker-<version>.zip` from the
   [latest release](https://github.com/mttfntn/transforms-checker-blender/releases/latest).
2. In Blender: **Edit › Preferences › Get Extensions**, then the **⌄** menu (top right)
   › **Install from Disk…**, and pick the zip.

If you used the old single-file version (`transforms_checker.py` in
`scripts/addons`), disable and remove it first in **Preferences › Add-ons**.

## Use

Open the 3D Viewport sidebar (**N**) › **Transforms** tab.

| Control | What it does |
|---|---|
| **Location / Rotation / Scale** | Which transforms to check (and to apply). |
| **Check Transforms** | Scans the scene and lists the flagged objects. |
| List rows | `L` `R` `S` = unapplied location / rotation / scale; ⚠ = negative scale. Click a name to select it. |
| **Select Flagged** | Selects every flagged object. |
| **Apply Transforms** | Applies the checked transforms to all flagged objects (asks first; undoable). |
| **Options** | Selected Only, Skip Hidden, Delta Transforms, Make Single User, Tolerance, Object Types. |

Changing an option re-scans automatically after the first scan.

### Things Apply leaves alone (and reports)

- **Text objects and 2D curves**: Blender can only apply their scale.
- **Cameras, lights, volumes**: Blender doesn't apply transforms to them.
- **Objects sharing data** with other objects: skipped unless **Make Single User** is on.
- **Linked / library-override objects**: can't be edited.
- **Children** of an applied parent may get a new compensating transform (so they
  don't move) and show up flagged; press **Apply Transforms** again for them.

## For developers

- [HANDOVER.md](HANDOVER.md): how the project is organized, tested and released.
- [AGENTS.md](AGENTS.md): the same, compact, for AI coding assistants.

Run the tests (needs Blender 5.3; uses a throwaway profile):

```
python tests/run.py
```

## License

[GPL-3.0-or-later](LICENSE). © 2026 Matteo Fontana.
