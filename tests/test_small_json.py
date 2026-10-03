"""关卡 JSON 接口回归：低阈值、WSGI 请求流、Unity mock 和真实底包。"""

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask, request
import UnityPy

from blueprints import level_editor
from extensions import UNITY_TASK_LOCK
from utils import json_requests as limits


PACK = "/api/editor/ab/pack"
EXTRACT = "/api/editor/ab/extract"


def test_app(blueprint):
    app = Flask(__name__)
    app.testing = True
    app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024
    limits.init_small_json_limits(app)
    app.register_blueprint(blueprint)
    return app


class LevelRequestTests(unittest.TestCase):
    def setUp(self):
        self.app = test_app(level_editor.level_editor_bp)
        self.client = self.app.test_client()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workdirs = []
        real_mkdtemp = tempfile.mkdtemp

        def make_dir(**kwargs):
            path = real_mkdtemp(dir=self.temp.name, **kwargs)
            self.workdirs.append(Path(path))
            return path

        for name, kwargs in (
            ("acquire_unity_lock", {"wraps": level_editor.acquire_unity_lock}),
            ("release_unity_lock", {"wraps": level_editor.release_unity_lock}),
            ("tempfile.mkdtemp", {"side_effect": make_dir}),
            ("logic.pack_level_config", {"side_effect": self.write_bundle}),
            ("logic.load_level_config", {"return_value": {"BoardConfig": {}}}),
        ):
            patcher = patch("blueprints.level_editor." + name, **kwargs)
            mocked = patcher.start()
            self.addCleanup(patcher.stop)
            setattr(self, name.split(".")[-1], mocked)
        self.assertFalse(UNITY_TASK_LOCK.locked())

    def write_bundle(self, level_id, config_text, output_path):
        self.assertTrue(UNITY_TASK_LOCK.locked())
        self.assertIsInstance(config_text, str)
        Path(output_path).write_bytes(b"bundle")

    def post(self, config=None, **kwargs):
        if not kwargs:
            kwargs["json"] = {"level_id": "valid", "config": config or {"BoardConfig": {}}}
        return self.client.post(PACK, **kwargs)

    def assert_invalid(self, result, status):
        self.assertEqual(result.status_code, status, result.data)
        self.acquire_unity_lock.assert_not_called()
        self.release_unity_lock.assert_not_called()
        self.pack_level_config.assert_not_called()
        self.load_level_config.assert_not_called()
        self.mkdtemp.assert_not_called()
        self.assertFalse(UNITY_TASK_LOCK.locked())
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_global_upload_limit_is_unchanged(self):
        self.app.add_url_rule("/upload", "upload", lambda: request.get_data(),
                              methods=["POST"])
        with patch.dict(limits.JSON_BODY_LIMITS, {"level_editor.pack_level": 64}):
            result = self.client.post("/upload", data=b"x" * 1024)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.data), 1024)
        self.assertEqual(self.app.config["MAX_CONTENT_LENGTH"], 150 * 1024 * 1024)

    def test_oversized_body_before_parse_load_or_lock(self):
        with patch.dict(limits.JSON_BODY_LIMITS, {"level_editor.pack_level": 64}), \
                patch("logic_level_editor.UnityPy.load") as load, \
                patch.object(self.app.json, "loads", wraps=self.app.json.loads) as parse:
            result = self.post(data=b" " * 65, content_type="application/json")
            self.assert_invalid(result, 413)
            load.assert_not_called()
            parse.assert_not_called()

    def test_stream_limit_without_content_length(self):
        stream = io.BytesIO(b" " * 65)
        with patch.dict(limits.JSON_BODY_LIMITS, {"level_editor.pack_level": 64}):
            result = self.post(content_type="application/json", environ_overrides={
                "wsgi.input": stream, "wsgi.input_terminated": True, "CONTENT_LENGTH": "",
            })
            self.assert_invalid(result, 413)
            self.assertLessEqual(stream.tell(), 64)

    def test_stream_valid_json_prefix_cannot_hide_oversized_tail(self):
        body = b'{"level_id":"valid","config":{"a":1}}'
        stream = io.BytesIO(body + b" " * 100)
        with patch.dict(limits.JSON_BODY_LIMITS, {"level_editor.pack_level": len(body)}):
            self.assert_invalid(self.post(content_type="application/json", environ_overrides={
                "wsgi.input": stream, "wsgi.input_terminated": True, "CONTENT_LENGTH": "",
            }), 413)
            self.assertEqual(stream.tell(), len(body))

    def test_config_must_be_nonempty_object(self):
        for config in ([], "text", 1, None, {}):
            with self.subTest(config=config):
                self.assert_invalid(self.post(json={"level_id": "valid", "config": config}), 400)

    def test_missing_parameters_bad_json_and_media_type_are_400(self):
        self.assert_invalid(self.post(json={}), 400)
        self.assert_invalid(self.post(data=b"{", content_type="application/json"), 400)
        self.assert_invalid(self.post(data=b"{}", content_type="text/plain"), 400)

    def test_level_id_must_be_bounded_string(self):
        for value in (None, [], {}, 1, True, "", " ", "x" * 129):
            with self.subTest(value=value):
                self.assert_invalid(self.post(json={"level_id": value, "config": {"a": 1}}), 400)

    def test_config_depth(self):
        with patch.object(limits, "CONFIG_MAX_DEPTH", 2):
            self.assert_invalid(self.post({"a": {"b": 1}}), 413)

    def test_parser_recursion_limit_returns_413(self):
        # 小于 5 KiB，触发解析器递归边界，而非生成巨型 JSON。
        body = b'{"level_id":"valid","config":{"a":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}}"
        self.assert_invalid(self.post(data=body, content_type="application/json"), 413)

    def test_config_nodes(self):
        with patch.object(limits, "CONFIG_MAX_NODES", 5):
            self.assert_invalid(self.post({"a": [1, 2, 3, 4]}), 413)

    def test_config_string_values_and_keys(self):
        for config in ({"a": "abcd"}, {"abcd": 1}):
            with self.subTest(config=config), patch.object(limits, "CONFIG_MAX_STRING_LENGTH", 3):
                self.assert_invalid(self.post(config), 413)

    def test_serialized_utf8_budget_before_lock(self):
        with patch.object(limits, "CONFIG_MAX_SERIALIZED_BYTES", 16):
            self.assert_invalid(self.post({"a": "中文中文"}), 413)

    def test_nonfinite_numbers_and_invalid_unicode_are_400(self):
        for text in ('{"a":NaN}', '{"a":1e400}', '{"a":"\\ud800"}'):
            with self.subTest(text=text):
                body = '{"level_id":"valid","config":' + text + '}'
                self.assert_invalid(self.post(data=body, content_type="application/json"), 400)

    def test_valid_request_acquires_releases_and_cleans_download(self):
        result = self.post()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data, b"bundle")
        self.assertIn("attachment", result.headers["Content-Disposition"])
        self.acquire_unity_lock.assert_called_once_with(json_response=True)
        self.release_unity_lock.assert_called_once()
        self.assertFalse(UNITY_TASK_LOCK.locked())
        self.assertTrue(self.workdirs[0].exists())
        result.close()
        self.assertFalse(self.workdirs[0].exists())

    def test_pack_failures_cleanup_and_release_once(self):
        for error, status in ((ValueError("未找到关卡"), 400), (RuntimeError("保存失败"), 500)):
            with self.subTest(error=error):
                self.pack_level_config.side_effect = error
                self.release_unity_lock.reset_mock()
                result = self.post()
                self.assertEqual(result.status_code, status)
                self.release_unity_lock.assert_called_once()
                self.assertFalse(UNITY_TASK_LOCK.locked())
                self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_temp_creation_failure_still_releases_lock(self):
        self.mkdtemp.side_effect = OSError("临时目录创建失败")
        self.assertEqual(self.post().status_code, 500)
        self.release_unity_lock.assert_called_once()
        self.assertFalse(UNITY_TASK_LOCK.locked())

    def test_download_setup_failure_cleans_directory_and_releases_lock(self):
        with patch("blueprints.level_editor.send_file", side_effect=OSError("下载失败")):
            self.assertEqual(self.post().status_code, 500)
        self.release_unity_lock.assert_called_once()
        self.assertFalse(UNITY_TASK_LOCK.locked())
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_busy_lock_does_not_create_directory_or_release_another_task(self):
        self.acquire_unity_lock.return_value = ({"code": "UNITY_BUSY"}, 429)
        self.acquire_unity_lock.side_effect = None
        self.assertEqual(self.post().status_code, 429)
        self.release_unity_lock.assert_not_called()
        self.mkdtemp.assert_not_called()
        self.pack_level_config.assert_not_called()

    def test_extract_body_limit_and_invalid_id_precede_lock(self):
        with patch.dict(limits.JSON_BODY_LIMITS, {"level_editor.extract_level": 32}):
            result = self.client.post(EXTRACT, data=b" " * 33, content_type="application/json")
            self.assert_invalid(result, 413)
        self.assert_invalid(self.client.post(EXTRACT, json={"level_id": []}), 400)

    def test_valid_extract_acquires_and_releases_lock(self):
        result = self.client.post(EXTRACT, json={"level_id": "valid"})
        self.assertEqual(result.status_code, 200)
        self.load_level_config.assert_called_once_with("valid")
        self.acquire_unity_lock.assert_called_once()
        self.release_unity_lock.assert_called_once()
        self.assertFalse(UNITY_TASK_LOCK.locked())

    def test_extract_failure_releases_lock(self):
        self.load_level_config.side_effect = ValueError("未找到关卡")
        self.assertEqual(self.client.post(EXTRACT, json={"level_id": "missing"}).status_code, 400)
        self.release_unity_lock.assert_called_once()
        self.assertFalse(UNITY_TASK_LOCK.locked())


class RealLevelCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.configs = []
        env = UnityPy.load(level_editor.logic.input_ab_path)
        for obj in env.objects:
            if obj.type.name != "TextAsset":
                continue
            asset = obj.read()
            text = level_editor.logic._get_text(asset)
            if '"PlayerConfig"' in text and '"BoardConfig"' in text:
                cls.configs.append((level_editor.logic._get_name(asset), json.loads(text)))

    def test_all_shipped_level_configs_fit_default_budgets(self):
        self.assertGreater(len(self.configs), 0)
        for level_id, config in self.configs:
            with self.subTest(level_id=level_id):
                limits.validate_level_id({"level_id": level_id})
                limits.serialize_level_config(config)
                body = json.dumps({"level_id": level_id, "config": config}, ensure_ascii=False).encode()
                self.assertLess(len(body), limits.JSON_BODY_LIMITS["level_editor.pack_level"])

    def test_real_largest_config_pack_uses_one_load_and_roundtrips(self):
        level_id, config = max(self.configs, key=lambda item: len(json.dumps(item[1])))
        app = test_app(level_editor.level_editor_bp)
        with patch("logic_level_editor.UnityPy.load", wraps=UnityPy.load) as load, \
                patch("blueprints.level_editor.release_unity_lock",
                      wraps=level_editor.release_unity_lock) as release:
            result = app.test_client().post(PACK, json={"level_id": level_id, "config": config})
            self.assertEqual(result.status_code, 200)
            load.assert_called_once_with(level_editor.logic.input_ab_path)
            release.assert_called_once()
            self.assertFalse(UNITY_TASK_LOCK.locked())
            output = result.data
            result.close()
        env = UnityPy.load(output)
        for obj in env.objects:
            if obj.type.name == "TextAsset":
                asset = obj.read()
                if level_editor.logic._get_name(asset) == level_id:
                    self.assertEqual(json.loads(level_editor.logic._get_text(asset)), config)
                    break
        else:
            self.fail("输出 Bundle 缺失关卡")


if __name__ == "__main__":
    unittest.main()
