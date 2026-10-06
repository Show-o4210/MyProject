"""Set kernel limits BEFORE importing UnityPy or reading a job."""
import json
import os
from pathlib import Path
import resource
import sys

from utils.unity_jobs import ADDRESS_BYTES, CPU_SECONDS, FILE_BYTES, RESULT_BYTES


def set_limits():
    for kind, value in (
        (resource.RLIMIT_AS, ADDRESS_BYTES), (resource.RLIMIT_CPU, CPU_SECONDS),
        (resource.RLIMIT_FSIZE, FILE_BYTES), (resource.RLIMIT_NOFILE, 64),
        (resource.RLIMIT_NPROC, 16), (resource.RLIMIT_CORE, 0),
    ):
        resource.setrlimit(kind, (value, value))


def dispatch(workdir, action, payload):
    if action in {'unpack', 'repack'}:
        from blueprints.unity import perform_unpack, perform_repack
        from utils.export_limits import ExportBudget
        if action == 'unpack':
            budget = ExportBudget()
            budget.disk_sizes.update(payload.get('disk_sizes', {}))
            perform_unpack(str(workdir / 'input.bundle'), str(workdir / 'output.zip'), payload['policy'], budget)
        else:
            perform_repack(str(workdir / 'original.bundle'), str(workdir / 'patch.zip'), str(workdir / 'output.bundle'), payload['mode'])
    elif action == 'deck_export':
        from logic_unity import unity_processor
        unity_processor.repack_from_server_data(payload['mods'], output_path=str(workdir / 'output.zip'))
    elif action == 'deck_init':
        from logic_unity import unity_processor
        return unity_processor.extract_all_to_memory()
    elif action.startswith('level_'):
        from logic_level_editor import LevelEditorLogic
        logic = LevelEditorLogic()
        if action == 'level_list':
            return logic.get_all_level_ids()
        if action == 'level_extract':
            return logic.load_level_config(payload['level_id'])
        if action == 'level_pack':
            logic.pack_level_config(payload['level_id'], payload['config_text'], output_path=str(workdir / 'output.bundle'))
        else:
            raise ValueError('Unknown job')
    else:
        raise ValueError('Unknown job')


def main():
    set_limits()
    workdir = Path(sys.argv[1]).resolve()
    os.chdir(workdir)
    try:
        job = json.loads((workdir / 'job.json').read_text(encoding='utf-8'))
        data = dispatch(workdir, job['action'], job['payload'])
        result = {'ok': True, 'data': data}
    except (MemoryError, RecursionError):
        result = {'ok': False, 'error': '文件超过在线内存或结构限制，请使用本地工具。', 'status': 413}
    except Exception as exc:
        result = {'ok': False, 'error': str(exc)[:1000], 'status': getattr(exc, 'status', 400)}
    encoded = json.dumps(result, ensure_ascii=True).encode('utf-8')
    if len(encoded) > RESULT_BYTES:
        encoded = b'{"ok":false,"error":"Result exceeds online limit","status":413}'
    (workdir / 'result.json').write_bytes(encoded)


if __name__ == '__main__':
    main()
