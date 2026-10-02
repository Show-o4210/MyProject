"""小文件、低阈值和 mock 覆盖资源预算；不生成大型 ZIP 或访问线上服务。"""

from contextlib import ExitStack
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from flask import Flask
from PIL import Image
import UnityPy

from blueprints import unity
from extensions import UNITY_TASK_LOCK
from utils import patch_limits as limits

ROOT = Path(__file__).resolve().parents[1]


def small_zip(members):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return output.getvalue()


def small_png(size=(2, 2)):
    output = io.BytesIO()
    with Image.new("RGBA", size, (12, 34, 56, 255)) as image:
        image.save(output, "PNG")
    return output.getvalue()


class ZipBudgetTests(unittest.TestCase):
    def metadata(self, names):
        infos = []
        for name, size, compressed in names:
            info = zipfile.ZipInfo(name)
            info.file_size, info.compress_size = size, compressed
            infos.append(info)
        archive = Mock()
        archive.infolist.return_value = infos
        return archive

    def test_larger_text_metadata_is_accepted_without_relaxing_other_formats(self):
        for name, size in (("_index.json", 10 * limits.MIB),
                           ("a.json", 40 * limits.MIB),
                           ("a.csv", 40 * limits.MIB)):
            with self.subTest(name=name):
                archive = self.metadata([(name, size, size)])
                limits.BoundedZipReader(archive)
                archive.open.assert_not_called()
                archive = self.metadata([(name, size + 1, size + 1)])
                with self.assertRaises(limits.ClientFacingError) as caught:
                    limits.BoundedZipReader(archive)
                self.assertEqual(caught.exception.status, 413)
                archive.open.assert_not_called()
        for name, size in (("a.dat", 32 * limits.MIB), ("a.raw", 32 * limits.MIB),
                           ("a.png", 16 * limits.MIB)):
            with self.subTest(name=name):
                archive = self.metadata([(name, size + 1, size + 1)])
                with self.assertRaises(limits.ClientFacingError) as caught:
                    limits.BoundedZipReader(archive)
                self.assertEqual(caught.exception.status, 413)
                archive.open.assert_not_called()

    def test_raw_actual_read_retains_format_cap_below_zip_member_cap(self):
        archive = self.metadata([("a.dat", 1, 1)])
        archive.getinfo.return_value = archive.infolist.return_value[0]
        body = io.BytesIO(b"0123456789")
        archive.open.return_value.__enter__ = Mock(return_value=body)
        archive.open.return_value.__exit__ = Mock(return_value=False)
        with patch.object(limits, "RAW_MAX_BYTES", 5), patch.object(limits, "ZIP_MAX_MEMBER_BYTES", 10):
            reader = limits.BoundedZipReader(archive)
            with self.assertRaises(limits.ClientFacingError) as caught:
                reader.read("a.dat")
        self.assertEqual(caught.exception.status, 413)
        self.assertEqual(body.tell(), 6)

    def test_metadata_rejects_before_any_body_is_opened(self):
        cases = (
            ("ZIP_MAX_ENTRIES", 1, [("a.dat", 1, 1), ("b.dat", 1, 1)]),
            ("ZIP_MAX_NAME_CHARS", 3, [("long.dat", 1, 1)]),
            ("ZIP_MAX_MEMBER_BYTES", 5, [("a.dat", 6, 6)]),
            ("ZIP_MAX_DECLARED_BYTES", 5, [("a.dat", 3, 3), ("b.dat", 3, 3)]),
            ("ZIP_MAX_COMPRESSION_RATIO", 2, [("a.dat", 5, 2)]),
            ("INDEX_MAX_BYTES", 5, [("_index.json", 6, 6)]),
            ("JSON_MAX_BYTES", 5, [("a.json", 6, 6)]),
            ("CSV_MAX_BYTES", 5, [("a.csv", 6, 6)]),
            ("PNG_MAX_BYTES", 5, [("a.png", 6, 6)]),
        )
        for setting, value, entries in cases:
            with self.subTest(setting=setting), patch.object(limits, setting, value):
                archive = self.metadata(entries)
                with self.assertRaises(limits.ClientFacingError) as caught:
                    limits.BoundedZipReader(archive)
                self.assertEqual(caught.exception.status, 413)
                archive.open.assert_not_called()

    def test_directory_limits_precede_zipfile_allocation(self):
        content = small_zip({"a.dat": b"a", "b.dat": b"b"})
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "patch.zip"
            path.write_bytes(content)
            for setting, value in (("ZIP_MAX_ENTRIES", 1), ("ZIP_MAX_DIRECTORY_BYTES", 1)):
                with self.subTest(setting=setting), patch.object(limits, setting, value):
                    with patch.object(limits.zipfile, "ZipFile") as constructor:
                        with self.assertRaises(limits.ClientFacingError) as caught:
                            with limits.open_patch_zip(path):
                                self.fail("不应打开 ZIP")
                        self.assertEqual(caught.exception.status, 413)
                        constructor.assert_not_called()

    def test_actual_member_budget_stops_chunked_read_of_underdeclared_data(self):
        archive = self.metadata([("a.dat", 1, 1)])
        archive.getinfo.return_value = archive.infolist.return_value[0]
        body = io.BytesIO(b"0123456789")
        stream = Mock(wraps=body)
        archive.open.return_value.__enter__ = Mock(return_value=stream)
        archive.open.return_value.__exit__ = Mock(return_value=False)
        with patch.object(limits, "ZIP_MAX_MEMBER_BYTES", 5), patch.object(limits, "READ_CHUNK_BYTES", 3):
            reader = limits.BoundedZipReader(archive)
            with self.assertRaises(limits.ClientFacingError) as caught:
                reader.read("a.dat")
        self.assertEqual(caught.exception.status, 413)
        self.assertEqual(body.tell(), 6)
        self.assertEqual(reader.total_read, 6)
        self.assertEqual([call.args[0] for call in stream.read.call_args_list], [3, 3])

    def test_actual_total_budget_counts_repeated_reads(self):
        content = small_zip({"a.dat": b"abc"})
        with zipfile.ZipFile(io.BytesIO(content)) as zf, patch.object(limits, "ZIP_MAX_READ_BYTES", 5):
            reader = limits.BoundedZipReader(zf)
            self.assertEqual(reader.read("a.dat"), b"abc")
            with self.assertRaises(limits.ClientFacingError) as caught:
                reader.read("a.dat")
            self.assertEqual(caught.exception.status, 413)
            self.assertEqual(reader.total_read, 6)

    def test_exact_actual_budget_is_accepted(self):
        content = small_zip({"a.dat": b"abc"})
        with zipfile.ZipFile(io.BytesIO(content)) as zf, patch.object(limits, "ZIP_MAX_READ_BYTES", 3):
            reader = limits.BoundedZipReader(zf)
            self.assertEqual(reader.read("a.dat"), b"abc")
            self.assertEqual(reader.total_read, 3)

    def test_json_depth_is_rejected_before_parsing(self):
        with patch.object(limits, "JSON_MAX_DEPTH", 2), patch.object(limits.json, "loads") as parse:
            with self.assertRaises(limits.ClientFacingError) as caught:
                limits.load_patch_json('{"x": [[[0]]]}', "补丁")
            self.assertEqual(caught.exception.status, 413)
            parse.assert_not_called()

    def test_json_structure_size_is_bounded(self):
        with patch.object(limits, "JSON_MAX_NODES", 3):
            with self.assertRaises(limits.ClientFacingError) as caught:
                limits.load_patch_json('{"a": 1, "b": 2, "c": 3}', "补丁")
            self.assertEqual(caught.exception.status, 413)

    def test_json5_scanner_ignores_quoted_brackets_and_comments(self):
        text = "{name: '[{}]', /* [[[ */ count: 2, note: 'it\\'s okay'}"
        with patch.object(limits, "JSON_MAX_DEPTH", 1):
            self.assertEqual(limits.load_patch_json(text, "补丁")["count"], 2)

    def test_json5_fallback_has_a_smaller_byte_budget(self):
        with patch.object(limits, "JSON5_MAX_BYTES", 8):
            with self.assertRaises(limits.ClientFacingError) as caught:
                limits.load_patch_json("{value: 'nonstandard JSON'}", "补丁")
            self.assertEqual(caught.exception.status, 413)
            self.assertEqual(limits.load_patch_json('{"value": "standard JSON"}', "补丁")["value"], "standard JSON")

    def test_legacy_trailing_commas_use_standard_json_budget(self):
        text = '{"items": [{"a": 1,}, 2,],}'
        with patch.object(limits, "JSON5_MAX_BYTES", 8), patch.object(limits.json5, "loads") as json5_parse:
            self.assertEqual(limits.load_patch_json(text, "补丁"), {"items": [{"a": 1}, 2]})
            json5_parse.assert_not_called()

    def test_trailing_comma_compat_preserves_strings_and_escaped_quotes(self):
        expected = {"text": 'literal ,] and ,} and \\"quoted\\" and \\\\', "items": [1, 2]}
        text = json.dumps(expected, ensure_ascii=False)[:-1] + ',\n}'
        with patch.object(limits.json5, "loads") as json5_parse:
            self.assertEqual(limits.load_patch_json(text, "补丁"), expected)
            json5_parse.assert_not_called()

    def test_nonstandard_json5_still_parses_original_strings_and_comments(self):
        text = "{message: ',}', values: [1,], /* ,} */}"
        self.assertEqual(limits.load_patch_json(text, "补丁"), {"message": ',}', "values": [1]})

    def test_trailing_commas_do_not_bypass_structure_and_byte_limits(self):
        text = '{"items": [[1,],],}'
        for setting, cap in (("JSON_MAX_DEPTH", 2), ("JSON_MAX_NODES", 3), ("JSON_MAX_BYTES", 8)):
            with self.subTest(setting=setting), patch.object(limits, setting, cap), \
                    patch.object(limits, "_strip_json_trailing_commas") as normalize:
                with self.assertRaises(limits.ClientFacingError) as caught:
                    limits.load_patch_json(text, "补丁")
                self.assertEqual(caught.exception.status, 413)
                normalize.assert_not_called()

    def test_other_malformed_json_is_still_rejected(self):
        for text in ('{"a": 1,,}', '[,]', '{"a":,}', '[1,,]'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                limits.load_patch_json(text, "补丁")

    def test_pillow_protection_is_retained(self):
        raw = small_png()
        with patch.object(Image, "MAX_IMAGE_PIXELS", 2):
            with self.assertRaises(limits.ClientFacingError) as caught:
                limits.open_patch_image(raw)
            self.assertEqual(caught.exception.status, 413)
            self.assertEqual(Image.MAX_IMAGE_PIXELS, 2)


class RepackRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workdirs = []
        original_mkdtemp = tempfile.mkdtemp

        def create_workdir(**kwargs):
            path = original_mkdtemp(dir=self.temp.name, **kwargs)
            self.workdirs.append(Path(path))
            return path

        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(unity.tempfile, "mkdtemp", side_effect=create_workdir))
        self.stack.enter_context(patch.object(unity, "cleanup_old_temp"))
        self.app = Flask(__name__, template_folder=str(ROOT / "templates"))
        self.app.testing = True
        self.app.config["MAX_CONTENT_LENGTH"] = 150 * limits.MIB
        self.app.register_blueprint(unity.unity_bp)
        self.client = self.app.test_client()
        self.obj = Mock()
        self.obj.path_id = 123
        self.obj.type = SimpleNamespace(name="MonoBehaviour")
        self.env = SimpleNamespace(objects=[self.obj], file=Mock())
        self.env.file.save.return_value = b"modified bundle"
        self.loader = self.stack.enter_context(patch.object(unity.UnityPy, "load", return_value=self.env))

    def post(self, members, original=b"original bundle", headers=None, **fields):
        response = self.client.post(
            "/repack", data={
                "original_bundle": (io.BytesIO(original), "original.bundle"),
                "modified_zip": (io.BytesIO(members if isinstance(members, bytes) else small_zip(members)), "patch.zip"),
                **fields,
            }, headers=headers or {"X-Requested-With": "fetch"},
        )
        self.addCleanup(response.close)
        return response

    def assert_rejected_and_cleaned(self, response, status=413):
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        self.assertFalse(response.get_json()["success"])
        self.assertTrue(response.get_json()["error"])
        self.assertTrue(self.workdirs)
        self.assertTrue(all(not path.exists() for path in self.workdirs))
        self.assertFalse(UNITY_TASK_LOCK.locked())
        self.env.file.save.assert_not_called()

    def test_normal_json_repack_is_independent_of_removed_validation(self):
        response = self.post({"Card_123.json": '{"m_Name": "修改后"}'}, require_validate="true", validate_level="full")
        self.assertEqual(response.status_code, 200)
        self.obj.save_typetree.assert_called_once_with({"m_Name": "修改后"})
        self.assertEqual(response.data, b"modified bundle")
        self.assertIn("modded_original.bundle", response.headers["Content-Disposition"])
        response.close()
        self.assertTrue(all(not path.exists() for path in self.workdirs))
        self.assertFalse(UNITY_TASK_LOCK.locked())

    def test_normal_csv_repack(self):
        response = self.post({"Card_123.csv": "m_Name,修改后\n"})
        self.assertEqual(response.status_code, 200)
        self.obj.save_typetree.assert_called_once_with({"m_Name": "修改后"})

    def test_csv_scalar_types_roundtrip_without_guessing_strings(self):
        tree = {"count": 2, "ratio": 1.5, "enabled": True, "name": "123"}
        text = unity.FormatManager.to_csv(tree).decode("utf-8-sig")
        self.assertEqual(unity.FormatManager.from_csv(text, original_tree=tree), tree)

    def test_normal_json5_repack(self):
        response = self.post({"Card_123.json5": "{m_Name: '修改后',}"})
        self.assertEqual(response.status_code, 200)
        self.obj.save_typetree.assert_called_once_with({"m_Name": "修改后"})

    def test_normal_png_repack(self):
        self.obj.type.name = "Texture2D"
        saved_images = []
        data = self.obj.read.return_value
        data.save.side_effect = lambda: saved_images.append(data.image.copy())
        response = self.post({"Image_123.png": small_png()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(saved_images[0].mode, "RGBA")
        self.assertEqual(saved_images[0].getpixel((0, 0)), (12, 34, 56, 255))
        saved_images[0].close()
        data.save.assert_called_once()

    def test_normal_dat_and_raw_repack(self):
        for extension in ("dat", "raw"):
            with self.subTest(extension=extension):
                self.obj.reset_mock()
                response = self.post({f"Object_123.{extension}": b"\x00\x01\x02"})
                self.assertEqual(response.status_code, 200)
                self.obj.set_raw_data.assert_called_once_with(b"\x00\x01\x02")
                response.close()

    def test_index_matching_preserves_renamed_patch(self):
        response = self.post({"_index.json": '{"123": "folder/renamed.json"}', "folder/renamed.json": '{"m_Name": "renamed"}'})
        self.assertEqual(response.status_code, 200)
        self.obj.save_typetree.assert_called_once_with({"m_Name": "renamed"})

    def test_unmatched_members_are_never_read(self):
        original_open = zipfile.ZipFile.open
        opened = []

        def track_open(zf, name, *args, **kwargs):
            opened.append(name.filename if isinstance(name, zipfile.ZipInfo) else name)
            return original_open(zf, name, *args, **kwargs)

        content = small_zip({"Card_123.json": '{"m_Name": "ok"}', "unmatched.json": "not JSON"})
        with patch.object(zipfile.ZipFile, "open", track_open):
            response = self.post(content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(opened, ["Card_123.json"])

    def test_metadata_and_index_rejections_clean_up_and_unlock(self):
        cases = (
            ("ZIP_MAX_ENTRIES", 1, {"a.dat": b"a", "b.dat": b"b"}),
            ("ZIP_MAX_MEMBER_BYTES", 2, {"a.dat": b"abc"}),
            ("ZIP_MAX_DECLARED_BYTES", 3, {"a.dat": b"ab", "b.dat": b"ab"}),
            ("ZIP_MAX_COMPRESSION_RATIO", 0, {"a.dat": b"a"}),
            ("INDEX_MAX_BYTES", 2, {"_index.json": b"{} "}),
        )
        for setting, value, members in cases:
            content = small_zip(members)
            with self.subTest(setting=setting), patch.object(limits, setting, value):
                with patch.object(zipfile.ZipFile, "open", side_effect=AssertionError("不得读正文")):
                    response = self.post(content)
                self.assert_rejected_and_cleaned(response)
                self.loader.assert_not_called()

    def test_actual_total_limit_aborts_before_later_members(self):
        second = Mock(path_id=124, type=SimpleNamespace(name="MonoBehaviour"))
        third = Mock(path_id=125, type=SimpleNamespace(name="MonoBehaviour"))
        self.env.objects.extend([second, third])
        with patch.object(limits, "ZIP_MAX_READ_BYTES", 5):
            response = self.post({"a_123.dat": b"abc", "b_124.dat": b"def", "c_125.dat": b"ghi"})
        self.assert_rejected_and_cleaned(response)
        self.obj.set_raw_data.assert_called_once_with(b"abc")
        second.set_raw_data.assert_not_called()
        third.set_raw_data.assert_not_called()

    def test_image_limits_precede_rgba_conversion(self):
        self.obj.type.name = "Texture2D"
        raw = small_png((4, 4))
        for setting, value in (("IMAGE_MAX_PIXELS", 15), ("IMAGE_MAX_SIDE", 3)):
            with self.subTest(setting=setting), patch.object(limits, setting, value):
                with patch.object(Image.Image, "convert", side_effect=AssertionError("不得展开 RGBA")):
                    response = self.post({"Image_123.png": raw})
                self.assert_rejected_and_cleaned(response)
                self.obj.read.assert_not_called()

    def test_csv_row_column_and_field_limits_return_413(self):
        for setting, value, text in (
            ("CSV_MAX_ROWS", 1, "m_Name,a\nx,b\n"),
            ("CSV_MAX_COLUMNS", 2, "m_Name,a,b\n"),
            ("CSV_MAX_FIELD_CHARS", 2, "x,abc\n"),
        ):
            with self.subTest(setting=setting), patch.object(limits, setting, value):
                self.assert_rejected_and_cleaned(self.post({"Card_123.csv": text}))

    def test_total_image_pixel_limit_aborts_before_second_decode(self):
        self.obj.type.name = "Texture2D"
        second = Mock(path_id=124, type=SimpleNamespace(name="Texture2D"))
        self.env.objects.append(second)
        with patch.object(limits, "IMAGE_MAX_TOTAL_PIXELS", 7):
            response = self.post({"a_123.png": small_png(), "b_124.png": small_png()})
        self.assert_rejected_and_cleaned(response)
        self.obj.read.assert_called_once()
        second.read.assert_not_called()

    def test_embedded_json_depth_cannot_bypass_budget(self):
        text = json.dumps({"m_Name": "ok", "m_Script": '{"x": [[[1]]]} '})
        with patch.object(limits, "JSON_MAX_DEPTH", 2):
            self.assert_rejected_and_cleaned(self.post({"Card_123.json": text}))

    def test_invalid_input_returns_chinese_400_and_cleans_up(self):
        self.assert_rejected_and_cleaned(self.post({"Card_123.json": "not JSON"}), status=400)

    def test_original_zip_cannot_bypass_patch_budgets_via_unitypy(self):
        response = self.post({"Object_123.dat": b"abc"}, original=small_zip({"data.dat": b"abc"}))
        self.assert_rejected_and_cleaned(response, status=400)
        self.loader.assert_not_called()

    def test_flask_upload_limit_remains_a_413_with_cleanup_and_unlock(self):
        self.app.config["MAX_CONTENT_LENGTH"] = 64
        self.assert_rejected_and_cleaned(self.post({"Object_123.dat": b"abc"}))
        self.loader.assert_not_called()

    def test_plain_form_receives_chinese_413_error_page(self):
        with patch.object(limits, "ZIP_MAX_MEMBER_BYTES", 2):
            response = self.post({"Object_123.dat": b"abc"}, headers={"Accept": "text/html"})
        self.assertEqual(response.status_code, 413)
        self.assertIn("声明解压大小", response.get_data(as_text=True))
        self.assertTrue(all(not path.exists() for path in self.workdirs))
        self.assertFalse(UNITY_TASK_LOCK.locked())

    def test_removed_validation_route_and_frontend(self):
        self.assertEqual(self.client.post("/unity/validate-repack").status_code, 404)
        response = self.client.get("/unity")
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("保留原始 Bundle 备份", text)
        self.assertIn('action="/repack"', text)
        for obsolete in ("validate-repack", "require_validate", "validateLevel", "validationReport", "预检"):
            self.assertNotIn(obsolete, text)

    def test_memory_failure_does_not_retry_full_bundle_save(self):
        self.env.file.save.side_effect = MemoryError("内存不足")
        response = self.post({"Object_123.dat": b"abc"})
        self.assertEqual(response.status_code, 507)
        self.env.file.save.assert_called_once()
        self.assertTrue(all(not path.exists() for path in self.workdirs))
        self.assertFalse(UNITY_TASK_LOCK.locked())


class RealBundleRepackTests(unittest.TestCase):
    def test_real_bundle_json_csv_and_dat_roundtrips(self):
        # 使用项目已有的 23 KiB 底包，不修改磁盘原件；验证真实 UnityPy load/save。
        source = (ROOT / "data" / "recipe_decks_1").read_bytes()
        original = UnityPy.load(source)
        obj = next(obj for obj in original.objects if obj.type.name == "MonoBehaviour")
        tree = obj.read_typetree()
        tree["m_Name"] = "SecurityBudgetRoundtrip"
        cases = (
            ("json", json.dumps(tree, ensure_ascii=False).encode("utf-8"), "SecurityBudgetRoundtrip"),
            ("csv", unity.FormatManager.to_csv(tree), "SecurityBudgetRoundtrip"),
            ("dat", obj.get_raw_data(), obj.read_typetree()["m_Name"]),
        )
        app = Flask(__name__, template_folder=str(ROOT / "templates"))
        app.testing = True
        app.register_blueprint(unity.unity_bp)
        for extension, body, expected_name in cases:
            with self.subTest(extension=extension), patch.object(unity, "cleanup_old_temp"):
                name = f"object.{extension}"
                response = app.test_client().post("/repack", data={
                    "original_bundle": (io.BytesIO(source), "source.bundle"),
                    "modified_zip": (io.BytesIO(small_zip({
                        "_index.json": json.dumps({str(obj.path_id): name}), name: body,
                    })), "patch.zip"),
                }, headers={"X-Requested-With": "fetch"})
                try:
                    self.assertEqual(response.status_code, 200, response.data[:500])
                    result = UnityPy.load(response.data)
                    modified = next(item for item in result.objects if item.path_id == obj.path_id)
                    self.assertEqual(modified.read_typetree()["m_Name"], expected_name)
                    self.assertFalse(UNITY_TASK_LOCK.locked())
                finally:
                    response.close()


if __name__ == "__main__":
    unittest.main()
