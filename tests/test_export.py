"""文本导出预算回归：小 Bundle、低阈值与 mock，不访问线上服务。"""

import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from flask import Flask

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
        # 下载流关闭后清理原 Bundle 与导出 ZIP。
        self.assertEqual({p.name for p in self.workdirs[-1].iterdir()}, {"input.bundle", "output.zip"})
        response.close()
        self.assertFalse(self.workdirs[-1].exists())
        return archive


    def test_inspection_removed_without_loading_bundle(self):
        self.assertEqual(self.post("/unity/inspect").status_code, 404)
        self.assertFalse(UNITY_TASK_LOCK.locked())
        self.assertFalse(self.workdirs)
        self.load.assert_not_called()

    def test_frontend_only_offers_export_and_repack(self):
        template = (ROOT / "templates" / "tab_unity.html").read_text(encoding="utf-8")
        for dead_code in ("inspectBundle", "inspectReport", "inspectFile", "结构检查", "inspectDepth", "inspect_depth", "value=\"deep\"", "深度检查", "__all__", "'AudioClip'"):
            self.assertNotIn(dead_code, template)
        self.assertFalse(hasattr(unity, "inspect_env"))
        self.assertFalse(hasattr(unity, "get_object_display_name"))
        response = self.client.get("/unity")
        self.assertEqual(response.status_code, 200)
        rendered = response.get_data(as_text=True)
        for obsolete in ("exportTypeOptions", "unpackPresets", "includeImages", "selectedTypes", "高级设置", "图片模式", "导出方案"):
            self.assertNotIn(obsolete, rendered)
        self.assertIn('type="radio" name="format" value="csv"', rendered)


    def test_json_export_has_expanded_text_and_index(self):
        with self.read_zip(self.post()) as archive:
            tree = json.loads(archive.read("TextAsset/small_1.json"))
            self.assertEqual(tree["m_Script"], {"value": 1})
            self.assertEqual(json.loads(archive.read("_index.json")), {"1": "TextAsset/small_1.json"})
        self.obj.read_typetree.assert_called_once()

    def test_csv_export_and_manual_mode(self):
        with self.read_zip(self.post(format="csv", mode="manual")) as archive:
            content = archive.read("TextAsset/small_1.csv").decode("utf-8-sig")
            self.assertIn("m_Name,small", content)
            self.assertIn("value", content)
            self.assertEqual(json.loads(archive.read("_index.json")), {"1": "TextAsset/small_1.csv"})


    def test_non_text_objects_are_never_read(self):
        unsupported = [text_object(i + 2, type_name=name) for i, name in enumerate(
            ("AudioClip", "Texture2D", "Sprite", "GameObject", "Material", "AnimationClip"))]
        self.env.objects.extend(unsupported)
        with self.read_zip(self.post()) as archive:
            self.assertEqual(set(archive.namelist()), {"TextAsset/small_1.json", "_index.json", "_export_summary.json"})
        for obj in unsupported:
            obj.read.assert_not_called()
            obj.read_typetree.assert_not_called()


    def test_removed_options_and_invalid_format_mode_reject_before_load(self):
        cases = [{"preset": value} for value in ("recommended", "patch", "images", "advanced")]
        cases += [{"types": "Texture2D"}, {"include_images": "1"}, {"include_index": "0"},
                  {"format": "raw"}, {"format": "png"}, {"mode": "unknown"}]
        for fields in cases:
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
            self.assert_error(self.post(format="csv"))

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


    def test_zip_size_budget_aborts_during_compressed_write(self):
        with patch.object(limits, "ZIP_MAX_BYTES", 32):
            self.assert_error(self.post())

    def test_zip_central_directory_is_also_bounded(self):
        with self.read_zip(self.post()) as archive:
            start_of_directory = archive.start_dir
        with patch.object(limits, "ZIP_MAX_BYTES", start_of_directory):
            self.assert_error(self.post())

    def test_failure_paths_cleanup_and_release_once(self):
        for error, status in ((RuntimeError("读取失败"), 500), (RecursionError("复杂结构"), 413)):
            with self.subTest(error=error):
                self.release_unity_lock.reset_mock()
                self.load.side_effect = error
                self.assert_error(self.post(), status)
                self.release_unity_lock.assert_called_once()

    def test_temp_directory_creation_failure_releases_lock(self):
        self.mkdtemp.side_effect = OSError("临时目录失败")
        for path in ("/unpack",):
            with self.subTest(path=path):
                self.release_unity_lock.reset_mock()
                self.assert_error(self.post(path), 500)
                self.release_unity_lock.assert_called_once()

    def test_download_preparation_failure_cleans_and_releases(self):
        with patch("blueprints.unity.send_file", side_effect=OSError("下载失败")):
            self.assert_error(self.post(), 500)

    def test_missing_or_zip_upload_are_400(self):
        self.assert_error(self.client.post("/unpack", headers={"Accept": "application/json"}), 400)
        for path in ("/unpack",):
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


class RealBundleExportTests(unittest.TestCase):
    def test_shipped_bundles_json_csv_export(self):
        app = Flask(__name__)
        app.testing = True
        app.register_blueprint(unity.unity_bp)
        for name in ("data_assets_44", "recipe_decks_1", "recipe_definitions_1"):
            content = (ROOT / "data" / name).read_bytes()
            with self.subTest(bundle=name), patch("blueprints.unity.cleanup_old_temp"):
                for fmt in ("json", "csv"):
                    with self.subTest(format=fmt):
                        result = app.test_client().post("/unpack", data={"bundle": (io.BytesIO(content), name), "format": fmt},
                                                        headers={"Accept": "application/json"})
                        result.request.environ["wsgi.input"].close()
                        try:
                            self.assertEqual(result.status_code, 200, result.data)
                            with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
                                summary = json.loads(archive.read("_export_summary.json"))
                                self.assertEqual(summary["failed_count"], 0)
                                self.assertGreater(summary["exported_count"], 100)
                                self.assertEqual(summary["format"], fmt)
                                index = json.loads(archive.read("_index.json"))
                                self.assertTrue(all(path.endswith("." + fmt) for path in index.values()))
                        finally:
                            result.close()
                        self.assertFalse(UNITY_TASK_LOCK.locked())


if __name__ == "__main__":
    unittest.main()
