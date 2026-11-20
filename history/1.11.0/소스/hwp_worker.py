"""GUI·한컴·LibreOffice를 불러오지 않는 앱 Python 저장 worker."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

MAX_MESSAGE = 64 * 1024


def read_message(path):
    from document_hwp import require_regular
    path = require_regular(path)
    with path.open('rb') as stream:
        raw = stream.read(MAX_MESSAGE + 1)
    if len(raw) > MAX_MESSAGE:
        raise ValueError('worker 메시지 크기 제한을 초과했습니다.')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('worker 메시지에 중복 키가 있습니다.')
            result[key] = value
        return result
    data = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('유한 JSON 값이 필요합니다.')))
    if not isinstance(data, dict):
        raise ValueError('worker 메시지는 객체여야 합니다.')
    return data


def write_message(path, data):
    raw = (json.dumps(data, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    if len(raw) > MAX_MESSAGE:
        raise ValueError('worker 결과 크기 제한을 초과했습니다.')
    with Path(path).open('xb') as stream:
        stream.write(raw)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        return 2
    from document_hwp import bounded_read, convert_document, require_regular
    request = require_regular(argv[0])
    result = request.parent / 'result.json'
    if result.exists():
        raise FileExistsError('기존 worker 결과를 덮어쓰지 않습니다.')
    output = None
    try:
        data = read_message(request)
        if set(data) != {'version', 'source', 'target', 'source_sha256'} or type(data['version']) is not int or data['version'] != 1:
            raise ValueError('worker 요청 스키마가 다릅니다.')
        if data['target'] not in {'hwp', 'hwpx'} or not isinstance(data['source'], str):
            raise ValueError('worker 입력·출력 형식이 잘못됐습니다.')
        source = require_regular(data['source'])
        source_hash = hashlib.sha256(bounded_read(source)).hexdigest()
        if source_hash != data['source_sha256']:
            raise ValueError('원본 해시가 요청과 다릅니다.')
        output = request.parent / ('output.' + data['target'])
        if output.exists():
            raise FileExistsError('기존 worker 출력을 덮어쓰지 않습니다.')
        report = convert_document(source, data['target'], output)
        report['output'] = output.name
        write_message(result, report)
        return 0
    except Exception as error:
        # 원래 존재한 파일은 제거하지 않는다. 새 출력이 만들어진 뒤 보고가 실패하면 회수한다.
        if output is not None and output.is_file() and not isinstance(error, FileExistsError):
            output.unlink()
        write_message(result, {'version': 1, 'ok': False, 'error': type(error).__name__ + ': ' + str(error),
                               'code': getattr(error, 'code', None)})
        return 1


if __name__ == '__main__':
    sys.exit(main())
