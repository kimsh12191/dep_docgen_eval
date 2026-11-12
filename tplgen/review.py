"""Human-reviewed reference contracts; no approval is inferred from model scores."""
from __future__ import annotations

import copy
import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from . import data as D, package as P

VERSION = 1
CHECKS = ('appearance', 'content', 'fields', 'changes')


def write_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def image_path(item):
    return next((p for p in sorted(Path(item).glob('image.*')) if p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}), None)


def draft(item):
    """Seed editable, frozen inputs from the reference, never from the candidate."""
    pkg = P.load(Path(item) / 'reference')
    if pkg['issues']:
        raise ValueError(', '.join(pkg['issues']))
    schema, sample = pkg['schema'], pkg['sample']
    cases = []
    for name, long in [('replace', False), ('long', True)]:
        rng = random.Random(4821)
        values = D.make(schema, rng, rows=0, long=long)
        for tb in schema['tables']:
            values[tb['name']] = D.make({'language': schema.get('language', 'ko'), 'fields': [], 'tables': [tb]}, rng,
                                      rows=len(sample[tb['name']]), long=long)[tb['name']]
        cases.append({'name': name, 'data': values})
    for tb in schema['tables']:
        lo, hi = int(tb.get('min_rows', 0)), int(tb.get('max_rows', 20))
        for n in sorted({lo, max(lo, min(1, hi)), hi}):
            values = copy.deepcopy(cases[0]['data'])
            values[tb['name']] = D.make({'language': schema.get('language', 'ko'), 'fields': [], 'tables': [tb]}, random.Random(4821), rows=n)[tb['name']]
            cases.append({'name': f"{tb['name']}_rows_{n}", 'data': values})
    for f in schema['fields']:
        options = [False, True] if f['type'] == 'bool' else f.get('options', []) if f['type'] == 'choice' else []
        for i, value in enumerate(options):
            values = copy.deepcopy(sample)
            values[f['name']] = value
            cases.append({'name': f"{f['name']}_option_{i}", 'data': values})
    return {'version': VERSION, 'schema': schema, 'sample': sample, 'cases': cases,
            'notes': '필수 필드·표, 허용 행 수와 긴 값 시험을 검수하세요. 필요하면 cases를 수정하세요.'}


def validate(contract):
    if contract.get('version') != VERSION or not isinstance(contract.get('schema'), dict):
        raise ValueError('지원하지 않는 계약 형식입니다')
    schema = contract['schema']
    fields, tables = schema.get('fields'), schema.get('tables')
    if not isinstance(fields, list) or not isinstance(tables, list) or not fields and not tables:
        raise ValueError('필드 또는 표가 필요합니다')
    names = [f['name'] for f in fields] + [t['name'] for t in tables]
    if len(names) != len(set(names)):
        raise ValueError('항목 이름이 중복됩니다')
    entries = fields + [c for t in tables for c in P.columns(t)]
    if any(not P.NAME.fullmatch(e.get('name', '')) or e.get('type') not in P.TYPES for e in entries):
        raise ValueError('항목 이름 또는 자료형 오류')
    if any(not P.NAME.fullmatch(t.get('name', '')) or not P.columns(t) or
           len(P.columns(t)) != len({c['name'] for c in P.columns(t)}) for t in tables):
        raise ValueError('표 이름 또는 열 정의 오류')
    cases = contract.get('cases')
    if not isinstance(cases, list) or not cases or len(cases) > 100:
        raise ValueError('변경 시험은 1~100개가 필요합니다')
    case_names = [c.get('name', '') for c in cases]
    if len(set(case_names)) != len(case_names) or any(not P.NAME.fullmatch(n) or n == 'sample' for n in case_names):
        raise ValueError('시험 이름은 중복 없는 영문 소문자·숫자·밑줄이어야 합니다')
    for values in [contract.get('sample')] + [c.get('data') for c in cases]:
        if not isinstance(values, dict) or set(values) != set(names):
            raise ValueError('각 시험값은 모든 필드와 표를 포함해야 합니다')
        for t in tables:
            rows = values[t['name']]
            if not isinstance(rows, list) or len(rows) > 200 or any(not isinstance(r, dict) or set(r) != {c['name'] for c in P.columns(t)} for r in rows):
                raise ValueError('표 값 또는 행 수 오류')
        typed = [(f, values[f['name']]) for f in fields]
        typed += [(c, row[c['name']]) for t in tables for row in values[t['name']] for c in P.columns(t)]
        for f, value in typed:
            if f['type'] == 'bool' and type(value) is not bool:
                raise ValueError('bool 값은 true/false여야 합니다')
            if f['type'] != 'bool' and not isinstance(value, (str, int, float)):
                raise ValueError('문자·숫자 필드 값 오류')
            if f['type'] == 'choice' and value not in f.get('options', []) and value != '':
                raise ValueError('선택지에 없는 값입니다')
    return contract


def load_contract(item):
    return validate(json.loads((Path(item) / 'contract.json').read_text(encoding='utf-8')))


def fingerprint(item):
    item = Path(item)
    image = image_path(item)
    if not image:
        raise ValueError('원본 이미지가 없습니다')
    digest = hashlib.sha256()
    for path in [image, item / 'contract.json'] + [item / 'reference' / n for n in P.FILES]:
        digest.update(path.relative_to(item).as_posix().encode())
        digest.update(b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def status(item):
    path = Path(item) / 'review.json'
    if not path.exists():
        return {'status': 'pending'}
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('fingerprint') != fingerprint(item):
            return {**record, 'status': 'stale'}
        if record.get('status') == 'approved' and (not record.get('reviewer') or not all(record.get('checks', {}).get(k) is True for k in CHECKS)):
            return {**record, 'status': 'pending'}
        return record
    except (ValueError, OSError):
        return {'status': 'stale'}


def decide(item, decision, reviewer, checks, note, expected):
    if decision not in {'approved', 'rejected'} or not reviewer.strip():
        raise ValueError('검수자와 승인/반려 상태가 필요합니다')
    load_contract(item)
    if fingerprint(item) != expected:
        raise ValueError('파일이 바뀌었습니다. 미리보기를 다시 확인하세요')
    if decision == 'approved' and not all(checks.get(k) is True for k in CHECKS):
        raise ValueError('승인하려면 네 검수 항목을 모두 확인하세요')
    record = {'status': decision, 'reviewer': reviewer.strip(), 'checks': checks, 'note': note,
              'fingerprint': expected, 'reviewed_at': datetime.now(timezone.utc).isoformat()}
    write_json(Path(item) / 'review.json', record)
    return record
