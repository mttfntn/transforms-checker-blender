"""Record the add-on's observable behaviour to JSON, to diff two versions.

Run inside Blender via tests/run.py:
    python tests/run.py --addon OLD --script tests/compare_behaviour.py -- old.json
    python tests/run.py --addon NEW --script tests/compare_behaviour.py -- new.json
then compare the two files (identical output = identical behaviour on these inputs).

A seeded random scene is rebuilt for every case. Recorded: scan results and
check_object flags for 384 option combinations, and the full object state after
Apply (transforms, deltas, world matrices, mesh vertices, data sharing) for 32.
"""

import itertools
import json
import math
import os
import random
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tc_loader import load_addon, make_mesh, make_object, reset_scene  # noqa: E402

tc = load_addon()
tc.register()

R = 5  # decimals kept; float noise below this is ignored


def rnd(v):
    return [round(x, R) + 0.0 for x in v]


def build_scene(seed=1234, count=80):
    rng = random.Random(seed)
    reset_scene()
    shared = None
    objs = []

    def pick(*choices):
        return rng.choice(choices)

    for i in range(count):
        kind = pick("MESH", "MESH", "MESH", "EMPTY", "CAMERA", "LIGHT", "CURVE", "ARMATURE")
        name = f"obj_{i:03d}"
        if kind == "MESH":
            if shared is not None and rng.random() < 0.15:
                o = make_mesh(name, data=shared)
            else:
                o = make_mesh(name, verts=[(rng.uniform(-1, 1), rng.uniform(-1, 1),
                                            rng.uniform(-1, 1)) for _ in range(4)])
                if shared is None and rng.random() < 0.3:
                    shared = o.data
        elif kind == "EMPTY":
            o = make_object(name, None)
        elif kind == "CAMERA":
            o = make_object(name, bpy.data.cameras.new(name))
        elif kind == "LIGHT":
            o = make_object(name, bpy.data.lights.new(name, "POINT"))
        elif kind == "CURVE":
            cu = bpy.data.curves.new(name, "CURVE")
            sp = cu.splines.new("POLY")
            sp.points.add(2)
            for p in sp.points:
                p.co = (rng.uniform(-1, 1), rng.uniform(-1, 1), 0, 1)
            o = make_object(name, cu)
        else:
            o = make_object(name, bpy.data.armatures.new(name))

        o.rotation_mode = pick("XYZ", "ZXY", "QUATERNION", "AXIS_ANGLE")
        mag = pick(0.0, 0.0, 5e-5, 2e-3, 1.0)
        if rng.random() < 0.6:
            o.location = [rng.uniform(-mag, mag) * 3 for _ in range(3)]
        if rng.random() < 0.6:
            if o.rotation_mode == "QUATERNION":
                o.rotation_quaternion = pick((1, 0, 0, 0), (-1, 0, 0, 0),
                                             (1, mag, 0, 0), (0.7, 0.7, 0, 0))
            elif o.rotation_mode == "AXIS_ANGLE":
                o.rotation_axis_angle = (pick(0.0, mag, 2 * math.pi), 0, pick(0, 1), 1)
            else:
                o.rotation_euler = [pick(0.0, mag, 2 * math.pi, -mag) for _ in range(3)]
        if rng.random() < 0.6:
            o.scale = [1 + pick(0.0, mag, -mag / 2) for _ in range(3)]  # never 0 (singular)
            if rng.random() < 0.1:
                o.scale.x *= -1
        if rng.random() < 0.25:
            o.delta_location = (pick(0.0, mag), 0, 0)
            o.delta_rotation_euler = (0, pick(0.0, mag), 0)
            o.delta_rotation_quaternion = pick((1, 0, 0, 0), (0.9, 0, 0.1, 0))
            o.delta_scale = (1, 1, pick(1.0, 1 + mag))
        if objs and rng.random() < 0.2:
            o.parent = rng.choice(objs)
        o.select_set(rng.random() < 0.5)
        if rng.random() < 0.15:
            o.hide_set(True)
        objs.append(o)
    bpy.context.view_layer.update()
    return objs


def object_state(o):
    st = {
        "loc": rnd(o.location), "rot": rnd(o.matrix_basis.to_quaternion()),
        "scale": rnd(o.scale),
        "dloc": rnd(o.delta_location), "drot": rnd(o.delta_rotation_euler),
        "dquat": rnd(o.delta_rotation_quaternion), "dscale": rnd(o.delta_scale),
        "world": [rnd(row) for row in o.matrix_world],
        "data": o.data.name if o.data else None,
    }
    # World-space geometry: what applying must never change.
    if o.type == "MESH":
        st["verts"] = [rnd(o.matrix_world @ v.co) for v in o.data.vertices]
    elif o.type == "CURVE":
        st["verts"] = [rnd(o.matrix_world @ p.co.xyz) for sp in o.data.splines for p in sp.points]
    elif o.type == "EMPTY":
        st["size"] = round(o.empty_display_size, R)
    return st


SCAN_KEYS = ("check_location", "check_rotation", "check_scale", "include_delta",
             "selected_only", "skip_hidden")
ALL_TYPES = {t for t, _, _ in tc.OBJECT_TYPES}


def set_options(opts):
    s = bpy.context.scene.transforms_checker
    for k, v in opts.items():
        setattr(s, k, v)


def main():
    out = {"scan": [], "apply": []}

    objs = build_scene()
    names = [o.name for o in objs]
    for bools in itertools.product((False, True), repeat=len(SCAN_KEYS)):
        for tol in (0.0, 1e-4, 1e-2):
            for types in ("default", "all"):
                opts = dict(zip(SCAN_KEYS, bools), tolerance=tol)
                if types == "all":
                    opts["object_types"] = ALL_TYPES
                set_options(opts)
                bpy.ops.transforms_checker.scan()
                s = bpy.context.scene.transforms_checker
                out["scan"].append({
                    "opts": {**dict(zip(SCAN_KEYS, bools)), "tolerance": tol, "types": types},
                    "results": [it.obj.name for it in s.results],
                    "live": [o.name for o in tc.live_results(s)],
                    "flags": {n: list(tc.check_object(bpy.data.objects[n], s)) for n in names},
                })
                bpy.ops.transforms_checker.clear()
                reset_opts = bpy.context.scene.transforms_checker
                for p in reset_opts.bl_rna.properties:
                    if p.identifier not in {"rna_type", "results", "name"}:
                        reset_opts.property_unset(p.identifier)

    for bools in itertools.product((False, True), repeat=5):
        keys = ("check_location", "check_rotation", "check_scale", "include_delta",
                "isolate_users")
        objs = build_scene()
        opts = dict(zip(keys, bools), object_types=ALL_TYPES)
        set_options(opts)
        bpy.ops.transforms_checker.scan()
        before = [it.obj.name for it in bpy.context.scene.transforms_checker.results]
        try:
            ret = bpy.ops.transforms_checker.apply("EXEC_DEFAULT")
        except RuntimeError as e:  # recorded, so a version that raises is visible in the diff
            ret = ["ERROR"] + sorted({ln.split("Error: ")[-1] for ln in str(e).splitlines()
                                      if "Error: " in ln and "Python" not in ln})
        bpy.context.view_layer.update()
        out["apply"].append({
            "opts": dict(zip(keys, bools)),
            "ret": sorted(ret),
            "before": before,
            "after": [it.obj.name for it in bpy.context.scene.transforms_checker.results],
            "objects": {o.name: object_state(o) for o in objs},
        })

    path = sys.argv[sys.argv.index("--") + 1]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=0, sort_keys=True)
    print(f"wrote {path}: {len(out['scan'])} scan cases, {len(out['apply'])} apply cases")


main()
