"""Real disposable processes and real shipped bundles, small caps for abuse tests."""
import io
import json
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
from unittest.mock import patch
import zipfile

import pytest
from flask import Flask
import UnityPy

from blueprints import unity, deck_editor
from extensions import UNITY_TASK_LOCK
from logic_data import data_manager
from utils import unity_jobs as jobs
from utils.patch_limits import ClientFacingError

ROOT = Path(__file__).resolve().parents[1]


def make_app():
    app = Flask(__name__, template_folder=str(ROOT / 'templates'))
    app.config['MAX_CONTENT_LENGTH'] = 150 * jobs.MIB
    app.register_blueprint(unity.unity_bp)
    app.register_blueprint(deck_editor.deck_editor_bp)
    app.add_url_rule('/health', view_func=lambda: {'status': 'ok'})
    return app


def valid_mods():
    return {'Deck_GreenShadow_G1': [{'cardguid': 1, 'count': 2, 'faction': 0}]}


def test_real_deck_export_preserves_modified_count_and_other_bundle():
    app = make_app()
    with patch('UnityPy.load', side_effect=AssertionError('web process must never parse Unity')):
        result = app.test_client().post('/api/quick_export', data={'deck_json': json.dumps(valid_mods())})
    assert result.status_code == 200, result.data
    with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
        assert set(archive.namelist()) == {'recipe_decks_1', 'recipe_definitions_1'}
        env = UnityPy.load(archive.read('recipe_decks_1'))
        trees = [obj.read_typetree() for obj in env.objects if obj.type.name == 'MonoBehaviour']
        deck = next(tree for tree in trees if tree.get('m_Name') == 'Deck_GreenShadow_G1')
        entry = deck['Cards']['CardEntries'][0]
        assert (entry['CardGuid'], entry['NumCopies'], entry['Faction']) == (1, 2, 0)
    result.close()
    assert not UNITY_TASK_LOCK.locked()
    assert app.test_client().get('/health').status_code == 200


@pytest.mark.parametrize('mods', [[], {}, {'unknown': []}, {'Deck_GreenShadow_G1': [0]},
    {'Deck_GreenShadow_G1': [{'cardguid': True, 'count': 1, 'faction': 0}]},
    {'Deck_GreenShadow_G1': [{'cardguid': 1, 'count': 100, 'faction': 0}]},
    {'Deck_GreenShadow_G1': [{'cardguid': 1, 'count': 2, 'faction': 1}]},
    {'Deck_GreenShadow_G1': [{'cardguid': 99999999, 'count': 2, 'faction': 0}]},
    {'Deck_GreenShadow_G1': [dict(cardguid=1, count=2, faction=0)] * 129},
])
def test_invalid_decks_never_acquire_lock_or_start_worker(mods):
    with patch.object(deck_editor, 'acquire_unity_lock') as lock, patch.object(deck_editor, 'run_unity_job') as runner:
        result = make_app().test_client().post('/api/quick_export', data={'deck_json': json.dumps(mods)})
    assert result.status_code in {400, 413}
    lock.assert_not_called(); runner.assert_not_called()


def test_large_deck_body_rejects_before_parsing_and_lock():
    with patch.object(deck_editor, 'acquire_unity_lock') as lock:
        result = make_app().test_client().post('/api/quick_export', data={'deck_json': ' ' * (512 * 1024 + 1)})
    assert result.status_code == 413
    lock.assert_not_called()


def test_busy_lock_returns_immediately_and_does_not_start_worker():
    UNITY_TASK_LOCK.acquire()
    try:
        start = time.monotonic()
        with patch.object(deck_editor, 'run_unity_job') as runner:
            result = make_app().test_client().post('/api/quick_export', data={'deck_json': json.dumps(valid_mods())})
        assert result.status_code == 429
        assert time.monotonic() - start < 1
        runner.assert_not_called()
    finally:
        UNITY_TASK_LOCK.release()


def harness_runner(monkeypatch, script):
    real_popen = subprocess.Popen
    processes = []
    def spawn(command, **kwargs):
        kwargs["cwd"] = command[-1]
        child = real_popen([command[0], '-c', script], **kwargs)
        processes.append(child)
        return child
    monkeypatch.setattr(jobs.subprocess, 'Popen', spawn)
    return processes


def test_wall_timeout_kills_real_worker_group_and_cleans_ipc(monkeypatch, tmp_path):
    children = harness_runner(monkeypatch, 'import time; time.sleep(30)')
    monkeypatch.setattr(jobs, 'WALL_SECONDS', 0.15)
    with pytest.raises(ClientFacingError) as error:
        jobs.run_unity_job(str(tmp_path), 'unpack', {})
    assert error.value.status == 413
    assert children[0].poll() == -signal.SIGKILL
    assert not (tmp_path / 'job.json').exists()


def test_kernel_memory_limit_rejects_allocation_and_parent_survives(tmp_path):
    script = '''from utils import unity_worker as worker
worker.ADDRESS_BYTES = 64 * 1024 * 1024
worker.set_limits()
try:
    value = bytearray(128 * 1024 * 1024)
except MemoryError:
    print('memory bounded')
'''
    child = subprocess.run([jobs.sys.executable, '-c', script], cwd=ROOT, capture_output=True, text=True, timeout=5)
    assert child.returncode == 0, child.stderr
    assert 'memory bounded' in child.stdout


def test_kernel_cpu_limit_terminates_busy_worker():
    script = '''from utils import unity_worker as worker
worker.CPU_SECONDS = 1
worker.set_limits()
while True: pass
'''
    child = subprocess.run([jobs.sys.executable, '-c', script], cwd=ROOT, capture_output=True, timeout=5)
    assert child.returncode in {-signal.SIGKILL, -signal.SIGXCPU}


def test_kernel_output_limit_stops_large_file(tmp_path):
    script = '''from utils import unity_worker as worker
import sys
worker.FILE_BYTES = 4096
worker.set_limits()
try:
    with open(sys.argv[1], 'wb') as out: out.write(b'a' * 8192)
except OSError:
    print('output bounded')
'''
    target = tmp_path / 'output'
    child = subprocess.run([jobs.sys.executable, '-c', script, str(target)], cwd=ROOT, capture_output=True, text=True, timeout=5)
    assert child.returncode == 0
    assert target.stat().st_size <= 4096
    assert 'output bounded' in child.stdout


def test_disk_watchdog_and_rss_watchdog_kill_child(monkeypatch, tmp_path):
    for kind, value, code in [('DISK_BYTES', 128, "from pathlib import Path; Path('large').write_bytes(b'x'*1024); import time; time.sleep(30)"),
                              ('RSS_BYTES', 1024, 'import time; time.sleep(30)')]:
        with monkeypatch.context() as current:
            children = harness_runner(current, code)
            current.setattr(jobs, kind, value)
            if kind == 'RSS_BYTES':
                read_text = Path.read_text
                def status_text(path, *args, **kwargs):
                    if str(path).startswith('/proc/'):
                        return 'VmRSS: 2048 kB\n'
                    return read_text(path, *args, **kwargs)
                current.setattr(Path, 'read_text', status_text)
            with pytest.raises(ClientFacingError):
                jobs.run_unity_job(str(tmp_path), 'unpack', {})
            assert children[0].poll() == -signal.SIGKILL
        (tmp_path / 'large').unlink(missing_ok=True)


def test_worker_rejection_cleans_upload_directory_and_unlocks(tmp_path):
    app = make_app()
    with patch.object(unity.tempfile, 'mkdtemp', return_value=str(tmp_path)), patch.object(unity, 'cleanup_old_temp'):
        result = app.test_client().post('/unpack', data={'bundle': (io.BytesIO(b'broken'), 'bad.bundle')}, headers={'Accept': 'application/json'})
    assert result.status_code == 400
    assert not tmp_path.exists()
    assert not UNITY_TASK_LOCK.locked()
    assert app.test_client().get('/health').status_code == 200
