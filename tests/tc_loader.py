"""Helpers shared by the in-Blender scripts: load the add-on from TC_ADDON_PATH,
reset the scene, and a mock UILayout that validates what panels draw.
"""

import importlib.util
import os
import sys

import bpy


def load_addon():
    """Import the add-on (package folder or single .py) as module 'transforms_checker'."""
    path = os.environ["TC_ADDON_PATH"]
    if os.path.isdir(path):
        spec = importlib.util.spec_from_file_location(
            "transforms_checker", os.path.join(path, "__init__.py"),
            submodule_search_locations=[path])
    else:
        spec = importlib.util.spec_from_file_location("transforms_checker", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["transforms_checker"] = mod
    spec.loader.exec_module(mod)
    return mod


def reset_scene():
    """Remove every object and orphan data block and reset the add-on settings."""
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    for coll in (bpy.data.meshes, bpy.data.curves, bpy.data.cameras,
                 bpy.data.lights, bpy.data.armatures):
        for d in list(coll):
            coll.remove(d)
    s = bpy.context.scene.transforms_checker
    s.results.clear()
    for p in s.bl_rna.properties:
        if p.identifier not in {"rna_type", "results", "name"}:
            s.property_unset(p.identifier)


def make_mesh(name, data=None, verts=((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))):
    """Create a small mesh object linked to the scene collection."""
    if data is None:
        data = bpy.data.meshes.new(name + "_me")
        data.from_pydata([tuple(v) for v in verts], [], [(0, 1, 2), (0, 1, 3)])
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def make_object(name, data):
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


# --- Mock layout ------------------------------------------------------------

_ICONS = set(bpy.types.UILayout.bl_rna.functions["prop"].parameters["icon"].enum_items.keys())


class MockLayout:
    """Stands in for bpy.types.UILayout in background mode.

    Records every call and raises if a drawn property, operator or icon does not
    exist, which is what Blender would report as a draw error in the UI.
    """

    def __init__(self, log):
        self.log = log
        self.alignment = "EXPAND"

    def _icon(self, kw):
        icon = kw.get("icon", "NONE")
        if icon not in _ICONS:
            raise AssertionError(f"unknown icon {icon!r}")

    def _child(self, *a, **kw):
        return MockLayout(self.log)

    row = column = box = grid_flow = split = _child

    def prop(self, data, name, **kw):
        if name not in data.bl_rna.properties:
            raise AssertionError(f"unknown property {name!r} on {data}")
        self._icon(kw)
        self.log.append(("prop", name))

    def label(self, **kw):
        self._icon(kw)
        self.log.append(("label", kw.get("text", "")))

    def operator(self, idname, **kw):
        cat, op = idname.split(".")
        if not hasattr(getattr(bpy.ops, cat), op) or not getattr(getattr(bpy.ops, cat), op).get_rna_type():
            raise AssertionError(f"unknown operator {idname!r}")
        self._icon(kw)
        self.log.append(("operator", idname))

        class _Props:
            pass
        return _Props()

    def template_list(self, listtype, list_id, data, prop, active_data, active_prop, **kw):
        assert listtype in {c.__name__ for c in bpy.types.UIList.__subclasses__()}, listtype
        assert prop in data.bl_rna.properties and active_prop in active_data.bl_rna.properties
        self.log.append(("template_list", prop))
