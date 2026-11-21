# AGENTS.md: Transforms Checker

Blender 5.3 extension: flags objects with unapplied location/rotation/scale; lists,
selects and applies them. One module, no dependencies. Not a fork. Human docs: HANDOVER.md.

## Commands

```
python tests/run.py                                   # unit tests (37), must all pass
python tests/run.py --addon PATH                      # tests on another copy (pkg dir or .py)
python tests/run.py --script tests/compare_behaviour.py -- out.json   # behaviour snapshot
python tests/run.py --script tests/benchmark.py       # timings on 5000 objects
python tools/build.py                                 # dist/transforms_checker-<ver>.zip + validate
```
Blender lookup: `--blender`, `$BLENDER`, `PATH`, then `C:\Program Files\Blender Foundation\Blender 5.3\blender.exe`.
`tests/run.py` = `blender -b --factory-startup` + temp `BLENDER_USER_*` dirs. Never test in the user's running Blender or profile.

## Architecture (transforms_checker/__init__.py)

- `check_object(obj, settings) -> (loc, rot, scale, negative)`: core check. Rotation is a quaternion via `_rotation_quaternion`, with the delta composed in, flagged if `1-|w| > tol²`.
- `candidate_objects` → `rescan` (fills `Scene.transforms_checker.results`, PointerProperty rows, sorted by name) → `live_results` (still existing and still flagged).
- `apply_transforms(context, objs, settings) -> {name: reason}`: fold deltas, one `object.transform_apply` call through `temp_override`; on RuntimeError, retry per object sorted by parent depth; restore refused objects' raw values.
- Operators: `transforms_checker.scan / select / select_one / apply / clear`. UI: `TC_PT_main` (VIEW_3D › UI › "Transforms"), `TC_UL_results`.
- Settings: `TC_Settings` PropertyGroup on Scene; every option's `update=_settings_changed` re-scans if `scanned`.
- Manifest `transforms_checker/blender_manifest.toml`: `blender_version_min = "5.3.0"`, `blender_version_max = "5.4.0"`.

## Rules and pitfalls

- No docstrings on Operator/Panel/UIList classes (they become tooltips); use `#` comments.
- New bpy classes must be added to `classes`.
- Properties are referenced by string in `layout.prop(...)`: a usage search misses them.
- `transform_apply` aborts the WHOLE call if it refuses one object: text and 2D curves (loc/rot), and `isolate_users=True` with shared data mixed with other objects. Keep the per-object fallback.
- Cameras, lights and volumes: `transform_apply` silently no-ops. Report them, don't count them as applied.
- `matrix_world` is stale until `bpy.context.view_layer.update()`.
- `UIList.bitflag_filter_item` exists only on instances.
- Restore transforms from raw property values, not via `matrix_basis` (Euler angles would change).
- Extension module name is `bl_ext.<repo>.transforms_checker`: never import self by name.
- LICENSE lives at the repo root only; `tools/build.py` copies it into the zip.

## Verification used for v1.0.0

- Baseline: 33 tests on the original single file. 4 regression tests added for the Apply bugs: they fail (raise) on the original and pass now.
- `compare_behaviour.py` old vs new: 384/384 scan cases identical; 6/6 apply cases that worked before are identical; the 26 that differ are exactly those where the original raised. In them, world-space geometry moved 0 times, and every object still flagged is explained (camera/light no-op, 2D curve refused, shared data skipped, or a child given a compensating transform; the original shows the same child effect).
- Benchmark: panel draw 18.5 → 9.4 ms (one check per object per redraw instead of two); scan unchanged.
- Built zip installed in a scratch profile and smoke-tested.

## Release checklist

1. Bump `version` in the manifest; update the static release badge in README.md (repo is private).
2. `python tests/run.py` passes; commit; push `main`; CI green.
3. `git tag -a vX.Y.Z -m "notes"` (annotated; the message becomes the release notes); `git push origin vX.Y.Z`.
4. CI (same job): test → build → fetch tag → check tag == manifest version → `gh release create` with the zip.

## Git

- Remote `origin` = https://github.com/mttfntn/transforms-checker-blender (private), branch `main`.
- Workflow `.github/workflows/ci.yml`: one job; Blender 5.3.0 linux tarball, sha256-pinned, 4 official mirrors with retries (download.blender.org refuses CI; the Berkeley mirror served it), cached. No artifacts uploaded: the account artifact quota is shared and was full. Release steps run in the same job for tags.
- Small commits; end messages with the Co-Authored-By trailer if an AI wrote them.
