"""User-reported files and large embedded trailing-comma JSON, real Linux jobs."""
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
SOURCE = ROOT / 'tests/fixtures/card_data_1'
PATCH = ROOT / 'tests/fixtures/card_data_1_modified.zip'


class EmbeddedTrailingCommaTests(unittest.TestCase):
    def test_export_and_transform_preserve_string_contents_in_both_modes(self):
        expected = {'text': 'literal ,] and ,} and "quoted"', 'items': [1, 2]}
        text = json.dumps(expected)[:-1] + ',}'
        for mode in ('auto', 'manual'):
            with self.subTest(mode=mode), patch.object(export_limits, 'JSON5_MAX_BYTES', 1), \
                    patch.object(unity.json5, 'loads', side_effect=AssertionError('JSON5 must not run')):
                policy = {'target_format': 'json', 'process_mode': mode}
                tree = unity.prepare_export_tree({'m_Script': text}, policy, export_limits.ExportBudget())
                self.assertEqual(tree['m_Script'], expected)
                self.assertEqual(unity.parse_embedded_json(text, mode), expected)

    def test_other_json5_syntax_and_structure_still_obey_export_budgets(self):
        cases = (("{value: 'nonstandard JSON'}", 'JSON5_MAX_BYTES', 1),
                 ('{"value": [1,],}', 'TREE_MAX_DEPTH', 1),
                 ('{"value": [1,],}', 'EMBEDDED_JSON_MAX_BYTES', 1),
                 ('{"value": [1,],}', 'TREE_MAX_NODES', 1))
        for text, limit, cap in cases:
            with self.subTest(limit=limit), patch.object(export_limits, limit, cap):
                with self.assertRaises(patch_limits.ClientFacingError) as caught:
                    unity.prepare_export_tree({'m_Script': text},
                        {'target_format': 'json', 'process_mode': 'auto'}, export_limits.ExportBudget())
                self.assertEqual(caught.exception.status, 413)


@unittest.skipUnless(sys.platform == 'linux', 'Real HTTP Unity jobs require Linux isolation')
class CardData1RoundtripTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__, template_folder=str(ROOT / 'templates'))
        app.testing = True
        app.config['MAX_CONTENT_LENGTH'] = 150 * 1024 * 1024
        app.register_blueprint(unity.unity_bp)
        self.client = app.test_client()
        self.source = SOURCE.read_bytes()
        self.original = UnityPy.load(self.source)
        self.target = next(obj for obj in self.original.objects if obj.type.name == 'TextAsset')
        self.tree = self.target.read_typetree()
        self.cards = json.loads(self.tree['m_Script'])

    def post_file(self, route, data):
        response = self.client.post(route, data=data, headers={'Accept': 'application/json'})
        try:
            self.assertEqual(response.status_code, 200, response.data[:1000])
            return response.data
        finally:
            response.close()
            response.request.environ['wsgi.input'].close()
            self.assertFalse(UNITY_TASK_LOCK.locked())

    def test_supplied_patch_applies_all_59_changed_cards(self):
        patch_bytes = PATCH.read_bytes()
        with zipfile.ZipFile(io.BytesIO(patch_bytes)) as archive:
            member = next(n for n in archive.namelist() if '/TextAsset/' in n and n.endswith('.json'))
            expected = patch_limits.loads_json_with_trailing_commas(archive.read(member).decode('utf-8'))
        self.assertEqual(len(expected['m_Script']), 660)
        self.assertEqual(sum(self.cards.get(k) != v for k, v in expected['m_Script'].items()), 59)
        for mode in ('auto', 'manual'):
            with self.subTest(mode=mode):
                output = self.post_file('/repack', {
                    'original_bundle': (io.BytesIO(self.source), 'card_data_1'),
                    'modified_zip': (io.BytesIO(patch_bytes), 'modified.zip'), 'mode': mode,
                })
                result = UnityPy.load(output)
                actual = next(obj.read_typetree() for obj in result.objects if obj.path_id == self.target.path_id)
                actual['m_Script'] = json.loads(actual['m_Script'])
                self.assertEqual(actual, expected)
                self.assertNotEqual(output, self.source)
                untouched = {obj.path_id: obj.get_raw_data() for obj in self.original.objects
                             if obj.path_id != self.target.path_id}
                self.assertEqual({obj.path_id: obj.get_raw_data() for obj in result.objects
                                  if obj.path_id != self.target.path_id}, untouched)
        self.assertEqual(SOURCE.read_bytes(), self.source)
        self.assertEqual(PATCH.read_bytes(), patch_bytes)
        self.assertEqual(hashlib.sha256(self.source).hexdigest(),
                         '6dbfaff6778e83b6d6ecd1725bc36436c3d143ee15c31703ee239fe094d3898c')

    def test_large_embedded_trailing_comma_exports_edits_and_repacks(self):
        text = self.tree['m_Script'].rstrip()
        self.assertGreater(len(text.encode('utf-8')), export_limits.JSON5_MAX_BYTES)
        self.tree['m_Script'] = text[:-1] + ',}'
        self.target.save_typetree(self.tree)
        source = self.original.file.save(packer='lz4')
        for fmt in ('json', 'csv'):
            for mode in ('auto', 'manual'):
                with self.subTest(format=fmt, mode=mode):
                    exported = self.post_file('/unpack', {
                        'bundle': (io.BytesIO(source), 'card_data_1'), 'format': fmt, 'mode': mode,
                    })
                    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
                        members = {name: archive.read(name) for name in archive.namelist()}
                    summary = json.loads(members['_export_summary.json'])
                    self.assertEqual((summary['exported_count'], summary['failed_count']), (1, 0))
                    name = json.loads(members['_index.json'])[str(self.target.path_id)]
                    text = members[name].decode('utf-8-sig')
                    tree = json.loads(text) if fmt == 'json' else unity.FormatManager.from_csv(text, self.tree)
                    self.assertEqual(tree['m_Script'], self.cards)
                    components = tree['m_Script']['1']['entity']['components']
                    attack = next(c['$data'] for c in components if '.Attack,' in c['$type'])
                    self.assertEqual(attack['AttackValue']['BaseValue'], 4)
                    attack['AttackValue']['BaseValue'] = 5
                    members[name] = (json.dumps(tree, ensure_ascii=False).encode('utf-8')
                                     if fmt == 'json' else unity.FormatManager.to_csv(tree))
                    # Match the negative path_id without an index, inside a wrapper folder.
                    members.pop('_index.json')
                    patch_bytes = io.BytesIO()
                    with zipfile.ZipFile(patch_bytes, 'w', zipfile.ZIP_DEFLATED) as archive:
                        for member, body in members.items():
                            archive.writestr('wrapped/' + member, body)
                    output = self.post_file('/repack', {
                        'original_bundle': (io.BytesIO(source), 'card_data_1'),
                        'modified_zip': (io.BytesIO(patch_bytes.getvalue()), 'modified.zip'), 'mode': mode,
                    })
                    result = UnityPy.load(output)
                    actual = next(obj.read_typetree() for obj in result.objects if obj.path_id == self.target.path_id)
                    self.assertEqual(json.loads(actual['m_Script']), tree['m_Script'])
                    self.assertEqual(actual['m_Name'], self.tree['m_Name'])
                    self.assertNotEqual(output, source)
                    untouched = {obj.path_id: obj.get_raw_data() for obj in self.original.objects
                                 if obj.path_id != self.target.path_id}
                    self.assertEqual({obj.path_id: obj.get_raw_data() for obj in result.objects
                                      if obj.path_id != self.target.path_id}, untouched)
