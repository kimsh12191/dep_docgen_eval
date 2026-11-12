"""Offline scoring against approved references. Never used in generation feedback."""
from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import re
from pathlib import Path

from . import check as C, package as P, review
from .render import Renderer

VERSION = 1


def norm(value):
    return re.sub(r'\s+', '', str(value))


def entries(schema):
    out = {f['name']: f for f in schema.get('fields', [])}
    out.update({f"{t['name']}.{c['name']}": c for t in schema.get('tables', []) for c in P.columns(t)})
    return out


def match_groups(required, actual, overrides=None):
    """Conservative one-to-one matching; ambiguous labels are left unmatched."""
    mapping, used = {}, set()
    for key, target in (overrides or {}).items():
        if key not in required or target is not None and target not in actual:
            raise ValueError(f'잘못된 매핑: {key} → {target}')
        if target is not None:
            if target in used:
                raise ValueError(f'중복 매핑: {target}')
            mapping[key] = target
            used.add(target)
    for key, expected in required.items():
        if key in (overrides or {}):
            continue
        candidates = [k for k, a in actual.items() if k not in used and a.get('type') == expected.get('type')
                      and norm(a.get('label', '')) == norm(expected.get('label', '')) and norm(expected.get('label', ''))]
        # Identical names disambiguate repeated labels, but never override conflicting labels/types.
        target = key if key in candidates else candidates[0] if len(candidates) == 1 else None
        if target is not None:
            mapping[key] = target
            used.add(target)
    return mapping


def align(schema, candidate, overrides=None):
    overrides = overrides or {}
    expected, actual = entries(schema), entries(candidate)
    if any(k not in expected or v is not None and v not in actual for k, v in overrides.items()):
        raise ValueError('매핑 파일에 없는 필드가 있습니다')
    mapping = match_groups({k: v for k, v in expected.items() if '.' not in k},
                           {k: v for k, v in actual.items() if '.' not in k},
                           {k: v for k, v in overrides.items() if '.' not in k})
    rt = {t['name']: t for t in schema.get('tables', [])}
    ct = {t['name']: t for t in candidate.get('tables', [])}
    table_overrides = {}
    for k, v in overrides.items():
        if '.' in k and v is not None:
            if '.' not in v:
                raise ValueError('표 열은 표 열에 대응해야 합니다')
            a, b = k.split('.')[0], v.split('.')[0]
            if a in table_overrides and table_overrides[a] != b:
                raise ValueError('한 표의 열이 서로 다른 표에 매핑되었습니다')
            table_overrides[a] = b
    tables = match_groups(rt, ct, table_overrides)
    for a, b in tables.items():
        rcols = {k: v for k, v in expected.items() if k.startswith(a + '.')}
        ccols = {k: v for k, v in actual.items() if k.startswith(b + '.')}
        # Use column-local names for exact-name disambiguation after table renaming.
        local_overrides = {k.split('.')[1]: v.split('.')[1] if v else None for k, v in overrides.items() if k.startswith(a + '.')}
        local = match_groups({k.split('.')[1]: v for k, v in rcols.items()},
                             {k.split('.')[1]: v for k, v in ccols.items()}, local_overrides)
        mapping.update({f'{a}.{k}': f'{b}.{v}' for k, v in local.items()})
    return mapping, tables


def translate(values, pkg, mapping, tables):
    out = copy.deepcopy(pkg['sample'])
    for key, target in mapping.items():
        if '.' not in key:
            out[target] = values[key]
    for a, b in tables.items():
        cols = {k.split('.')[1]: v.split('.')[1] for k, v in mapping.items() if k.startswith(a + '.')}
        target_table = next(t for t in pkg['schema']['tables'] if t['name'] == b)
        out[b] = [{c['name']: next((row[k] for k, v in cols.items() if v == c['name']), '') for c in P.columns(target_table)} for row in values[a]]
    return out


def mapped_path(path, mapping):
    parts = path.split('.')
    key = path if len(parts) == 1 else parts[0] + '.' + parts[-1]
    target = mapping.get(key)
    if target is None:
        return None
    if len(parts) == 1:
        return target
    table, column = target.split('.')
    return f'{table}.{parts[1]}.{column}'


def texts(shot):
    out = {}
    for label in shot['labels']:
        if label.get('visible', True):
            out[label['field']] = out.get(label['field'], '') + norm(label['text'])
    return out


def score_case(expected, actual, paths, mapping):
    ref, got = texts(expected), texts(actual)
    failures, correct = [], 0
    for path in paths:
        target = mapped_path(path, mapping)
        # Empty fields may collapse to zero width; non-empty fields must be visible.
        expected_text = ref.get(path, '')
        all_actual = {l['field'] for l in actual['labels']}
        if target and target in all_actual and got.get(target, '') == expected_text and (not expected_text or target in got):
            correct += 1
        else:
            failures.append(f'value:{path}')
    wanted = {mapped_path(p, mapping) for p in paths} - {None}
    unexpected = set(l['field'] for l in actual['labels']) - wanted
    failures += [f'unexpected:{p}' for p in sorted(unexpected)]
    failures += actual['problems']
    fixed = difflib.SequenceMatcher(None, norm(expected.get('fixed_text', '')), norm(actual.get('fixed_text', '')), autojunk=False).ratio()
    if fixed < C.REVIEW_RULE['fixed_text']:
        failures.append('fixed_text_changed')
    return {'value_accuracy': correct / len(paths) if paths else 1.0, 'fixed_text': fixed,
            'pass': not failures, 'issues': failures}


def preflight(dataset):
    items = [p for p in sorted(Path(dataset).iterdir()) if p.is_dir() and review.image_path(p)]
    if not items:
        raise ValueError('평가 문서가 없습니다')
    blocked = [p.name + ':' + review.status(p)['status'] for p in items if review.status(p)['status'] != 'approved']
    if blocked:
        raise ValueError('승인된 기준이 필요합니다: ' + ', '.join(blocked))
    for item in items:
        review.load_contract(item)
    return items


def evaluate(item, folder, renderer, out=None, overrides=None):
    item, folder = Path(item), Path(folder)
    if review.status(item)['status'] != 'approved':
        raise ValueError(f'{item.name}: 기준 검수가 필요합니다')
    contract = review.load_contract(item)
    ref, pkg = P.load(item / 'reference'), P.load(folder)
    result = {'version': VERSION, 'reference_fingerprint': review.fingerprint(item),
              'valid': False, 'pass': False, 'field_precision': 0.0, 'field_recall': 0.0, 'field_f1': 0.0,
              'sample_accuracy': 0.0, 'fixed_text': 0.0, 'change_pass_rate': 0.0,
              'layout': 0.0, 'missing': 1.0, 'issues': pkg['issues'], 'tests': {}}
    if pkg['issues']:
        return result
    mapping, tables = align(contract['schema'], pkg['schema'], overrides)
    n, m = len(entries(contract['schema'])), len(entries(pkg['schema']))
    precision, recall = len(mapping) / max(m, 1), len(mapping) / max(n, 1)
    result.update(mapping=mapping, unmapped=sorted(set(entries(contract['schema'])) - set(mapping)),
                  field_precision=precision, field_recall=recall,
                  field_f1=2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(out or tmp)
        output.mkdir(parents=True, exist_ok=True)
        for case in [{'name': 'sample', 'data': contract['sample']}] + contract['cases']:
            name, values = case['name'], case['data']
            expected = renderer.render(P.html(ref, values))
            # Original reproduction must use the candidate's own extracted sample values.
            actual_values = pkg['sample'] if name == 'sample' else translate(values, pkg, mapping, tables)
            try:
                png = output / f'{name}.png'
                actual = renderer.render(P.html(pkg, actual_values), png)
                scored = score_case(expected, actual, P.paths(contract['schema'], values), mapping)
                if name == 'sample':
                    result['valid'] = actual['width'] > 0 and actual['height'] > 0
                    result['sample_accuracy'], result['fixed_text'] = scored['value_accuracy'], scored['fixed_text']
                    if result['valid']:
                        result['layout'], result['missing'] = C.layout(review.image_path(item), C.fill_assets(png, actual))
                result['tests'][name] = scored
            except Exception as e:
                result['tests'][name] = {'pass': False, 'value_accuracy': 0.0, 'fixed_text': 0.0,
                                         'issues': [f'render_error:{type(e).__name__}:{str(e)[:200]}']}
        changes = [v for k, v in result['tests'].items() if k != 'sample']
        result['change_pass_rate'] = sum(c['pass'] for c in changes) / len(changes)
        result['pass'] = bool(result['valid'] and result['tests']['sample']['pass'] and
                              all(result[k] >= v for k, v in C.REVIEW_RULE.items()) and result['missing'] <= C.MAX_MISSING)
    return result


def report(dataset, runs, out):
    items = preflight(dataset)
    runs, out = Path(runs), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    models = [p for p in sorted(runs.iterdir()) if p.is_dir() and any((p / it.name).is_dir() for it in items)]
    if not models:
        raise ValueError('모델 실행 결과가 없습니다')
    rows = []
    with Renderer() as renderer:
        renderer_info = {'browser': renderer._browser.version, 'scale': renderer.scale, 'viewport': [1200, 1200]}
        for model in models:
            for item in items:
                root = model / item.name
                mp = root / 'field_map.json'
                overrides = json.loads(mp.read_text(encoding='utf-8')) if mp.exists() else None
                logs = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(root.glob('round*/make.json'))]
                for stage, folder in [('first', root / 'round0'), ('final', root / 'final')]:
                    result = evaluate(item, folder, renderer, out / model.name / item.name / stage, overrides)
                    paid = logs[:1] if stage == 'first' else logs
                    seconds = sum(g.get('seconds') or 0 for g in paid)
                    usage = [g.get('usage') or {} for g in paid]
                    tokens = sum(g['total_tokens'] for g in usage) if usage and all('total_tokens' in g for g in usage) else None
                    digest = hashlib.sha256()
                    for filename in P.FILES:
                        p = folder / filename
                        digest.update(filename.encode() + (p.read_bytes() if p.exists() else b'<missing>'))
                    result.update(model=model.name, image=item.name, stage=stage, seconds_total=seconds,
                                  tokens_total=tokens, candidate_fingerprint=digest.hexdigest(), field_map=overrides, renderer=renderer_info,
                                  calls=len(paid))
                    rows.append(result)
    # Refuse to publish a mixed report if a human changed the references during scoring.
    for row in rows:
        item = Path(dataset) / row['image']
        if review.status(item)['status'] != 'approved' or review.fingerprint(item) != row['reference_fingerprint']:
            raise ValueError('채점 중 기준이 변경되었습니다. 다시 실행하세요')
    (out / 'results.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    lines = ['# 승인 기준 템플릿 평가', '', '점수는 문서별 평균. 실패도 분모에 포함합니다. layout은 대략적인 배치 지표이며 정밀 시각 품질 순위가 아닙니다.', '',
             '| 모델 | 단계 | 사용 가능 | 필드 P/R/F1 | 원본 값 정확도 | 고정 문구 유사도 | 변경 시험 통과율 | 배치 유사도 | 호출 초 |',
             '|---|---|---|---|---|---|---|---|---|']
    for model in models:
        for stage in ('first', 'final'):
            group = [r for r in rows if r['model'] == model.name and r['stage'] == stage]
            avg = lambda k: sum(r[k] for r in group) / len(group)
            lines.append(f"| {model.name} | {stage} | {sum(r['pass'] for r in group)}/{len(group)} | " +
                         '/'.join(f'{avg(k):.3f}' for k in ('field_precision', 'field_recall', 'field_f1')) + ' | ' +
                         ' | '.join(f'{avg(k):.3f}' for k in ('sample_accuracy', 'fixed_text', 'change_pass_rate', 'layout', 'seconds_total')) + ' |')
    lines += ['', '통과 기준: ' + json.dumps(C.REVIEW_RULE, ensure_ascii=False),
              '추가 조건: sample 시험 통과, 렌더링 성공, missing ≤ ' + str(C.MAX_MISSING),
              'final 비용은 선택된 회차와 무관하게 실행한 모든 회차를 합산합니다. 초는 모델 호출 시간이며 렌더링 시간은 제외합니다.',
              '매핑이 모호하면 model/document/field_map.json으로 정답 경로 → 생성 경로를 지정하고 다시 채점하세요. null은 미대응입니다.']
    text = '\n'.join(lines) + '\n'
    (out / 'compare.md').write_text(text, encoding='utf-8')
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dataset', default='evalset/v1')
    ap.add_argument('--runs', required=True)
    ap.add_argument('--out', default='out/evaluation')
    a = ap.parse_args(argv)
    try:
        print(report(a.dataset, a.runs, a.out))
    except ValueError as e:
        raise SystemExit(str(e)) from e
