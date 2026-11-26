"""사용자가 명시적으로 이어가는 로컬 작업·결과 소유권 기록."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import quick_actions as core

MAX_BYTES = 16 * 1024 * 1024
STATES = {'waiting', 'running', 'completed', 'failed', 'cancelled', 'review'}


def _hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _owned(row):
    if not isinstance(row, dict) or not {'path', 'source', 'sha256', 'size'} <= row.keys():
        raise ValueError('결과 기록 형식을 확인해 주세요.')
    if not _hash(row['sha256']) or type(row['size']) is not int or row['size'] < 0:
        raise ValueError('결과 해시·크기 기록을 확인해 주세요.')
    if not isinstance(row['source'], str) or not isinstance(row['path'], str) or not Path(row['path']).is_absolute():
        raise ValueError('결과 경로 기록을 확인해 주세요.')
    return copy.deepcopy(row)


def _validate(value):
    if not isinstance(value, dict) or set(value) != {'version', 'jobs', 'ledger'} or type(value['version']) is not int or value['version'] != 1:
        raise ValueError('지원하지 않는 대기열 기록입니다.')
    jobs, ledger = value['jobs'], value['ledger']
    if not isinstance(jobs, list) or len(jobs) > 1000 or not isinstance(ledger, dict) or set(ledger) != {'rows', 'moves'}:
        raise ValueError('대기열 기록 한도를 확인해 주세요.')
    count, identifiers = 0, set()
    for job in jobs:
        if not isinstance(job, dict) or not {'id', 'inputs', 'action', 'output', 'state', 'file_states', 'checkpoints'} <= job.keys():
            raise ValueError('작업 기록 형식을 확인해 주세요.')
        if not isinstance(job['id'], str) or not re.fullmatch('[0-9a-f]{8}', job['id']) or job['id'] in identifiers:
            raise ValueError('작업 식별자를 확인해 주세요.')
        identifiers.add(job['id'])
        core.validate_action(job['action'])
        if job['state'] not in STATES or not isinstance(job['output'], str) or not Path(job['output']).is_absolute():
            raise ValueError('작업 상태·결과 경로를 확인해 주세요.')
        if not isinstance(job['inputs'], list) or not isinstance(job['checkpoints'], dict) or not isinstance(job['file_states'], dict):
            raise ValueError('파일 작업 기록을 확인해 주세요.')
        count += len(job['inputs'])
        if count > core.MAX_FILES:
            raise ValueError('복구 가능한 입력은 최대 10,000개입니다.')
        result = job.get('result')
        if result is not None:
            if not isinstance(result, dict) or result.get('status') not in STATES or not isinstance(result.get('error'), str):
                raise ValueError('작업 결과 상태를 확인해 주세요.')
            if not isinstance(result.get('outputs'), list) or not isinstance(result.get('files'), list) or not isinstance(result.get('warnings'), list):
                raise ValueError('작업 결과 목록을 확인해 주세요.')
            if any(not isinstance(text, str) for text in result['warnings']):
                raise ValueError('작업 경고 기록을 확인해 주세요.')
            for row in result['outputs']:
                _owned(row)
            for row in result['files']:
                if not isinstance(row, dict) or not isinstance(row.get('source'), str) or row.get('state') not in STATES:
                    raise ValueError('파일 결과 상태를 확인해 주세요.')
        if 'retried' in job and type(job['retried']) is not bool:
            raise ValueError('재시도 기록을 확인해 주세요.')
        if 'bundle_rows' in job:
            if not isinstance(job['bundle_rows'], list) or not isinstance(job.get('previous'), dict):
                raise ValueError('묶음 재시도 기록을 확인해 주세요.')
            for row in job['bundle_rows']:
                _owned(row)
                if not Path(row['path']).is_relative_to(Path(job['output'])):
                    raise ValueError('묶음 입력이 결과 폴더 밖에 있습니다.')
        sources = set()
        for row in job['inputs']:
            if not isinstance(row, dict) or set(row) != {'source', 'relative'} or not all(isinstance(v, str) for v in row.values()):
                raise ValueError('입력 기록 형식을 확인해 주세요.')
            relative = Path(row['relative'])
            if not Path(row['source']).is_absolute() or relative.anchor or relative.drive or '..' in relative.parts or not relative.name:
                raise ValueError('입력 경로 기록을 확인해 주세요.')
            for part in relative.parts:
                core.workspace._name(part)
            sources.add(row['source'])
        if set(job['file_states']) != sources or any(v not in STATES for v in job['file_states'].values()):
            raise ValueError('파일 상태 기록을 확인해 주세요.')
        for source, checkpoint in job['checkpoints'].items():
            if source not in sources | {''} or not isinstance(checkpoint, dict) or not _hash(checkpoint.get('input_sha256')):
                raise ValueError('입력 해시 기록을 확인해 주세요.')
            if checkpoint.get('state') not in STATES or type(checkpoint.get('expected', 1)) is not int or checkpoint.get('expected', 1) < 1:
                raise ValueError('완료 기록을 확인해 주세요.')
            for row in checkpoint.get('outputs', []):
                _owned(row)
                if not Path(row['path']).is_relative_to(Path(job['output'])):
                    raise ValueError('결과가 작업 폴더 밖에 있습니다.')
    if not isinstance(ledger['rows'], dict) or not isinstance(ledger['moves'], list) or len(ledger['rows']) > 20000 or len(ledger['moves']) > 20000:
        raise ValueError('결과 보관 기록 한도를 확인해 주세요.')
    for path, row in ledger['rows'].items():
        _owned(row)
        if path != row['path']:
            raise ValueError('결과 소유권 기록이 일치하지 않습니다.')
    for row in ledger['moves']:
        if not isinstance(row, dict) or set(row) != {'original', 'stored', 'sha256'} or not _hash(row['sha256']):
            raise ValueError('보관 기록을 확인해 주세요.')
        original, stored = Path(row['original']), Path(row['stored'])
        if not original.is_absolute() or stored.parent != original.parent / '.flipring-undo':
            raise ValueError('보관 경로 기록을 확인해 주세요.')
        if str(original) not in ledger['rows'] or ledger['rows'][str(original)]['sha256'] != row['sha256']:
            raise ValueError('보관 소유권이 일치하지 않습니다.')
    return copy.deepcopy(value)


class QueueJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.blocked = False

    def load(self):
        with self.lock:
            try:
                if not self.path.exists():
                    return {'version': 1, 'jobs': [], 'ledger': {'rows': {}, 'moves': []}}
                core.safe_path(self.path)
                if self.path.stat().st_size > MAX_BYTES:
                    raise ValueError('대기열 기록은 16MiB 이하여야 합니다.')
                return _validate(json.loads(self.path.read_text(encoding='utf-8')))
            except Exception:
                self.blocked = True
                raise

    def save(self, jobs, ledger):
        with self.lock:
            if self.blocked:
                raise ValueError('손상된 기록은 덮어쓰지 않습니다. 기록 파일을 별도 보존하고 확인해 주세요.')
            value = _validate({'version': 1, 'jobs': jobs, 'ledger': {'rows': ledger.rows, 'moves': ledger.moves}})
            data = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            if len(data) > MAX_BYTES:
                raise ValueError('대기열 기록은 16MiB 이하여야 합니다.')
            core.safe_path(self.path, exists=False)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)


def checkpoint_event(job, event):
    source, state = event['source'], event['state']
    if state == 'publishing':
        point = job['checkpoints'].setdefault(source, {'input_sha256': event['input_sha256'],
                'state': 'running', 'outputs': [], 'expected': event.get('expected', 1)})
        point['expected'] = event.get('expected', 1)
        owned = copy.deepcopy(event['owned'])
        owned['constraints_met'] = not job['action']['max_bytes'] or owned['size'] <= job['action']['max_bytes']
        point['outputs'].append(owned)
    elif state == 'publication_conflict':
        point = job['checkpoints'][source]
        point['outputs'] = [r for r in point['outputs'] if r['path'] != event['owned']['path']]
    elif state == 'completed' and 'outputs' in event:
        job['checkpoints'][source] = {'input_sha256': event['input_sha256'], 'state': 'completed',
                                      'outputs': copy.deepcopy(event['outputs']), 'expected': len(event['outputs'])}


def recover_jobs(jobs):
    """파일 내용을 검사하고 복구 상태만 반환한다. 자동 실행하지 않는다."""
    # 입력과 결과가 일치한 항목만 완료로 인정한다.
    jobs = copy.deepcopy(jobs)
    for job in jobs:
        for source, point in job['checkpoints'].items():
            try:
                valid = (not source or core.digest(source) == point['input_sha256'])
                valid = valid and len(point['outputs']) == point.get('expected', 1) and bool(point['outputs'])
                valid = valid and all(core.digest(row['path']) == row['sha256'] for row in point['outputs'])
            except (OSError, ValueError):
                valid = False
            if not point.get('outputs') and point.get('state') == 'waiting':
                try: valid = not source or core.digest(source) == point['input_sha256']
                except (OSError, ValueError): valid = False
                point['state'] = 'waiting' if valid else 'review'
            else:
                point['state'] = 'completed' if valid else 'review'
            if source:
                job['file_states'][source] = point['state']
        if any(p['state'] == 'review' for p in job['checkpoints'].values()):
            job['state'] = 'review'
        elif job['state'] in {'running', 'waiting', 'review'}:
            job['state'] = 'waiting'
    return jobs


def diagnostic(jobs, version='1.13.0'):
    """공유 정보는 고정된 허용 목록에서 새로 구성한다."""
    from collections import Counter
    statuses = Counter(j['state'] for j in jobs if j.get('state') in STATES)
    allowed = {'jpg', 'jpeg', 'png', 'webp', 'pdf', 'docx', 'xlsx', 'pptx', 'txt', 'hwp', 'hwpx', 'zip'}
    extensions = Counter((Path(r['source']).suffix.lower().lstrip('.') if Path(r['source']).suffix.lower().lstrip('.') in allowed else 'other')
                         for j in jobs for r in j.get('inputs', []))
    return {'version': version if version == '1.13.0' else 'unknown', 'jobs': len(jobs),
            'states': dict(statuses), 'extensions': dict(extensions),
            'error_codes': {'TASK_FAILED': statuses.get('failed', 0), 'REVIEW_REQUIRED': statuses.get('review', 0)}}
