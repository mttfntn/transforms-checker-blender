"""Time the add-on's hot paths on a large scene. Runs inside Blender via tests/run.py:
    python tests/run.py --addon PATH --script tests/benchmark.py

Prints the median time of: a full scan, one redraw of the panel (mock layout),
and one redraw of every list row, for 5000 objects of which half are flagged.
"""

import os
import statistics
import sys
import time
import types

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tc_loader import MockLayout, load_addon, make_mesh, reset_scene  # noqa: E402

tc = load_addon()
tc.register()
reset_scene()
me = bpy.data.meshes.new("shared")
for i in range(5000):
    o = make_mesh(f"o{i:05d}", data=me)
    if i % 2:
        o.location.x = 1
        o.scale.y = 2  # no negative scale: worst case for the panel hint
s = bpy.context.scene.transforms_checker


def median_ms(fn, n=15):
    times = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t) * 1000)
    return statistics.median(times)


def draw_panel():
    tc.TC_PT_main.draw(types.SimpleNamespace(layout=MockLayout([])), bpy.context)


def draw_rows():
    fake = types.SimpleNamespace()
    for i, item in enumerate(s.results):
        tc.TC_UL_results.draw_item(fake, bpy.context, MockLayout([]), s, item, 0, s, "active_index", i)


print(f"BENCH scan        {median_ms(lambda: tc.rescan(bpy.context)):8.2f} ms  ({len(s.results)} flagged)")
print(f"BENCH panel draw  {median_ms(draw_panel):8.2f} ms")
print(f"BENCH all rows    {median_ms(draw_rows, 5):8.2f} ms  (Blender only draws visible rows)")
