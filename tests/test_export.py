"""检查/导出预算回归：小 Bundle、低阈值与 mock，不访问线上服务。"""

import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, PropertyMock, patch
import zipfile

from flask import Flask
from PIL import Image
import UnityPy

from blueprints import unity
from extensions import UNITY_TASK_LOCK
from utils import export_limits as limits

ROOT = Path(__file__).resolve().parents[1]


def text_object(path_id=1, tree=None, size=16, type_name="TextAsset"):
    return SimpleNamespace(
        path_id=path_id, byte_size=size, type=SimpleNamespace(name=type_name),
        read_typetree=Mock(return_value=tree or {"m_Name": "small", "m_Script": '{"value":1}'}),
        read=Mock(),
    )


def texture_object(path_id=1, size=(2, 2), external_size=0):
    data = Mock()
    data.m_Name = "texture"
    data.m_Width, data.m_Height = size
    data.image_data = b"" if external_size else b"data"
    data.m_StreamData = SimpleNamespace(size=external_size)
    image = PropertyMock(side_effect=lambda: Image.new("RGBA", size, (12, 34, 56, 255)))
    type(data).image = image
    obj = text_object(path_id, type_name="Texture2D")
    obj.read.return_value = data
    return obj, image


class ExportRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__, template_folder=str(ROOT / "templates"))
        self.app.testing = True
        self.app.config["MAX_CONTENT_LENGTH"] = 150 * limits.MIB
        self.app.register_blueprint(unity.unity_bp)
        self.client = self.app.test_client()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workdirs = []
        real_mkdtemp = tempfile.mkdtemp

        def make_dir(**kwargs):
            path = real_mkdtemp(dir=self.temp.name, **kwargs)
            self.workdirs.append(Path(path))
            return path

        self.obj = text_object()
        self.env = SimpleNamespace(objects=[self.obj])
        for name, options in (
            ("UnityPy.load", {"return_value": self.env}),
            ("tempfile.mkdtemp", {"side_effect": make_dir}),
            ("cleanup_old_temp", {}),
            ("release_unity_lock", {"wraps": unity.release_unity_lock}),
        ):
            patcher = patch("blueprints.unity." + name, **options)
            mock = patcher.start()
            self.addCleanup(patcher.stop)
            setattr(self, name.split(".")[-1], mock)
        self.assertFalse(UNITY_TASK_LOCK.locked())

    def post(self, path="/unpack", **fields):
        return self.client.post(path, data={
            "bundle": (io.BytesIO(b"small bundle"), "small.bundle"), **fields,
        }, headers={"Accept": "application/json"})

    def assert_error(self, result, status=413):
        self.assertEqual(result.status_code, status, result.data)
        self.assertFalse(result.json["success"])
        self.assertFalse(UNITY_TASK_LOCK.locked())
        self.assertFalse(list(Path(self.temp.name).iterdir()))

    def read_zip(self, response):
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(UNITY_TASK_LOCK.locked())
        archive = zipfile.ZipFile(io.BytesIO(response.data))
        self.assertTrue(self.workdirs[-1].exists())
        # 成功目录只留原 Bundle 与 ZIP，不积累 PNG。
        self.assertEqual({p.name for p in self.workdirs[-1].iterdir()}, {"input.bundle", "output.zip"})
        response.close()
        self.assertFalse(self.workdirs[-1].exists())
        return archive

    def test_fast_inspect_never_reads_object_body(self):
        result = self.post("/unity/inspect")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["report"]["total_objects"], 1)
        self.assertEqual(result.json["report"]["objects"][0]["export_modes"], ["json", "csv"])
        self.obj.read.assert_not_called()
        self.obj.read_typetree.assert_not_called()
        self.assertFalse(UNITY_TASK_LOCK.locked())
        self.assertFalse(self.workdirs[0].exists())

    def test_explicit_fast_is_accepted(self):
        self.assertEqual(self.post("/unity/inspect", inspect_depth="fast").status_code, 200)

    def test_unknown_inspect_depth_is_400_before_load(self):
        for depth in ("deep", "unknown", "FAST", ""):
            with self.subTest(depth=depth):
                self.assert_error(self.post("/unity/inspect", inspect_depth=depth), 400)
        self.load.assert_not_called()

    def test_frontend_no_longer_has_deep_or_all_types(self):
        template = (ROOT / "templates" / "tab_unity.html").read_text(encoding="utf-8")
        for dead_code in ("inspectDepth", "inspect_depth", "value=\"deep\"", "深度检查", "__all__", "'AudioClip'"):
            self.assertNotIn(dead_code, template)
        self.assertFalse(hasattr(unity, "inspect_env"))
        self.assertFalse(hasattr(unity, "get_object_display_name"))
        response = self.client.get("/unity")
        self.assertEqual(response.status_code, 200)
        rendered = response.get_data(as_text=True)
        self.assertNotIn("{{ export_type_options", rendered)
        allowed = sorted(unity.LIGHT_EDITABLE_TYPES | unity.JSON_LIKE_TYPES | unity.IMAGE_TYPES)
        self.assertIn("const exportTypeOptions = " + json.dumps(allowed), rendered)

    def test_inspect_object_and_report_budgets(self):
        self.env.objects.append(text_object(2))
        for setting, cap in (("MAX_OBJECTS", 1), ("REPORT_MAX_ENTRIES", 1), ("REPORT_MAX_BYTES", 20)):
            with self.subTest(setting=setting), patch.object(limits, setting, cap):
                self.assert_error(self.post("/unity/inspect"))

    def test_inspect_strings_are_bounded(self):
        self.obj.type.name = "x" * 10
        with patch.object(limits, "NAME_MAX_CHARS", 8):
            self.assert_error(self.post("/unity/inspect"))

    def test_inspect_load_failure_is_400_and_cleans(self):
        self.load.side_effect = ValueError("损坏的 Bundle")
        self.assert_error(self.post("/unity/inspect"), 400)

    def test_inspect_recursion_and_memory_failures_still_release_lock(self):
        for error, status in ((RecursionError("复杂结构"), 413), (MemoryError("内存不足"), 500)):
            with self.subTest(error=error):
                self.load.side_effect = error
                self.release_unity_lock.reset_mock()
                self.assert_error(self.post("/unity/inspect"), status)
                self.release_unity_lock.assert_called_once()

    def test_typetree_recommended_and_patch_presets(self):
        for preset in ("recommended", "patch"):
            with self.subTest(preset=preset), self.read_zip(self.post(preset=preset)) as archive:
                tree = json.loads(archive.read("TextAsset/small_1.json"))
                self.assertEqual(tree["m_Script"], {"value": 1})
                self.assertEqual(json.loads(archive.read("_index.json")), {"1": "TextAsset/small_1.json"})
        self.assertEqual(self.obj.read_typetree.call_count, 2)

    def test_advanced_csv_and_manual_mode(self):
        with self.read_zip(self.post(preset="advanced", format="csv", types="TextAsset", mode="manual")) as archive:
            content = archive.read("TextAsset/small_1.csv").decode("utf-8-sig")
            self.assertIn("m_Name,small", content)
            self.assertIn("value", content)

    def test_images_preset_deletes_temporary_png(self):
        self.obj, image = texture_object()
        self.env.objects = [self.obj]
        with self.read_zip(self.post(preset="images")) as archive:
            with Image.open(io.BytesIO(archive.read("Images/texture_1.png"))) as output:
                self.assertEqual(output.size, (2, 2))
        image.assert_called_once()

    def test_normal_sprite_export_and_reused_backing_texture(self):
        texture, _ = texture_object(100)
        texture.assets_file = object()
        pointer = Mock()
        pointer.deref.return_value = texture
        sprites = []
        for path_id in (1, 2):
            data = Mock()
            data.m_Name = "sprite"
            data.m_Rect = SimpleNamespace(width=1, height=1)
            data.m_SpriteAtlas = None
            data.m_AtlasTags = []
            data.m_RD = SimpleNamespace(texture=pointer, alphaTexture=None,
                                        textureRect=SimpleNamespace(width=1, height=1))
            type(data).image = PropertyMock(side_effect=lambda: Image.new("RGBA", (1, 1)))
            obj = text_object(path_id, type_name="Sprite")
            obj.read.return_value = data
            sprites.append(obj)
        self.env.objects = sprites
        with self.read_zip(self.post(preset="images")) as archive:
            self.assertIn("Images/sprite_1.png", archive.namelist())
            self.assertIn("Images/sprite_2.png", archive.namelist())
        # 相同底图的轻量 metadata 不反复读取；库图像缓存预算按独立底图计数。
        texture.read.assert_called_once()

    def test_unselected_objects_are_not_decoded(self):
        obj = text_object(2, type_name="AudioClip")
        self.env.objects.append(obj)
        response = self.post()
        self.read_zip(response).close()
        obj.read.assert_not_called()
        obj.read_typetree.assert_not_called()

    def test_unknown_export_types_do_not_enable_all(self):
        for types in ("__all__", "AudioClip", "unknown"):
            with self.subTest(types=types):
                self.assert_error(self.post(preset="advanced", types=types), 400)
        self.load.assert_not_called()

    def test_export_types_are_intersected_with_server_allowlist(self):
        self.env.objects.append(text_object(2, type_name="AudioClip"))
        with self.read_zip(self.post(preset="advanced", types=["TextAsset", "AudioClip", "__all__"])) as archive:
            summary = json.loads(archive.read("_export_summary.json"))
            self.assertEqual(summary["selected_types"], ["TextAsset"])
        self.env.objects[1].read_typetree.assert_not_called()

    def test_invalid_preset_format_mode_are_400(self):
        for fields in ({"preset": "unknown"}, {"format": "raw"}, {"mode": "unknown"}):
            with self.subTest(fields=fields):
                self.assert_error(self.post(**fields), 400)
        self.load.assert_not_called()

    def test_object_count_budget_cleans_partial_output(self):
        self.env.objects.append(text_object(2))
        with patch.object(limits, "MAX_OBJECTS", 1):
            self.assert_error(self.post())
        self.env.objects[1].read_typetree.assert_not_called()

    def test_source_binary_limits_precede_typetree_read(self):
        with patch.object(limits, "RAW_MAX_BYTES", 15):
            self.assert_error(self.post())
        self.obj.read_typetree.assert_not_called()
        self.env.objects.append(text_object(2))
        with patch.object(limits, "RAW_TOTAL_BYTES", 20):
            self.assert_error(self.post())
        self.env.objects[1].read_typetree.assert_not_called()

    def test_text_member_and_total_limits_abort(self):
        self.env.objects.append(text_object(2))
        for setting, cap in (("TEXT_MAX_BYTES", 10), ("TEXT_TOTAL_BYTES", 60), ("EXPORT_TOTAL_BYTES", 60)):
            with self.subTest(setting=setting), patch.object(limits, setting, cap):
                self.assert_error(self.post())

    def test_csv_budget_aborts(self):
        with patch.object(limits, "TEXT_MAX_BYTES", 12):
            self.assert_error(self.post(preset="advanced", format="csv", types="TextAsset"))

    def test_typetree_structure_limits_abort(self):
        for setting, cap in (("TREE_MAX_DEPTH", 2), ("TREE_MAX_NODES", 3), ("TREE_TOTAL_NODES", 3), ("TREE_MAX_STRING_CHARS", 4)):
            with self.subTest(setting=setting), patch.object(limits, setting, cap):
                self.assert_error(self.post())

    def test_embedded_json_depth_is_bounded_before_parsing(self):
        self.obj.read_typetree.return_value = {"m_Name": "small", "m_Script": '{"a":{"b":{"c":1}}}'}
        with patch.object(limits, "TREE_MAX_DEPTH", 2), patch("blueprints.unity.json.loads") as loads:
            result = self.post()
            self.assertEqual(result.status_code, 413)
            loads.assert_not_called()
        self.assertFalse(UNITY_TASK_LOCK.locked())
        self.assertFalse(list(Path(self.temp.name).iterdir()))

    def test_export_json5_budget_is_independent_of_repack_budget(self):
        self.obj.read_typetree.return_value = {"m_Name": "small", "m_Script": "{value: 'nonstandard JSON'}"}
        with patch.object(limits, "JSON5_MAX_BYTES", 8), \
                patch.object(unity.patch_limits, "JSON5_MAX_BYTES", 128), \
                patch("blueprints.unity.json5.loads") as parse:
            self.assert_error(self.post(mode="manual"))
            parse.assert_not_called()

    def test_single_image_pixels_and_side_limits_precede_decode(self):
        self.obj, image = texture_object(size=(3, 3))
        self.env.objects = [self.obj]
        for setting, cap in (("IMAGE_MAX_PIXELS", 8), ("IMAGE_MAX_SIDE", 2)):
            with self.subTest(setting=setting), patch.object(limits, setting, cap):
                self.assert_error(self.post(preset="images"))
        image.assert_not_called()

    def test_total_image_pixels_precede_second_decode(self):
        first, image1 = texture_object(1)
        second, image2 = texture_object(2)
        self.env.objects = [first, second]
        with patch.object(limits, "IMAGE_TOTAL_PIXELS", 7):
            self.assert_error(self.post(preset="images"))
        image1.assert_called_once()
        image2.assert_not_called()

    def test_external_texture_data_binary_budget_precedes_decode(self):
        obj, image = texture_object(external_size=100)
        self.env.objects = [obj]
        with patch.object(limits, "RAW_MAX_BYTES", 50):
            self.assert_error(self.post(preset="images"))
        image.assert_not_called()

    def test_png_size_and_total_payload_limits_abort_during_save(self):
        obj, _ = texture_object()
        self.env.objects = [obj]
        for setting, cap in (("PNG_MAX_BYTES", 16), ("EXPORT_TOTAL_BYTES", 16)):
            with self.subTest(setting=setting), patch.object(limits, setting, cap):
                self.assert_error(self.post(preset="images"))

    def test_image_temp_file_is_deleted_before_next_image(self):
        first, _ = texture_object(1)
        second, image2 = texture_object(2)

        def decode_second():
            self.assertFalse(list(self.workdirs[0].glob("image_*.png")))
            return Image.new("RGBA", (2, 2))

        image2.side_effect = decode_second
        self.env.objects = [first, second]
        self.read_zip(self.post(preset="images")).close()

    def test_budget_exception_is_not_swallowed_as_failed_object(self):
        second = text_object(2)
        self.env.objects.append(second)
        with patch.object(limits, "TEXT_MAX_BYTES", 10):
            self.assert_error(self.post())
        second.read_typetree.assert_not_called()

    def test_file_count_includes_index_and_summary(self):
        with patch.object(limits, "EXPORT_MAX_FILES", 1):
            self.assert_error(self.post())

    def test_temp_disk_budget_precedes_upload_write(self):
        with patch.object(limits, "TEMP_MAX_BYTES", 20):
            self.assert_error(self.post())
        self.load.assert_not_called()

    def test_temp_disk_budget_counts_extra_multipart_uploads(self):
        with patch.object(limits, "TEMP_MAX_BYTES", 30):
            result = self.client.post("/unpack", data={
                "bundle": (io.BytesIO(b"small bundle"), "small.bundle"),
                "extra": (io.BytesIO(b"x" * 20), "extra.bin"),
            }, headers={"Accept": "application/json"})
            self.assert_error(result)
        self.load.assert_not_called()

    def test_temp_disk_budget_covers_zip_and_png(self):
        obj, _ = texture_object()
        self.env.objects = [obj]
        with patch.object(limits, "TEMP_MAX_BYTES", 100):
            self.assert_error(self.post(preset="images"))

    def test_zip_size_budget_aborts_during_compressed_write(self):
        with patch.object(limits, "ZIP_MAX_BYTES", 32):
            self.assert_error(self.post())

    def test_zip_central_directory_is_also_bounded(self):
        # 空包仅 summary；限制在成员结束后、中心目录写入之前。
        with self.read_zip(self.post(include_index="0")) as archive:
            start_of_directory = archive.start_dir
        with patch.object(limits, "ZIP_MAX_BYTES", start_of_directory):
            self.assert_error(self.post(include_index="0"))

    def test_failure_paths_cleanup_and_release_once(self):
        for error, status in ((RuntimeError("读取失败"), 500), (RecursionError("复杂结构"), 413)):
            with self.subTest(error=error):
                self.release_unity_lock.reset_mock()
                self.load.side_effect = error
                self.assert_error(self.post(), status)
                self.release_unity_lock.assert_called_once()

    def test_temp_directory_creation_failure_releases_lock(self):
        self.mkdtemp.side_effect = OSError("临时目录失败")
        for path in ("/unity/inspect", "/unpack"):
            with self.subTest(path=path):
                self.release_unity_lock.reset_mock()
                self.assert_error(self.post(path), 500)
                self.release_unity_lock.assert_called_once()

    def test_download_preparation_failure_cleans_and_releases(self):
        with patch("blueprints.unity.send_file", side_effect=OSError("下载失败")):
            self.assert_error(self.post(), 500)

    def test_missing_or_zip_upload_are_400(self):
        self.assert_error(self.client.post("/unpack", headers={"Accept": "application/json"}), 400)
        for path in ("/unity/inspect", "/unpack"):
            result = self.client.post(path, data={"bundle": (io.BytesIO(b"PK\x03\x04zip"), "upload.zip")},
                                      headers={"Accept": "application/json"})
            self.assert_error(result, 400)
        self.load.assert_not_called()


class BudgetHelperTests(unittest.TestCase):
    def test_real_file_dictionary_count_rejects_before_yield(self):
        obj = text_object()
        env = SimpleNamespace(files={"cab": SimpleNamespace(objects={1: obj, 2: text_object(2)})})
        with patch.object(limits, "MAX_OBJECTS", 1):
            with self.assertRaises(unity.ClientFacingError):
                next(limits.iter_objects(env))
        obj.read_typetree.assert_not_called()

    def test_nested_file_structure_is_bounded_and_dependencies_are_skipped(self):
        leaf = SimpleNamespace(objects={1: text_object()})
        env = SimpleNamespace(files={"nested": SimpleNamespace(files={"leaf": leaf})})
        with patch.object(limits, "MAX_BUNDLE_DEPTH", 1):
            with self.assertRaises(unity.ClientFacingError):
                list(limits.iter_objects(env))
        with patch.object(limits, "MAX_BUNDLE_FILES", 1):
            with self.assertRaises(unity.ClientFacingError):
                list(limits.iter_objects(env))
        leaf.is_dependency = True
        self.assertEqual(list(limits.iter_objects(env)), [])

    def test_bounded_output_does_not_write_oversized_chunk(self):
        file = io.BytesIO()
        sink = limits.BoundedOutput(file, limits.ExportBudget(), "zip", 4, "ZIP")
        sink.write(b"1234")
        sink.seek(0)
        sink.write(b"12")  # 覆盖头部不重复计入磁盘。
        sink.seek(4)
        with self.assertRaises(unity.ClientFacingError):
            sink.write(b"5")
        self.assertEqual(file.getvalue(), b"1234")

    def test_bounded_output_prevents_file_descriptor_bypass(self):
        with tempfile.TemporaryFile() as file:
            self.assertIsInstance(file.fileno(), int)
            sink = limits.BoundedOutput(file, limits.ExportBudget(), "zip", 4, "ZIP")
            with self.assertRaises(io.UnsupportedOperation):
                sink.fileno()

    def test_member_writer_checks_before_writing_and_counts_utf8(self):
        file = io.BytesIO()
        writer = limits.MemberWriter(file, limits.ExportBudget())
        with patch.object(limits, "TEXT_MAX_BYTES", 3):
            writer.write("中")
            with self.assertRaises(unity.ClientFacingError):
                writer.write("文")
        self.assertEqual(file.getvalue(), "中".encode())

    def test_reused_image_key_increases_budget_if_dimensions_change(self):
        budget = limits.ExportBudget()
        with patch.object(limits, "IMAGE_TOTAL_PIXELS", 8):
            budget.check_image(2, 2, "image")
            budget.check_image(2, 2, "image")
            self.assertEqual(budget.image_pixels, 4)
            with self.assertRaises(unity.ClientFacingError):
                budget.check_image(3, 3, "image")

    def test_sprite_backing_texture_is_checked_before_image_decode(self):
        reader, _ = texture_object(size=(5, 5))
        reader.assets_file = object()
        pointer = Mock()
        pointer.deref.return_value = reader
        data = SimpleNamespace(m_Rect=SimpleNamespace(width=1, height=1), m_SpriteAtlas=None, m_AtlasTags=[],
                               m_RD=SimpleNamespace(texture=pointer, alphaTexture=None,
                                                    textureRect=SimpleNamespace(width=1, height=1)))
        with patch.object(limits, "IMAGE_MAX_PIXELS", 16):
            with self.assertRaises(unity.ClientFacingError) as error:
                unity._check_sprite_for_export(data, limits.ExportBudget(), "sprite")
        self.assertEqual(error.exception.status, 413)

    def test_sprite_atlas_and_alpha_texture_are_budgeted(self):
        texture, _ = texture_object(100)
        alpha, _ = texture_object(101, size=(5, 5))
        texture.assets_file = alpha.assets_file = object()
        texture_pointer, alpha_pointer = Mock(), Mock()
        texture_pointer.deref.return_value = texture
        alpha_pointer.deref.return_value = alpha
        entry = SimpleNamespace(texture=texture_pointer, alphaTexture=alpha_pointer,
                                textureRect=SimpleNamespace(width=1, height=1))
        atlas = text_object(200, size=20)
        atlas.assets_file = object()
        atlas.read.return_value = SimpleNamespace(m_RenderDataMap=[("sprite", entry)])
        pointer = Mock()
        pointer.deref.return_value = atlas
        data = SimpleNamespace(m_Rect=SimpleNamespace(width=1, height=1), m_SpriteAtlas=pointer,
                               m_RenderDataKey="sprite", m_RD=None)
        with patch.object(limits, "IMAGE_MAX_PIXELS", 16):
            with self.assertRaises(unity.ClientFacingError):
                unity._check_sprite_for_export(data, limits.ExportBudget(), "sprite")

    def test_sprite_atlas_lookup_work_is_bounded(self):
        atlas = text_object(200, size=20)
        atlas.assets_file = object()
        atlas.read.return_value = SimpleNamespace(m_RenderDataMap=[("other", None)] * 4)
        pointer = Mock()
        pointer.deref.return_value = atlas
        data = SimpleNamespace(m_Rect=SimpleNamespace(width=1, height=1), m_SpriteAtlas=pointer,
                               m_RenderDataKey="sprite", m_RD=None)
        with patch.object(limits, "MAX_OBJECTS", 3):
            with self.assertRaises(unity.ClientFacingError) as error:
                unity._check_sprite_for_export(data, limits.ExportBudget(), "sprite")
        self.assertEqual(error.exception.status, 413)


class RealBundleExportTests(unittest.TestCase):
    def test_shipped_bundles_inspect_and_recommended_export(self):
        app = Flask(__name__)
        app.testing = True
        app.register_blueprint(unity.unity_bp)
        for name in ("data_assets_44", "recipe_decks_1", "recipe_definitions_1"):
            content = (ROOT / "data" / name).read_bytes()
            with self.subTest(bundle=name), patch("blueprints.unity.cleanup_old_temp"):
                result = app.test_client().post("/unity/inspect", data={"bundle": (io.BytesIO(content), name)})
                result.request.environ["wsgi.input"].close()
                self.assertEqual(result.status_code, 200, result.data)
                expected = len(UnityPy.load(content).objects)
                self.assertEqual(result.json["report"]["total_objects"], expected)
                result.close()
                result = app.test_client().post("/unpack", data={"bundle": (io.BytesIO(content), name)},
                                                headers={"Accept": "application/json"})
                result.request.environ["wsgi.input"].close()
                self.assertEqual(result.status_code, 200, result.data)
                with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
                    summary = json.loads(archive.read("_export_summary.json"))
                    self.assertEqual(summary["failed_count"], 0)
                    self.assertGreater(summary["exported_count"], 100)
                result.close()
                self.assertFalse(UNITY_TASK_LOCK.locked())


if __name__ == "__main__":
    unittest.main()
