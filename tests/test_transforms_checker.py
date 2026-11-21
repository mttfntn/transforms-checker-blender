"""Unit tests for the Transforms Checker add-on. Runs inside Blender (see tests/run.py).

Covers detection (check_object), scanning filters (rescan), the operators
(scan / select / select_one / apply / clear), registration, and the panel and
list draw code via a validating mock layout.
"""

import math
import os
import sys
import types
import unittest

import bpy
from mathutils import Matrix

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tc_loader import MockLayout, load_addon, make_mesh, make_object, reset_scene  # noqa: E402

tc = load_addon()
tc.register()


def settings():
    return bpy.context.scene.transforms_checker


def flagged_names():
    return [it.obj.name for it in settings().results]


def world_verts(obj):
    bpy.context.view_layer.update()  # matrix_world is stale until the depsgraph updates
    return [obj.matrix_world @ v.co for v in obj.data.vertices]


def assert_vecs_close(tc_case, a, b, places=5):
    tc_case.assertEqual(len(a), len(b))
    for u, v in zip(a, b):
        tc_case.assertLess((u - v).length, 10 ** -places, f"{u} != {v}")


class Base(unittest.TestCase):
    def setUp(self):
        reset_scene()


class TestCheckObject(Base):
    def test_identity_not_flagged(self):
        o = make_mesh("A")
        self.assertEqual(tc.check_object(o, settings()), (False, False, False, False))

    def test_location(self):
        o = make_mesh("A")
        o.location.x = 0.5
        self.assertEqual(tc.check_object(o, settings())[:3], (True, False, False))

    def test_rotation_euler(self):
        o = make_mesh("A")
        o.rotation_euler.z = 0.1
        self.assertEqual(tc.check_object(o, settings())[:3], (False, True, False))

    def test_euler_full_turn_not_flagged(self):
        o = make_mesh("A")
        o.rotation_euler.z = 2 * math.pi
        self.assertFalse(tc.check_object(o, settings())[1])

    def test_quaternion_negated_identity_not_flagged(self):
        o = make_mesh("A")
        o.rotation_mode = "QUATERNION"
        o.rotation_quaternion = (-1, 0, 0, 0)
        self.assertFalse(tc.check_object(o, settings())[1])

    def test_quaternion_rotation(self):
        o = make_mesh("A")
        o.rotation_mode = "QUATERNION"
        o.rotation_quaternion = (0.9, 0.1, 0, 0)
        self.assertTrue(tc.check_object(o, settings())[1])

    def test_axis_angle(self):
        o = make_mesh("A")
        o.rotation_mode = "AXIS_ANGLE"
        o.rotation_axis_angle = (0.5, 0, 0, 1)
        self.assertTrue(tc.check_object(o, settings())[1])

    def test_axis_angle_zero_axis(self):
        o = make_mesh("A")
        o.rotation_mode = "AXIS_ANGLE"
        o.rotation_axis_angle = (0.5, 0, 0, 0)
        self.assertFalse(tc.check_object(o, settings())[1])

    def test_axis_angle_ignores_scale(self):
        o = make_mesh("A")
        o.rotation_mode = "AXIS_ANGLE"
        o.rotation_axis_angle = (0.0, 0, 0, 1)
        o.scale = (2, 3, 4)
        self.assertEqual(tc.check_object(o, settings())[:3], (False, False, True))

    def test_scale_and_negative(self):
        o = make_mesh("A")
        o.scale = (1, -1, 1)
        self.assertEqual(tc.check_object(o, settings()), (False, False, True, True))

    def test_tolerance(self):
        o = make_mesh("A")
        o.location.x = 5e-5
        o.scale.x = 1 + 5e-5
        self.assertEqual(tc.check_object(o, settings())[:3], (False, False, False))
        settings().tolerance = 1e-5
        self.assertEqual(tc.check_object(o, settings())[:3], (True, False, True))

    def test_toggles(self):
        o = make_mesh("A")
        o.location.x = 1
        o.rotation_euler.x = 1
        o.scale.x = 2
        s = settings()
        s.check_location = s.check_rotation = s.check_scale = False
        self.assertEqual(tc.check_object(o, s)[:3], (False, False, False))

    def test_delta(self):
        o = make_mesh("A")
        o.delta_location.x = 1
        o.delta_rotation_euler.y = 0.3
        o.delta_scale.z = 2
        self.assertEqual(tc.check_object(o, settings())[:3], (True, True, True))
        settings().include_delta = False
        self.assertEqual(tc.check_object(o, settings())[:3], (False, False, False))

    def test_delta_cancels_rotation(self):
        o = make_mesh("A")
        o.rotation_euler.z = 0.4
        o.delta_rotation_euler.z = -0.4
        self.assertFalse(tc.check_object(o, settings())[1])

    def test_delta_quaternion(self):
        o = make_mesh("A")
        o.rotation_mode = "QUATERNION"
        o.delta_rotation_quaternion = (0.9, 0, 0.1, 0)
        self.assertTrue(tc.check_object(o, settings())[1])


class TestScan(Base):
    def test_sorted_and_filtered_by_type(self):
        for n in ("b", "a", "c"):
            make_mesh(n).location.x = 1
        make_mesh("clean")
        e = make_object("empty", None)
        e.scale = (2, 2, 2)
        cam = make_object("cam", bpy.data.cameras.new("cam"))
        cam.location.z = 5
        bpy.ops.transforms_checker.scan()
        self.assertEqual(flagged_names(), ["a", "b", "c"])
        self.assertTrue(settings().scanned)

    def test_object_types_option_rescans(self):
        make_mesh("m").location.x = 1
        make_object("empty", None).location.x = 1
        bpy.ops.transforms_checker.scan()
        settings().object_types = {"EMPTY"}
        self.assertEqual(flagged_names(), ["empty"])

    def test_selected_only(self):
        a, b = make_mesh("a"), make_mesh("b")
        a.location.x = b.location.x = 1
        b.select_set(True)
        a.select_set(False)
        settings().selected_only = True
        bpy.ops.transforms_checker.scan()
        self.assertEqual(flagged_names(), ["b"])

    def test_skip_hidden(self):
        a, b = make_mesh("a"), make_mesh("b")
        a.location.x = b.location.x = 1
        b.hide_set(True)
        settings().skip_hidden = True
        bpy.ops.transforms_checker.scan()
        self.assertEqual(flagged_names(), ["a"])

    def test_live_results_drop_deleted_and_fixed(self):
        a, b, c = make_mesh("a"), make_mesh("b"), make_mesh("c")
        for o in (a, b, c):
            o.location.x = 1
        bpy.ops.transforms_checker.scan()
        bpy.data.objects.remove(b)
        c.location.x = 0
        self.assertEqual([o.name for o in tc.live_results(settings())], ["a"])

    def test_negative_scale_needs_scale_check(self):
        o = make_mesh("a")
        o.scale = (-1, 1, 1)
        settings().check_scale = False
        self.assertFalse(tc.is_flagged(o, settings()))
        settings().check_scale = True
        self.assertTrue(tc.is_flagged(o, settings()))

    def test_clear(self):
        make_mesh("a").location.x = 1
        bpy.ops.transforms_checker.scan()
        bpy.ops.transforms_checker.clear()
        self.assertEqual(len(settings().results), 0)
        self.assertFalse(settings().scanned)


class TestSelect(Base):
    def test_select_flagged(self):
        a, b = make_mesh("a"), make_mesh("b")
        a.location.x = 1
        b.select_set(True)
        bpy.ops.transforms_checker.scan()
        bpy.ops.transforms_checker.select()
        self.assertTrue(a.select_get())
        self.assertFalse(b.select_get())
        self.assertEqual(bpy.context.view_layer.objects.active, a)

    def test_select_one(self):
        a, b = make_mesh("a"), make_mesh("b")
        a.select_set(True)
        bpy.ops.transforms_checker.select_one(name="b")
        self.assertFalse(a.select_get())
        self.assertTrue(b.select_get())
        self.assertEqual(bpy.ops.transforms_checker.select_one(name="nope"), {"CANCELLED"})


class TestApply(Base):
    def apply(self):
        bpy.ops.transforms_checker.scan()
        return bpy.ops.transforms_checker.apply("EXEC_DEFAULT")

    def test_apply_preserves_world_space(self):
        o = make_mesh("a")
        o.location = (1, 2, 3)
        o.rotation_euler = (0.3, 0.2, 0.1)
        o.scale = (2, 1, 0.5)
        o.delta_location = (0, 1, 0)
        o.delta_scale = (1.5, 1, 1)
        before = world_verts(o)
        self.assertEqual(self.apply(), {"FINISHED"})
        assert_vecs_close(self, world_verts(o), before)
        self.assertEqual(o.matrix_basis, Matrix.Identity(4))
        self.assertEqual(tuple(o.delta_scale), (1, 1, 1))
        self.assertEqual(flagged_names(), [])

    def test_apply_respects_toggles(self):
        o = make_mesh("a")
        o.location = (1, 0, 0)
        o.scale = (2, 2, 2)
        settings().check_location = False
        self.apply()
        self.assertEqual(tuple(o.location), (1, 0, 0))
        self.assertEqual(tuple(o.scale), (1, 1, 1))

    def test_multi_user_skipped_then_isolated(self):
        a = make_mesh("a")
        b = make_mesh("b", data=a.data)
        a.scale = (2, 2, 2)
        self.apply()
        self.assertEqual(tuple(a.scale), (2, 2, 2))
        self.assertEqual(flagged_names(), ["a"])
        settings().isolate_users = True
        before = world_verts(a)
        self.apply()
        self.assertEqual(tuple(a.scale), (1, 1, 1))
        self.assertNotEqual(a.data, b.data)
        assert_vecs_close(self, world_verts(a), before)

    def test_children_keep_world_transform(self):
        p, c = make_mesh("p"), make_mesh("c")
        c.parent = p
        p.scale = (2, 2, 2)
        p.rotation_euler.z = 0.5
        bpy.context.view_layer.update()
        before = world_verts(c)
        settings().object_types = {"MESH"}
        self.apply()
        bpy.context.view_layer.update()
        assert_vecs_close(self, world_verts(c), before)

    def test_nothing_to_apply(self):
        make_mesh("a")
        self.assertEqual(self.apply(), {"FINISHED"})


class TestRegistration(unittest.TestCase):
    def test_reregister(self):
        tc.unregister()
        self.assertFalse(hasattr(bpy.types.Scene, "transforms_checker"))
        tc.register()
        self.assertTrue(hasattr(bpy.context.scene, "transforms_checker"))
        self.assertTrue(hasattr(bpy.ops.transforms_checker, "apply"))


class TestDraw(Base):
    def draw_panel(self):
        log = []
        tc.TC_PT_main.draw(types.SimpleNamespace(layout=MockLayout(log)), bpy.context)
        return log

    def test_panel_states(self):
        settings().show_options = True
        self.assertNotIn(("template_list", "results"), self.draw_panel())
        bpy.ops.transforms_checker.scan()
        self.assertIn(("label", "All transforms applied"), self.draw_panel())
        o = make_mesh("a")
        o.scale = (-1, 1, 1)
        bpy.ops.transforms_checker.scan()
        log = self.draw_panel()
        self.assertIn(("template_list", "results"), log)
        self.assertIn(("operator", "transforms_checker.apply"), log)
        self.assertIn(("label", "Warning icon = negative scale"), log)

    def test_list_items(self):
        objs = [make_mesh("m"), make_object("e", None),
                make_object("c", bpy.data.cameras.new("c")),
                make_object("l", bpy.data.lights.new("l", "POINT")),
                make_object("arm", bpy.data.armatures.new("arm"))]
        for o in objs:
            o.location.x = 1
        objs[0].scale = (-1, 1, 1)
        s = settings()
        s.object_types = {t for t, _, _ in tc.OBJECT_TYPES}
        bpy.ops.transforms_checker.scan()
        objs[1].location.x = 0  # now clean: drawn with a checkmark
        fake = types.SimpleNamespace(bitflag_filter_item=1 << 30)  # UIList.bitflag_filter_item is instance-only
        for i, item in enumerate(s.results):
            log = []
            tc.TC_UL_results.draw_item(fake, bpy.context, MockLayout(log), s, item,
                                       0, s, "active_index", i)
            self.assertIn(("operator", "transforms_checker.select_one"), log)
        flags, order = tc.TC_UL_results.filter_items(fake, bpy.context, s, "results")
        self.assertEqual(len(flags), len(s.results))
        self.assertEqual(order, [])

    def test_object_icon(self):
        for t in ("m", None):
            o = make_mesh("m") if t else make_object("e", None)
            self.assertIn(tc.object_icon(o), MockLayout.__init__.__globals__["_ICONS"])


if __name__ == "__main__":
    result = unittest.main(argv=[sys.argv[0]], exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
