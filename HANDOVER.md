# Handover: Transforms Checker

## What it is

A Blender **extension** (add-on) that scans the scene for objects whose location,
rotation or scale is not applied, shows them in a list in the 3D Viewport sidebar
(**N › Transforms**), and can select them or apply their transforms. It is a
single Python module with no dependencies outside Blender.

It is an original project, not a fork, so there is no upstream to merge from.

## What you need

- **Blender 5.3** (the only supported version). On Windows the scripts find
  `C:\Program Files\Blender Foundation\Blender 5.3\blender.exe` automatically;
  elsewhere put `blender` on `PATH`, set `$BLENDER`, or pass `--blender PATH`.
- **Python 3** on the host to run the helper scripts (they only launch Blender).
- `git` and, for releases, push access to
  `https://github.com/mttfntn/transforms-checker-blender` (public).

## How the code is organized

| Path | What it is |
|---|---|
| `transforms_checker/__init__.py` | The whole add-on: check logic, operators, UI, register/unregister. |
| `transforms_checker/blender_manifest.toml` | Extension manifest: id, version, **supported Blender range**, license. |
| `LICENSE` | GPL-3.0-or-later text. Copied into the zip at build time (not duplicated in git). |
| `tests/run.py` | Launches Blender headless in a **throwaway profile** and runs a script in it. |
| `tests/tc_loader.py` | Shared test helpers: load the add-on from a path, reset the scene, mock `UILayout`. |
| `tests/test_transforms_checker.py` | Unit tests (37). Default script of `tests/run.py`. |
| `tests/compare_behaviour.py` | Records behaviour on a seeded random scene to JSON, to diff two versions. |
| `tests/benchmark.py` | Times scan / panel draw / row draw on 5000 objects. |
| `tools/build.py` | Builds and validates `dist/transforms_checker-<version>.zip`. |
| `.github/workflows/ci.yml` | CI: tests + build on push/PR; release on `vX.Y.Z` tags. |
| `README.md` | User-facing docs. |
| `HANDOVER.md`, `AGENTS.md` | This file and its compact twin for AI assistants. Not shipped in the zip. |

## How the main feature works

Everything is in `transforms_checker/__init__.py`, top to bottom:

1. **Check**: `check_object(obj, settings)` returns `(loc, rot, scale, negative)`.
   - Location: any component (plus `delta_location` if *Delta Transforms* is on) farther than *Tolerance* from 0.
   - Rotation: the rotation is turned into a quaternion whatever the rotation mode
     (`_rotation_quaternion`), composed with the delta rotation, and flagged when
     `1 - |w| > tolerance²`. Using `|w|` makes `q` and `-q` (the same rotation) equal,
     and 360° Euler turns count as applied.
   - Scale: any component (plus `delta_scale`) farther than *Tolerance* from 1.
     `negative` is reported separately; it only flags the object when *Scale* is checked.
2. **Scan**: `rescan()` takes `candidate_objects()` (scene or selection, filtered by
   type and visibility), keeps the flagged ones and stores pointers to them, sorted by
   name, in `Scene.transforms_checker.results`. All options have an update callback
   that re-scans once a scan has run.
3. **Show**: `TC_PT_main.draw` and `TC_UL_results.draw_item` call `check_object()`
   again while drawing, so the list always shows the current state. `live_results()`
   is the list minus deleted and already-fixed objects.
4. **Apply**: `TC_OT_apply` skips linked/overridden objects and (unless *Make Single
   User*) objects with shared data, then calls `apply_transforms()`:
   - With *Delta Transforms*, deltas are folded into the normal transforms first
     (`transform_apply` ignores them), keeping the object in place.
   - All objects go to `bpy.ops.object.transform_apply` in **one call**, through
     `context.temp_override` so the user's selection is not used or changed.
   - Blender **aborts the whole call** if it refuses one object. If that happens, the
     objects are retried **one at a time, parents first**, and refused objects get their
     original transforms and deltas back.
   - Afterwards it re-scans and reports applied / skipped / refused / unchanged counts.

## How to make a change

1. Edit `transforms_checker/__init__.py`.
2. Add or update a test in `tests/test_transforms_checker.py`.
3. Run `python tests/run.py`. All tests must pass.
4. If the change should not alter behaviour, compare against the last commit (below).
5. To try it in your own Blender: `python tools/build.py`, then install the zip
   (Preferences › Get Extensions › ⌄ › Install from Disk).
6. Commit in small steps with clear messages, push to `main`, and check the Actions run.

Rules for this codebase:

- Don't add docstrings to operator / panel / UIList classes: Blender shows class
  docstrings as tooltips. Use `#` comments; tooltips come from `bl_description`.
- Every new Blender class must go in `classes` or it won't be registered.
- Property names drawn with `layout.prop(settings, "name")` are only referenced by
  string, so a search for usages misses them. Don't delete one as "unused" without checking the panel.

## How to run the tests

```
python tests/run.py                          # unit tests on transforms_checker/
python tests/run.py --addon path/to/other    # same tests on another copy (folder or .py)
python tests/run.py --script tests/benchmark.py
```

`tests/run.py` starts Blender with `-b --factory-startup` and points every
`BLENDER_USER_*` folder at a temporary directory. It never touches your
preferences, installed add-ons or a running Blender.

### Comparing behaviour with the previous version

```
mkdir -p /tmp/old/transforms_checker
git show HEAD:transforms_checker/__init__.py > /tmp/old/transforms_checker/__init__.py
python tests/run.py --addon /tmp/old/transforms_checker --script tests/compare_behaviour.py -- old.json
python tests/run.py --script tests/compare_behaviour.py -- new.json
```

Identical files mean identical behaviour on 384 scan and 32 apply option
combinations. The output is deterministic (two runs of the same code are byte-identical).

## How to make a release

1. Bump `version` in `transforms_checker/blender_manifest.toml` (e.g. `1.0.1`).
2. Nothing to change in `README.md`: its release, license and language badges read GitHub, and the Blender badge reads the manifest.
3. Run the tests, commit, push to `main`, and wait for CI to pass.
4. Create an **annotated** tag; its message becomes the release notes:
   ```
   git tag -a v1.0.1 -m "Short title

   - change one
   - change two"
   git push origin v1.0.1
   ```
5. CI runs the tests, builds the zip, checks the tag matches the manifest version, and
   publishes the GitHub release with the zip attached.

To support a new Blender version (e.g. 5.4): change `blender_version_max` in the
manifest, `BLENDER_VERSION` / `BLENDER_SERIES` / `BLENDER_SHA256` in `ci.yml`
(the hash is in `blender-<version>.sha256` on download.blender.org), the Windows
default path in `tests/run.py`, and the Blender badge; then run the tests on it.

## Things to know

- **Blender refuses some applies**: location/rotation on text objects and 2D curves
  raise an error, and so does *Make Single User* when shared data is mixed with
  other objects in one call. In the first (unreleased) version this made the whole
  Apply fail with a Python error; it is now handled by the one-at-a-time retry.
- Blender silently does nothing for cameras, lights and volumes; the add-on
  reports them as "unchanged by Blender".
- `matrix_world` is stale until `view_layer.update()`; tests that compare world
  positions must update first (`world_verts()` in the tests does).
- `UIList.bitflag_filter_item` only exists on instances; tests pass `1 << 30`.
- In background mode, operator reports are printed to stdout (`Info:` / `Warning:` lines).
- The extension module is imported as `bl_ext.<repo>.transforms_checker`, not
  `transforms_checker`; the code never imports itself by name.

## Known limits

- Applying a parent with non-uniform scale or rotation gives its children
  compensating transforms (Blender behaviour), so they can be flagged afterwards.
- The list doesn't notice new objects until the next scan or option change.
- Each panel redraw re-checks every listed object: about 9 ms for 2500 flagged
  objects (measured with `tests/benchmark.py`).
- Rotation tolerance is on `1 - |w|`, so the smallest flagged angle is about
  `2.8 × tolerance` radians, not `tolerance`.
- CI covers Linux only; the code has no platform-specific parts.
- CI uploads no workflow artifacts on purpose: the GitHub account's artifact storage
  quota is shared with other repos and was full on the first run. The release is
  published from the same job that tested and built the zip.
- `download.blender.org` refuses GitHub's machines; CI falls back to official
  mirrors and verifies the pinned SHA-256, so any mirror is safe.
