"""Real requested bundle: HTTP export → edit ZIP → isolated repack → reload."""
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zipfile

from flask import Flask
import UnityPy

from blueprints import unity
from extensions import UNITY_TASK_LOCK
from utils import export_limits, patch_limits

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tests' / 'fixtures' / 'card_data_5'


class CardDataBudgetTests(unittest.TestCase):
    def test_embedded_json_uses_byte_budget_before_expansion(self):
        body = json.dumps({'name': '卡牌'}, ensure_ascii=False)
        policy = {'target_format': 'json', 'process_mode': 'auto'}
        with patch.object(export_limits, 'EMBEDDED_JSON_MAX_BYTES', len(body.encode('utf-8'))):
            tree = unity.prepare_export_tree({'m_Script': body}, policy, export_limits.ExportBudget())
            self.assertEqual(tree['m_Script'], {'name': '卡牌'})
        with patch.object(export_limits, 'EMBEDDED_JSON_MAX_BYTES', len(body.encode('utf-8')) - 1):
            with self.assertRaises(patch_limits.ClientFacingError) as caught:
                unity.prepare_export_tree({'m_Script': body}, policy, export_limits.ExportBudget())
            self.assertEqual(caught.exception.status, 413)

    def test_large_csv_field_and_parser_limit_restored(self):
        previous = csv.field_size_limit()
        tree = {'m_Script': 'x' * (128 * 1024 + 1)}
        self.assertEqual(unity.FormatManager.from_csv(unity.FormatManager.to_csv(tree).decode('utf-8-sig')), tree)
        self.assertEqual(csv.field_size_limit(), previous)
        with patch.object(patch_limits, 'CSV_MAX_FIELD_CHARS', 4):
            with self.assertRaises(patch_limits.ClientFacingError) as caught:
                unity.FormatManager.from_csv('name,12345\n')
            self.assertEqual(caught.exception.status, 413)
        self.assertEqual(csv.field_size_limit(), previous)


@unittest.skipUnless(sys.platform == 'linux', 'Real HTTP Unity jobs require Linux isolation')
class CardDataRoundtripTests(unittest.TestCase):
    def test_all_formats_modes_preserve_cards_and_apply_real_edits(self):
        source = SOURCE.read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        original = UnityPy.load(source)
        text_asset = next(obj for obj in original.objects if obj.type.name == 'TextAsset')
        original_tree = text_asset.read_typetree()
        original_cards = json.loads(original_tree['m_Script'])
        untouched = {obj.path_id: obj.get_raw_data() for obj in original.objects if obj.path_id != text_asset.path_id}
        app = Flask(__name__, template_folder=str(ROOT / 'templates'))
        app.testing = True
        app.register_blueprint(unity.unity_bp)
        client = app.test_client()
        for fmt in ('json', 'csv'):
            for mode in ('auto', 'manual'):
                with self.subTest(format=fmt, mode=mode):
                    exported = client.post('/unpack', data={
                        'bundle': (io.BytesIO(source), 'card_data_5'), 'format': fmt, 'mode': mode,
                    }, headers={'Accept': 'application/json'})
                    try:
                        self.assertEqual(exported.status_code, 200, exported.data[:500])
                        export_bytes = exported.data
                        with zipfile.ZipFile(io.BytesIO(export_bytes)) as archive:
                            members = {name: archive.read(name) for name in archive.namelist()}
                        summary = json.loads(members['_export_summary.json'])
                        self.assertEqual((summary['exported_count'], summary['failed_count']), (1, 0))
                        index = json.loads(members['_index.json'])
                        name = index[str(text_asset.path_id)]
                        text = members[name].decode('utf-8-sig')
                        tree = json.loads(text) if fmt == 'json' else unity.FormatManager.from_csv(text, original_tree)
                        self.assertEqual(tree['m_Script'], original_cards)
                    finally:
                        exported.close()
                        exported.request.environ['wsgi.input'].close()
                    for edited in (False, True):
                        with self.subTest(edited=edited):
                            expected_cards = copy.deepcopy(original_cards)
                            if edited:
                                components = expected_cards['1']['entity']['components']
                                attack = next(item['$data'] for item in components if '.Attack,' in item['$type'])
                                attack['AttackValue']['BaseValue'] += 1
                                tree['m_Script'] = expected_cards
                                members[name] = (json.dumps(tree, ensure_ascii=False).encode('utf-8')
                                                 if fmt == 'json' else unity.FormatManager.to_csv(tree))
                                # Real negative path_id must also match when _index.json is omitted.
                                members.pop('_index.json')
                            output = io.BytesIO()
                            with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
                                for member, body in members.items():
                                    archive.writestr(member, body)
                            repacked = client.post('/repack', data={
                                'original_bundle': (io.BytesIO(source), 'card_data_5'),
                                'modified_zip': (io.BytesIO(output.getvalue()), 'patch.zip'), 'mode': mode,
                            }, headers={'Accept': 'application/json'})
                            try:
                                self.assertEqual(repacked.status_code, 200, repacked.data[:500])
                                result = UnityPy.load(repacked.data)
                                self.assertEqual({obj.path_id for obj in result.objects}, {obj.path_id for obj in original.objects})
                                actual = next(obj.read_typetree() for obj in result.objects if obj.path_id == text_asset.path_id)
                                self.assertEqual(actual['m_Name'], original_tree['m_Name'])
                                self.assertIsInstance(actual['m_Script'], str)
                                self.assertEqual(json.loads(actual['m_Script']), expected_cards)
                                for obj in result.objects:
                                    if obj.path_id in untouched:
                                        self.assertEqual(obj.get_raw_data(), untouched[obj.path_id])
                            finally:
                                repacked.close()
                                repacked.request.environ['wsgi.input'].close()
                            self.assertFalse(UNITY_TASK_LOCK.locked())
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), digest)
