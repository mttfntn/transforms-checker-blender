bl_info = {
    "name": "Transforms Checker",
    "author": "Matteo Fontana",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar (N) > Transforms",
    "description": "Find objects whose location, rotation or scale has not been applied",
    "category": "Object",
}

import bpy
from mathutils import Quaternion
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
)
from bpy.types import Operator, Panel, PropertyGroup, UIList


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

DEFAULT_TYPES = {
    "MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES",
    "POINTCLOUD", "VOLUME", "GREASEPENCIL", "ARMATURE", "LATTICE",
}


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

def check_object(obj, settings):
    """Return (loc, rot, scale, negative_scale) flags for unapplied transforms."""
    tol = settings.tolerance

    loc_vals = list(obj.location)
    scale_vals = list(obj.scale)
    rot_quat = obj.rotation_euler.to_quaternion() if obj.rotation_mode not in {
        "QUATERNION", "AXIS_ANGLE"} else None
    if obj.rotation_mode == "QUATERNION":
        rot_quat = obj.rotation_quaternion.normalized()
    elif obj.rotation_mode == "AXIS_ANGLE":
        angle, x, y, z = obj.rotation_axis_angle
        rot_quat = Quaternion((x, y, z), angle) if (x or y or z) else Quaternion()

    if settings.include_delta:
        loc_vals += list(obj.delta_location)
        scale_vals += list(obj.delta_scale)
        delta_q = (obj.delta_rotation_quaternion.normalized()
                   if obj.rotation_mode == "QUATERNION"
                   else obj.delta_rotation_euler.to_quaternion())
        rot_quat = delta_q @ rot_quat

    loc = settings.check_location and any(abs(v) > tol for v in loc_vals)
    # Quaternion q and -q are the same rotation; compare |w| to 1.
    rot = settings.check_rotation and (1.0 - abs(rot_quat.w)) > tol * tol
    scale = settings.check_scale and any(abs(v - 1.0) > tol for v in scale_vals)
    negative = any(v < 0.0 for v in scale_vals)
    return loc, rot, scale, negative


def candidate_objects(context, settings):
    objs = context.selected_objects if settings.selected_only else context.scene.objects
    for obj in objs:
        if obj.type not in settings.object_types:
            continue
        if settings.skip_hidden and not obj.visible_get():
            continue
        yield obj


def is_flagged(obj, settings):
    loc, rot, scale, negative = check_object(obj, settings)
    return loc or rot or scale or (negative and settings.check_scale)


def rescan(context):
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
    """Result entries whose object still exists and is still flagged."""
    return [it.obj for it in settings.results
            if it.obj is not None and is_flagged(it.obj, settings)]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

class TC_ResultItem(PropertyGroup):
    obj: PointerProperty(type=bpy.types.Object)


def _settings_changed(self, context):
    if self.scanned:
        rescan(context)


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
    scanned: BoolProperty(default=False)


# ---------------------------------------------------------------------------
# Operators
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


class TC_OT_select(Operator):
    bl_idname = "transforms_checker.select"
    bl_label = "Select Flagged"
    bl_description = "Select all objects in the result list"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.transforms_checker
        objs = live_results(settings)
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for o in context.view_layer.objects:
            o.select_set(False)
        selected = [o for o in objs if o.name in context.view_layer.objects and o.visible_get()]
        for o in selected:
            o.select_set(True)
        if selected:
            context.view_layer.objects.active = selected[0]
        self.report({"INFO"}, f"Selected {len(selected)} object(s)")
        return {"FINISHED"}


class TC_OT_select_one(Operator):
    bl_idname = "transforms_checker.select_one"
    bl_label = "Select Object"
    bl_description = "Select and make this object active"
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.name)
        if obj is None or obj.name not in context.view_layer.objects:
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for o in context.view_layer.objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {"FINISHED"}


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
            if o.library or o.override_library or o.name not in context.view_layer.objects:
                skipped.append(o.name)
                continue
            if (o.data is not None and o.data.users > 1 and not settings.isolate_users):
                skipped.append(o.name)
                continue
            objs.append(o)

        if objs:
            # Delta transforms are not touched by transform_apply; fold them in first.
            if settings.include_delta:
                for o in objs:
                    mb = o.matrix_basis.copy()
                    o.delta_location = (0, 0, 0)
                    o.delta_rotation_euler = (0, 0, 0)
                    o.delta_rotation_quaternion = (1, 0, 0, 0)
                    o.delta_scale = (1, 1, 1)
                    o.matrix_basis = mb

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

        rescan(context)
        msg = f"Applied transforms on {len(objs)} object(s)"
        if skipped:
            msg += f"; skipped {len(skipped)} (linked or multi-user data): " + ", ".join(skipped[:5])
            if len(skipped) > 5:
                msg += ", ..."
            self.report({"WARNING"}, msg)
        else:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


class TC_OT_clear(Operator):
    bl_idname = "transforms_checker.clear"
    bl_label = "Clear Results"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.transforms_checker
        settings.results.clear()
        settings.scanned = False
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

_ICONS = None


def object_icon(obj):
    global _ICONS
    if _ICONS is None:
        _ICONS = set(bpy.types.UILayout.bl_rna.functions["prop"]
                     .parameters["icon"].enum_items.keys())
    for name in (f"OUTLINER_OB_{obj.type}", f"OUTLINER_OB_{obj.type.replace('_', '')}"):
        if name in _ICONS:
            return name
    return "OBJECT_DATA"


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

        flagged = live_results(settings)
        if not flagged:
            layout.label(text="All transforms applied", icon="CHECKMARK")
            return

        layout.label(text=f"{len(flagged)} object(s) not applied", icon="ERROR")
        layout.template_list("TC_UL_results", "", settings, "results",
                             settings, "active_index", rows=6)
        layout.label(text="L = location  R = rotation  S = scale", icon="INFO")

        if any(check_object(o, settings)[3] for o in flagged):
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


if __name__ == "__main__":
    register()
