"""Disposable Unity worker. No untrusted container is parsed in the web process."""
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from utils.patch_limits import ClientFacingError
from flask import current_app, has_app_context

MIB = 1024 * 1024
WALL_SECONDS = 45
CPU_SECONDS = 30
ADDRESS_BYTES = 384 * MIB
RSS_BYTES = 256 * MIB
FILE_BYTES = 140 * MIB
DISK_BYTES = 384 * MIB
RESULT_BYTES = 2 * MIB
ROOT = Path(__file__).resolve().parents[1]


def directory_bytes(directory):
    return sum(p.stat().st_size for p in Path(directory).rglob('*') if p.is_file())


def kill_worker(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def run_unity_job(workdir, action, payload):
    """Only internal paths/validated JSON enter IPC; errors never expose worker internals."""
    if sys.platform != 'linux':
        raise ClientFacingError('在线处理需要 Linux 资源隔离，请使用本地工具。', 503)
    reserved_disk = payload.get('reserved_disk', payload.get('disk_sizes', {}).get('multipart', 0))
    job_path = Path(workdir) / 'job.json'
    job_path.write_text(json.dumps({'action': action, 'payload': payload}, ensure_ascii=False), encoding='utf-8')
    # Do not pass Supabase credentials or start Flask/scheduler in the child.
    env = {k: v for k, v in os.environ.items() if k in {'PATH', 'LANG', 'LC_ALL', 'VIRTUAL_ENV'}}
    env.update(TMPDIR=str(workdir), PYTHONPATH=str(ROOT), OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    process = subprocess.Popen(
        [sys.executable, '-m', 'utils.unity_worker', str(workdir)], cwd=ROOT,
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )
    started = time.monotonic()
    try:
        while process.poll() is None:
            if time.monotonic() - started > WALL_SECONDS:
                raise ClientFacingError('处理超过在线时间上限，请缩小文件或使用本地工具。', 413)
            if directory_bytes(workdir) + reserved_disk > DISK_BYTES:
                raise ClientFacingError('处理超过临时磁盘上限，请使用本地工具。', 413)
            try:
                status = Path(f'/proc/{process.pid}/status').read_text()
                rss = next((int(line.split()[1]) * 1024 for line in status.splitlines() if line.startswith('VmRSS:')), 0)
                if rss > RSS_BYTES:
                    raise ClientFacingError('处理超过在线内存上限，请使用本地工具。', 413)
            except FileNotFoundError:
                pass
            time.sleep(0.05)
        if process.returncode != 0:
            raise ClientFacingError('处理进程已中止，文件可能损坏或超过在线资源限制，请使用本地工具。', 413)
        result_path = Path(workdir) / 'result.json'
        if not result_path.is_file() or result_path.stat().st_size > RESULT_BYTES:
            raise ClientFacingError('处理结果超出在线范围，请使用本地工具。', 413)
        result = json.loads(result_path.read_text(encoding='utf-8'))
        if not result.get('ok'):
            raise ClientFacingError(result.get('error', '文件处理失败。'), result.get('status', 400))
        if directory_bytes(workdir) + reserved_disk > DISK_BYTES:
            raise ClientFacingError('处理超过临时磁盘上限，请使用本地工具。', 413)
        (current_app.logger if has_app_context() else logging.getLogger(__name__)).info("unity_job action=%s outcome=ok elapsed=%.2f", action, time.monotonic() - started)
        return result.get('data')
    except ClientFacingError as exc:
        (current_app.logger if has_app_context() else logging.getLogger(__name__)).warning("unity_job action=%s outcome=rejected status=%s elapsed=%.2f", action, exc.status, time.monotonic() - started)
        raise
    finally:
        kill_worker(process)
        job_path.unlink(missing_ok=True)
        (Path(workdir) / 'result.json').unlink(missing_ok=True)
