# SPDX-License-Identifier: GPL-3.0-or-later
"""Transforms Checker: find and apply unapplied object transforms in Blender.

Adds a "Transforms" tab to the 3D Viewport sidebar (N panel). The flow is:

1. Scan: ``rescan()`` walks the scene (``candidate_objects()``), runs
   ``check_object()`` on each object and stores the flagged ones in the scene's
   ``TC_Settings.results`` collection.
2. Display: the panel and list re-run ``check_object()`` while drawing, so rows
   always show the current state, and objects fixed since the scan drop out
   (``live_results()``).
3. Act: operators select the flagged objects, or apply their transforms
   through Blender's own ``object.transform_apply`` (``apply_transforms()``).

Settings live on the scene (``Scene.transforms_checker``), so they are saved with
the .blend file. Changing an option re-scans automatically once a scan has run.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup, UIList
from mathutils import Quaternion


# Object types offered in the "Object Types" filter (identifiers are Object.type values).
OBJECT_TYPES = [
    ("MESH", "Mesh", ""),
    ("CURVE", "Curve", ""),
    ("SURFACE", "Surface", ""),
    ("META", "Metaball", ""),
    ("FONT", "Text", ""),
    ("CURVES", "Hair Curves", ""),
    ("POINTCLOUD", "Point Cloud", ""),
    ("VOLUME", "Volume", ""),
    ("GREASEPENCIL", "Grease Pencil", ""),
    ("ARMATURE", "Armature", ""),
    ("LATTICE", "Lattice", ""),
    ("EMPTY", "Empty", ""),
    ("CAMERA", "Camera", ""),
    ("LIGHT", "Light", ""),
    ("LIGHT_PROBE", "Light Probe", ""),
    ("SPEAKER", "Speaker", ""),
]

# Checked by default: types whose geometry is affected by applying transforms.
# Empties, cameras, lights, probes and speakers are usually placed on purpose.
DEFAULT_TYPES = {
    "MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES",
    "POINTCLOUD", "VOLUME", "GREASEPENCIL", "ARMATURE", "LATTICE",
}


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

def _rotation_quaternion(obj):
    """Return the object's local rotation as a quaternion, whatever its rotation mode."""
    if obj.rotation_mode == "QUATERNION":
        return obj.rotation_quaternion.normalized()
    if obj.rotation_mode == "AXIS_ANGLE":
        angle, x, y, z = obj.rotation_axis_angle
        # A zero axis means no rotation (Quaternion() would fail to normalize it).
        return Quaternion((x, y, z), angle) if (x or y or z) else Quaternion()
    return obj.rotation_euler.to_quaternion()


def check_object(obj, settings):
    """Report which transforms of ``obj`` are not applied.

    Returns ``(loc, rot, scale, negative)``. The first three are False when the
    matching check is disabled in ``settings``. ``negative`` is True when any
    scale axis is negative, whatever the settings. With ``include_delta`` the
    delta transforms count too: deltas add to location, multiply scale and
    compose with rotation (so a delta that cancels the rotation is not flagged).
    Values within ``settings.tolerance`` of identity count as applied.
    """
    tol = settings.tolerance

    loc_vals = list(obj.location)
    scale_vals = list(obj.scale)
    rot_quat = _rotation_quaternion(obj)

    if settings.include_delta:
        loc_vals += list(obj.delta_location)
        scale_vals += list(obj.delta_scale)
        # Blender uses the delta quaternion only in QUATERNION mode, else the delta euler.
        delta_q = (obj.delta_rotation_quaternion.normalized()
                   if obj.rotation_mode == "QUATERNION"
                   else obj.delta_rotation_euler.to_quaternion())
        rot_quat = delta_q @ rot_quat

    loc = settings.check_location and any(abs(v) > tol for v in loc_vals)
    # q and -q are the same rotation, so compare |w| with 1. For a rotation of angle
    # a, 1 - |w| is about a^2 / 8, so tol^2 flags rotations above about 2.8 * tol rad.
    rot = settings.check_rotation and (1.0 - abs(rot_quat.w)) > tol * tol
    scale = settings.check_scale and any(abs(v - 1.0) > tol for v in scale_vals)
    negative = any(v < 0.0 for v in scale_vals)
    return loc, rot, scale, negative


def _flagged(flags, settings):
    """Whether the result of ``check_object()`` means the object belongs in the list."""
    loc, rot, scale, negative = flags
    return loc or rot or scale or (negative and settings.check_scale)


def is_flagged(obj, settings):
    """True if ``obj`` has an unapplied transform the settings ask about."""
    return _flagged(check_object(obj, settings), settings)


def candidate_objects(context, settings):
    """Yield the objects a scan should look at: scene or selection, filtered by type/visibility."""
    objs = context.selected_objects if settings.selected_only else context.scene.objects
    for obj in objs:
        if obj.type not in settings.object_types:
            continue
        if settings.skip_hidden and not obj.visible_get():
            continue
        yield obj


def rescan(context):
    """Rebuild the scene's result list (sorted by name) and return how many objects are flagged."""
    settings = context.scene.transforms_checker
    settings.results.clear()
    for obj in sorted(candidate_objects(context, settings), key=lambda o: o.name):
        if is_flagged(obj, settings):
            item = settings.results.add()
            item.obj = obj
    settings.scanned = True
    settings.active_index = min(settings.active_index, max(len(settings.results) - 1, 0))
    return len(settings.results)


def live_results(settings):
    """Objects from the last scan that still exist and are still flagged now."""
    return [it.obj for it in settings.results
            if it.obj is not None and is_flagged(it.obj, settings)]


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------

_DELTA_DEFAULTS = (
    ("delta_location", (0.0, 0.0, 0.0)),
    ("delta_rotation_euler", (0.0, 0.0, 0.0)),
    ("delta_rotation_quaternion", (1.0, 0.0, 0.0, 0.0)),
    ("delta_scale", (1.0, 1.0, 1.0)),
)


def _fold_deltas(obj):
    """Move delta transforms into the regular ones, keeping the object where it is.

    ``transform_apply`` ignores deltas, so they are folded in first. Returns the
    exact previous property values, which ``_restore_deltas()`` puts back.
    """
    saved = {a: tuple(getattr(obj, a)) for a in _SAVED_ATTRS}
    mb = obj.matrix_basis.copy()
    for attr, value in _DELTA_DEFAULTS:
        setattr(obj, attr, value)
    obj.matrix_basis = mb
    return saved


# Restored as raw values: going back through a matrix could change the euler angles.
_SAVED_ATTRS = ("location", "rotation_euler", "rotation_quaternion",
                "rotation_axis_angle", "scale") + tuple(a for a, _ in _DELTA_DEFAULTS)


def _restore_deltas(obj, saved):
    for attr, value in saved.items():
        setattr(obj, attr, value)


def _transform_apply(context, objs, settings):
    """Run Blender's Apply Transform on exactly ``objs`` (not the user's selection)."""
    with context.temp_override(
        selected_editable_objects=objs,
        selected_objects=objs,
        active_object=objs[0],
        object=objs[0],
    ):
        bpy.ops.object.transform_apply(
            location=settings.check_location,
            rotation=settings.check_rotation,
            scale=settings.check_scale,
            isolate_users=settings.isolate_users,
        )


def _blender_error(exc):
    """The first 'Error: ...' line Blender put in an operator RuntimeError."""
    for line in str(exc).splitlines():
        if "Error: " in line:
            return line.split("Error: ", 1)[1].strip()
    return str(exc).strip()


def _depth(obj):
    d = 0
    while obj.parent is not None:
        obj, d = obj.parent, d + 1
    return d


def apply_transforms(context, objs, settings):
    """Apply the enabled transforms to ``objs``. Returns ``{name: reason}`` for refusals.

    All objects go to Blender in one call. Blender aborts the whole call if it
    refuses any one object (location/rotation on text objects and 2D curves;
    "Make Single User" when shared data is mixed with other objects), so on
    failure the objects are retried one at a time, parents first so applying a
    parent does not undo an already applied child. Refused objects keep their
    original transforms and deltas.
    """
    saved = {o.name: _fold_deltas(o) for o in objs} if settings.include_delta else {}
    try:
        _transform_apply(context, objs, settings)
        return {}
    except RuntimeError:
        pass  # Blender changed nothing ("aborting"); retry one by one below.

    refused = {}
    for o in sorted(objs, key=_depth):
        try:
            _transform_apply(context, [o], settings)
        except RuntimeError as exc:
            refused[o.name] = _blender_error(exc)
            if o.name in saved:
                _restore_deltas(o, saved[o.name])
    return refused


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

# One row of the result list: a pointer, so renaming the object keeps the row valid.
class TC_ResultItem(PropertyGroup):
    obj: PointerProperty(type=bpy.types.Object)


def _settings_changed(self, context):
    # Update callback for every option: keep the list current once a scan has run.
    if self.scanned:
        rescan(context)


# All options and the result list, stored per scene as Scene.transforms_checker.
class TC_Settings(PropertyGroup):
    check_location: BoolProperty(name="Location", default=True, update=_settings_changed)
    check_rotation: BoolProperty(name="Rotation", default=True, update=_settings_changed)
    check_scale: BoolProperty(name="Scale", default=True, update=_settings_changed)
    include_delta: BoolProperty(
        name="Delta Transforms", default=True, update=_settings_changed,
        description="Also flag non-zero delta transforms")
    selected_only: BoolProperty(
        name="Selected Only", default=False, update=_settings_changed,
        description="Only check selected objects")
    skip_hidden: BoolProperty(
        name="Skip Hidden", default=False, update=_settings_changed,
        description="Ignore objects hidden in the viewport")
    tolerance: FloatProperty(
        name="Tolerance", default=1e-4, min=0.0, soft_max=0.01,
        precision=5, update=_settings_changed,
        description="Values closer than this to the identity are treated as applied")
    object_types: EnumProperty(
        name="Object Types", items=OBJECT_TYPES, options={"ENUM_FLAG"},
        default=DEFAULT_TYPES, update=_settings_changed)
    isolate_users: BoolProperty(
        name="Make Single User", default=False,
        description="When applying, make multi-user object data single-user "
                    "(otherwise those objects are skipped)")
    show_options: BoolProperty(name="Options", default=False)

    results: CollectionProperty(type=TC_ResultItem)
    active_index: IntProperty(default=0)
    scanned: BoolProperty(default=False)  # False until the first scan, and after Clear


# ---------------------------------------------------------------------------
# Operators
# (No class docstrings: Blender would show them as tooltips. bl_description is the tooltip.)
# ---------------------------------------------------------------------------

class TC_OT_scan(Operator):
    bl_idname = "transforms_checker.scan"
    bl_label = "Check Transforms"
    bl_description = "Scan the scene for objects with unapplied transforms"
    bl_options = {"REGISTER"}

    def execute(self, context):
        n = rescan(context)
        if n:
            self.report({"WARNING"}, f"{n} object(s) with unapplied transforms")
        else:
            self.report({"INFO"}, "All transforms are applied")
        return {"FINISHED"}


def _select_only(context, objs):
    # Replace the selection with objs; the first becomes active. Switches to Object Mode.
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    if objs:
        context.view_layer.objects.active = objs[0]


class TC_OT_select(Operator):
    bl_idname = "transforms_checker.select"
    bl_label = "Select Flagged"
    bl_description = "Select all objects in the result list"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.transforms_checker
        # Hidden objects and objects outside this view layer cannot be selected.
        selected = [o for o in live_results(settings)
                    if o.name in context.view_layer.objects and o.visible_get()]
        _select_only(context, selected)
        self.report({"INFO"}, f"Selected {len(selected)} object(s)")
        return {"FINISHED"}


# Used by the list rows: clicking a name selects that object.
class TC_OT_select_one(Operator):
    bl_idname = "transforms_checker.select_one"
    bl_label = "Select Object"
    bl_description = "Select and make this object active"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.name)
        if obj is None or obj.name not in context.view_layer.objects:
            return {"CANCELLED"}
        _select_only(context, [obj])
        return {"FINISHED"}


def _name_list(names, limit=5):
    return ", ".join(names[:limit]) + (", ..." if len(names) > limit else "")


class TC_OT_apply(Operator):
    bl_idname = "transforms_checker.apply"
    bl_label = "Apply Transforms"
    bl_description = "Apply the checked transforms (location/rotation/scale) to flagged objects"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        settings = context.scene.transforms_checker
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        objs = []
        skipped = []
        for o in live_results(settings):
            # Linked/overridden objects can't be edited; shared data needs "Make Single User".
            if o.library or o.override_library or o.name not in context.view_layer.objects:
                skipped.append(o.name)
                continue
            if (o.data is not None and o.data.users > 1 and not settings.isolate_users):
                skipped.append(o.name)
                continue
            objs.append(o)

        refused = apply_transforms(context, objs, settings) if objs else {}

        rescan(context)
        # Blender silently leaves some types as they are (cameras, lights, volumes):
        # count anything still flagged as not applied rather than trusting the call.
        still = {o.name for o in live_results(settings)}
        not_applied = [o.name for o in objs if o.name in still and o.name not in refused]
        applied = len(objs) - len(refused) - len(not_applied)

        msg = f"Applied transforms on {applied} object(s)"
        if skipped:
            msg += f"; skipped {len(skipped)} (linked or multi-user data): " + _name_list(skipped)
        if refused:
            reasons = sorted(set(refused.values()))
            msg += f"; Blender refused {len(refused)}: " + _name_list(sorted(refused))
            msg += " (" + reasons[0] + (" ..." if len(reasons) > 1 else "") + ")"
        if not_applied:
            msg += f"; unchanged by Blender {len(not_applied)}: " + _name_list(not_applied)
        self.report({"WARNING"} if (skipped or refused or not_applied) else {"INFO"}, msg)
        return {"FINISHED"}


class TC_OT_clear(Operator):
    bl_idname = "transforms_checker.clear"
    bl_label = "Clear Results"
    bl_description = "Empty the result list"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.transforms_checker
        settings.results.clear()
        settings.scanned = False
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

_ICONS = None  # every valid icon name, filled on first use


def object_icon(obj):
    """Outliner icon for the object's type, or a generic one if Blender has none by that name."""
    global _ICONS
    if _ICONS is None:
        _ICONS = set(bpy.types.UILayout.bl_rna.functions["prop"]
                     .parameters["icon"].enum_items.keys())
    # e.g. LIGHT_PROBE -> OUTLINER_OB_LIGHTPROBE
    for name in (f"OUTLINER_OB_{obj.type}", f"OUTLINER_OB_{obj.type.replace('_', '')}"):
        if name in _ICONS:
            return name
    return "OBJECT_DATA"


# One row per scanned object: clickable name, then L / R / S letters for what is
# still unapplied, a warning icon for negative scale, or a checkmark once fixed.
class TC_UL_results(UIList):
    bl_idname = "TC_UL_results"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        obj = item.obj
        if obj is None:
            layout.label(text="(deleted)", icon="ERROR")
            return
        settings = context.scene.transforms_checker
        loc, rot, scale, negative = check_object(obj, settings)

        row = layout.row(align=True)
        op = row.operator("transforms_checker.select_one", text=obj.name,
                          icon=object_icon(obj), emboss=False)
        op.name = obj.name

        flags = row.row(align=True)
        flags.alignment = "RIGHT"
        if not (loc or rot or scale or negative):
            flags.label(text="", icon="CHECKMARK")
            return
        if loc:
            flags.label(text="L")
        if rot:
            flags.label(text="R")
        if scale:
            flags.label(text="S")
        if negative:
            flags.label(text="", icon="ERROR")

    def filter_items(self, context, data, propname):
        # Hide rows whose object was deleted; keep the stored order.
        items = getattr(data, propname)
        flt_flags = [self.bitflag_filter_item if it.obj is not None else 0 for it in items]
        return flt_flags, []


class TC_PT_main(Panel):
    bl_label = "Transforms Checker"
    bl_idname = "TC_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Transforms"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.transforms_checker

        row = layout.row(align=True)
        row.prop(settings, "check_location", toggle=True)
        row.prop(settings, "check_rotation", toggle=True)
        row.prop(settings, "check_scale", toggle=True)

        box = layout.box()
        box.prop(settings, "show_options",
                 icon="TRIA_DOWN" if settings.show_options else "TRIA_RIGHT", emboss=False)
        if settings.show_options:
            col = box.column(align=True)
            col.prop(settings, "selected_only")
            col.prop(settings, "skip_hidden")
            col.prop(settings, "include_delta")
            col.prop(settings, "isolate_users")
            col.prop(settings, "tolerance")
            box.label(text="Object Types:")
            grid = box.grid_flow(columns=2, align=True)
            grid.prop(settings, "object_types")

        layout.operator("transforms_checker.scan", icon="VIEWZOOM")

        if not settings.scanned:
            return

        # One check per object per redraw (the panel redraws on every hover).
        flagged = 0
        any_negative = False
        for it in settings.results:
            if it.obj is None:
                continue
            flags = check_object(it.obj, settings)
            if _flagged(flags, settings):
                flagged += 1
                any_negative = any_negative or flags[3]
        if not flagged:
            layout.label(text="All transforms applied", icon="CHECKMARK")
            return

        layout.label(text=f"{flagged} object(s) not applied", icon="ERROR")
        layout.template_list("TC_UL_results", "", settings, "results",
                             settings, "active_index", rows=6)
        layout.label(text="L = location  R = rotation  S = scale", icon="INFO")

        if any_negative:
            layout.label(text="Warning icon = negative scale", icon="ERROR")

        row = layout.row(align=True)
        row.operator("transforms_checker.select", icon="RESTRICT_SELECT_OFF")
        row.operator("transforms_checker.clear", text="", icon="X")
        layout.operator("transforms_checker.apply", icon="CHECKMARK")


classes = (
    TC_ResultItem,
    TC_Settings,
    TC_OT_scan,
    TC_OT_select,
    TC_OT_select_one,
    TC_OT_apply,
    TC_OT_clear,
    TC_UL_results,
    TC_PT_main,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.transforms_checker = PointerProperty(type=TC_Settings)


def unregister():
    del bpy.types.Scene.transforms_checker
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
