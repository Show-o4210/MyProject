"""Real disposable processes and real shipped bundles, small caps for abuse tests."""
import io
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

import pytest
from flask import Flask

from blueprints import unity
from extensions import UNITY_TASK_LOCK
from utils import unity_jobs as jobs
from utils.patch_limits import ClientFacingError

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Unity resource isolation requires Linux")

ROOT = Path(__file__).resolve().parents[1]


def make_app():
    app = Flask(__name__, template_folder=str(ROOT / 'templates'))
    app.config['MAX_CONTENT_LENGTH'] = 150 * jobs.MIB
    app.register_blueprint(unity.unity_bp)
    app.add_url_rule('/health', view_func=lambda: {'status': 'ok'})
    return app


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
