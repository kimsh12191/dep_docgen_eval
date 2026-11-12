"""Inventory document_gen forms, rasterize existing PDFs, and promote human picks.
No synthetic samples, gold HTML, or human approvals are generated here.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

REPO_URL = 'https://github.com/kimsh12191/document_gen'


def read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else default


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(source):
    """Resolve source PDFs without executing any source-repository code."""
    root = source / 'docgen' / 'forms'
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain', '--', 'docgen/forms'], text=True).strip():
        raise ValueError('소스 서식에 미커밋 변경이 있습니다. 고정 커밋의 서식을 사용하세요.')
    rows = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not re.fullmatch(r'(gov_.+|hana_.+|hf\d+)', folder.name):
            continue
        form, fields, layout = [read(folder / n, {}) for n in ('form.json', 'fields.json', 'layout.json')]
        src = form.get('source', {})
        parent = form.get('parent')
        pdf = folder / 'look' / 'original.pdf'
        if not pdf.exists() and parent and re.fullmatch(r'hf\d+', parent):
            pdf = root / parent / 'look' / 'original.pdf'
        if not pdf.exists() and src.get('source_file'):
            pdf = source / 'docgen' / src['source_file']
        if pdf.exists() and not pdf.resolve().is_relative_to(source.resolve()):
            raise ValueError('Source PDF must stay inside the checkout')
        native = fields.get('fields', fields.get('items', []))
        inherited = False
        if not native and parent and (root / parent / 'fields.json').exists():
            fields = read(root / parent / 'fields.json')
            native = fields.get('items', [])
            inherited = True
        entries = list(native.values()) if isinstance(native, dict) else native
        family = parent if parent and re.fullmatch(r'hf\d+', parent) else folder.name
        pages = src.get('source_pages')
        if pages is None:
            pages = [p['source_page'] - 1 for p in form.get('reconstruction', {}).get('pages', [])]
        if not pages:
            pages = list(range(len(layout.get('pages', []))))
        digest = sha(pdf) if pdf.is_file() else None
        row = {'id': folder.name, 'group': folder.name.split('_')[0] if not folder.name.startswith('hf') else 'hf',
               'title': form.get('name') or layout.get('name') or folder.name,
               'category': form.get('group') or layout.get('class'), 'family': family,
               'source_commit': commit, 'source_folder': str(folder.relative_to(source)),
               'source_url': src.get('url'), 'source_pdf': str(pdf.relative_to(source)) if pdf.is_file() else None,
               'source_pdf_sha256': digest, 'declared_sha256': src.get('sha256'),
               'source_hash_matches': digest == src['sha256'] if digest and src.get('sha256') else None,
               'source_pages_zero_based': pages, 'field_entries': len(entries),
               'row_cell_hints': sum(bool(e.get('row')) for e in entries if isinstance(e, dict)),
               'check_hints': sum(e.get('t') == 'check' or e.get('type') in ('bool', 'choice', 'checkbox') for e in entries if isinstance(e, dict)),
               'field_hints_inherited_from': parent if inherited else None,
               'metadata_available': bool(form or layout), 'selection_status': 'reserve',
               'split': 'unassigned', 'human_review': 'pending'}
        rows.append(row)
    # Family is a conservative connected component of explicit parent links and PDF identity.
    owner = {}
    for row in rows:
        digest = row['source_pdf_sha256']
        if digest:
            owner.setdefault(digest, row['family'])
    for row in rows:
        if row['source_pdf_sha256']:
            row['family'] = owner[row['source_pdf_sha256']]
    return rows


def build(source, out, selection, dpi=120):
    import fitz
    source, out = Path(source).resolve(), Path(out)
    if out.exists():
        raise ValueError('출력 폴더가 이미 있습니다. 새 폴더를 지정하세요.')
    spec = read(Path(selection))
    rows = inventory(source)
    by_id = {r['id']: r for r in rows}
    chosen = spec['items']
    ids = [x['id'] for x in chosen]
    source_ids = [x.get('source_id', x['id']) for x in chosen]
    if len(ids) != len(set(ids)) or any(x not in by_id for x in source_ids) or any(not re.fullmatch(r'[a-z0-9_]+', x) for x in ids):
        raise ValueError('중복 또는 없는 서식 ID')
    selected, families, seen_pages = [], set(), set()
    base = Path(spec['base_dataset']) if spec.get('base_dataset') else None
    base_manifest = read(base / 'manifest.json') if base else None
    base_items = {r['id']: r for r in base_manifest['items']} if base_manifest else {}
    for pick, source_id in zip(chosen, source_ids):
        row = copy.deepcopy(by_id[source_id])
        declared = row['source_pages_zero_based']
        explicit = pick.get('page')
        if not row['source_pdf'] or explicit is None and len(declared) != 1:
            raise ValueError(f"{source_id}: 원본 PDF가 없거나 페이지 선택이 필요합니다")
        if explicit is not None and (type(explicit) is not int or explicit < 1 or explicit - 1 not in declared):
            raise ValueError(f"{source_id}: 이 서식 범위 밖의 PDF 페이지")
        number = explicit - 1 if explicit is not None else declared[0]
        with fitz.open(source / row['source_pdf']) as pdf:
            if number >= len(pdf):
                raise ValueError(f"{source_id}: PDF 페이지 범위 오류")
        if row['source_hash_matches'] is False:
            raise ValueError(f"{source_id}: 원본 PDF 해시 불일치")
        aliases = {r['id'] for r in rows if r['family'] == row['family']}
        page_key = (row['source_pdf_sha256'], number)
        if page_key in seen_pages or aliases.intersection(spec.get('excluded_development_families', [])):
            raise ValueError(f"{source_id}: 중복 페이지 또는 개발에 사용한 서식 계열")
        seen_pages.add(page_key)
        families.add(row['family'])
        row.update(id=pick['id'], source_id=source_id, selection_status='proposed',
                   declared_source_pages_zero_based=declared, source_pages_zero_based=[number],
                   form_page_one_based=declared.index(number) + 1,
                   proposed_tier=pick['tier'], selection_reason=pick['reason'],
                   complexity_tags=pick.get('complexity_tags', []), raster_dpi=pick.get('dpi', dpi))
        if type(row['raster_dpi']) is not int or not 72 <= row['raster_dpi'] <= 300:
            raise ValueError('DPI는 72~300 정수여야 합니다')
        if row['id'] in base_items:
            old = base_items[row['id']]
            if (old['source_commit'] != row['source_commit'] or old['source_pdf_sha256'] != row['source_pdf_sha256']
                or old['input_page_one_based'] != number + 1 or old['raster_dpi'] != row['raster_dpi']
                or sha(base / row['id'] / 'image.png') != old['image_sha256']):
                raise ValueError('기존 후보의 출처 또는 이미지가 변경되었습니다')
        row['family_members'] = sorted(aliases)
        selected.append(row)
    family_counts = Counter(r['family'] for r in selected)
    for row in selected:
        row['family_page_count'] = family_counts[row['family']]
        row['family_weight'] = 1 / family_counts[row['family']]
    out.mkdir(parents=True)
    for row in selected:
        folder = out / row['id']
        folder.mkdir()
        with fitz.open(source / row['source_pdf']) as pdf:
            number = row['source_pages_zero_based'][0]
            page = pdf[number]
            row.update(pdf_total_pages=len(pdf), input_page_one_based=number + 1,
                       width_pt=round(page.rect.width, 2), height_pt=round(page.rect.height, 2),
                       text_char_count=len(page.get_text().strip()), input_kind='official_blank_form_pdf',
                       rasterizer=f'PyMuPDF {fitz.VersionBind}')
            if row['id'] in base_items:
                shutil.copyfile(base / row['id'] / 'image.png', folder / 'image.png')
                row['rasterizer'] = base_items[row['id']]['rasterizer']
            else:
                page.get_pixmap(dpi=row['raster_dpi'], alpha=False).save(folder / 'image.png')
            row['image_sha256'] = sha(folder / 'image.png')
            (folder / 'source_text.txt').write_text('\n'.join(line.expandtabs(4).rstrip() for line in page.get_text().splitlines()).rstrip() + '\n', encoding='utf-8')
        origin = source / row['source_folder']
        hint_source = source / 'docgen/forms' / (row['field_hints_inherited_from'] or row['source_id']) / 'fields.json'
        if hint_source.exists():
            shutil.copyfile(hint_source, folder / 'source_fields.json')
        write(folder / 'meta.json', {**row, 'tier': row['proposed_tier'], 'reference_status': 'not_created',
                                    'note': '원본 서식 채택 후보. source_fields는 검수 참고자료이며 정답 계약이 아닙니다.'})
    for row in rows:
        if row['id'] in source_ids:
            row['selection_status'] = 'proposed'
            row['selected_inputs'] = [r['id'] for r in selected if r['source_id'] == row['id']]
        else:
            row['selection_reason'] = ('원본/메타데이터 없음' if not row['source_pdf'] or not row['metadata_available'] else
                                       '다중 페이지: 이번 후보에 명시적으로 선택하지 않은 서식' if len(row['source_pages_zero_based']) != 1 else
                                       '개발에 사용한 계열 또는 선택 후보와 같은 원본' if row['family'] in families or row['family'] in spec.get('excluded_development_families', []) else
                                       '이번 선정 범위 밖의 예비 후보')
    write(out / 'inventory.json', rows)
    manifest = {'version': 1, 'name': spec['name'], 'status': 'proposed', 'source_repository': REPO_URL,
                'source_commit': rows[0]['source_commit'], 'inventory_counts': dict(Counter(r['group'] for r in rows)),
                'selected_counts': dict(Counter(r['group'] for r in selected)), 'items': selected,
                'source_form_count': len(set(source_ids)), 'family_count': len(families),
                'description': spec.get('description', ''),
                'notes': ['난이도는 제안이며 사람 검수로 확정합니다.', 'hana와 hf는 모두 하나은행 계열입니다.',
                          '원본 PDF 이미지만 준비했습니다. 합성값 생성이나 기준 HTML 생성·승인은 수행하지 않았습니다.',
                          '같은 family 및 유사 서식은 개발/테스트에 나누지 마세요. 자동 family는 알려진 출처 관계만 묶습니다.']}
    write(out / 'manifest.json', manifest)
    template = (Path(__file__).parent / 'templates' / 'candidates.html').read_text(encoding='utf-8')
    # Inline manifest supports file:// viewing; escape script terminators from source text.
    payload = json.dumps(manifest, ensure_ascii=False).replace('<', '\\u003c')
    (out / 'index.html').write_text(template.replace('__MANIFEST__', payload), encoding='utf-8')
    lines = [f'# gov · hana · hf 평가 후보 {len(selected)}쪽 ({len(set(source_ids))}개 소스 서식)', '', '**사람 최종 선정 전 후보 세트입니다. 기준 HTML은 아직 없습니다.**', '',
             f"소스 커밋: [{manifest['source_commit']}]({REPO_URL}/commit/{manifest['source_commit']})", '',
             '로컬에서 `index.html`을 열면 원본·선정 사유·계열·검수 항목을 볼 수 있습니다. 채택/보류/제외와 메모를 기록하고 결정을 JSON으로 내려받으세요.', '',
             '전체 원본 목록과 1차 제외 사유는 `inventory.json`, 후보 메타데이터는 `manifest.json`에 있습니다.', '',
             '## 사람이 확인할 것', '',
             '- 실제 업무 대표성, 판독 가능성, 문서 전체 포함 여부',
             '- 같은 양식의 개정판·유사 동의서 중복, 기존 학습/개발 노출 여부',
             '- 반복 표인지 고정 격자인지, 필수 필드 누락, 빈칸 해석',
             '- 난이도와 개발/테스트 분할은 미지정입니다. 같은 family의 모든 페이지를 함께 묶습니다.',
             '- 다중 페이지에서 고른 한 장의 재현 평가이며 문서 전체 연결 평가는 아닙니다.',
             '- source_fields.json은 원본 서식 전체의 참고 정의입니다. 선택 페이지의 필드를 따로 검수하세요.',
             '- 페이지 평균은 많이 뽑은 서식을 과대 반영합니다. 계열 내 평균 후 계열 간 평균도 함께 보세요. family_weight를 기록했으며 기존 evaluate는 아직 페이지 평균입니다.',
             '- 빈 원본만으로 부족한 값 추출 평가는 별도 합성값 입력 세트로 보완', '',
             '## 채택 이후', '',
             '```bash', 'python tools/prepare_form_candidates.py promote \\',
             f'  --candidates {out.as_posix()} --decisions decisions.json --out evalset/forms_selected_v1', '```', '',
             '채택 문서의 image.png/meta.json만 새 폴더로 옮깁니다. 모델로 기준 초안을 생성해 reference/에 넣고, `python -m tplgen review evalset/forms_selected_v1`에서 별도로 승인하세요.', '',
             'source_fields.json과 source_text.txt는 원본 추출 참고자료이며 검수된 정답이 아닙니다. 기존 document_gen HTML은 절대 배치·전용 helper를 사용하므로 현재 tplgen 규격의 정답으로 그대로 복사하지 않습니다.', '',
             '원본 PDF를 메타데이터의 raster_dpi(기본 120, 고난도 추가분 160) PNG로 변환했을 뿐 고객 값을 합성하거나 원본에 추가하지 않았습니다. 합성값 문서는 소스 저장소 지침에 따라 studio에서 준비해야 합니다.', '',
             '| ID | 이름 | 난이도(제안) | 선정 이유 |', '|---|---|---|---|']
    for row in selected:
        lines.append(f"| [{row['id']}]({row['id']}/image.png) | {row['title'].replace('|', '/')} | {row['proposed_tier']} | {row['selection_reason']} |")
    lines += ['', '후보 화면을 로컬 웹으로 열려면 다음 명령 후 `http://127.0.0.1:8766`에 접속하세요.', '',
              '```bash', f'python -m http.server 8766 --bind 127.0.0.1 --directory {out.as_posix()}', '```']
    (out / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return manifest


def promote(candidates, decisions, out):
    candidates, out = Path(candidates), Path(out)
    if out.exists():
        raise ValueError('출력 폴더가 이미 있습니다. 새 폴더를 지정하세요.')
    manifest, decision = read(candidates / 'manifest.json'), read(Path(decisions))
    if decision.get('source_commit') != manifest['source_commit'] or decision.get('name') != manifest['name']:
        raise ValueError('다른 후보 세트의 검수 파일입니다')
    if not decision.get('reviewer', '').strip():
        raise ValueError('검수자가 필요합니다')
    picks = decision.get('items', {})
    known = {r['id'] for r in manifest['items']}
    if set(picks) - known:
        raise ValueError('알 수 없는 문서 ID')
    chosen = [r for r in manifest['items'] if picks.get(r['id'], {}).get('decision') == 'keep']
    if not chosen:
        raise ValueError('채택 문서가 없습니다')
    for row in chosen:
        if not all(picks[row['id']].get('checks', {}).get(k) is True for k in ('legible', 'representative', 'duplicates', 'fields')):
            raise ValueError('검수 확인란이 누락되었습니다: ' + row['id'])
        if sha(candidates / row['id'] / 'image.png') != row['image_sha256'] or picks[row['id']].get('image_sha256') != row['image_sha256']:
            raise ValueError('이미지가 변경되었습니다. 재검수하세요: ' + row['id'])
    out.mkdir(parents=True)
    for row in chosen:
        folder = out / row['id']
        folder.mkdir()
        shutil.copyfile(candidates / row['id'] / 'image.png', folder / 'image.png')
        write(folder / 'meta.json', {**read(candidates / row['id'] / 'meta.json'), 'selection_status': 'selected',
                                    'selection_review': picks[row['id']], 'selection_reviewer': decision['reviewer'],
                                    'reference_status': 'not_created'})
    write(out / 'selection.json', decision)
    return len(chosen)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    commands = ap.add_subparsers(dest='command', required=True)
    b = commands.add_parser('build')
    b.add_argument('--source', required=True)
    b.add_argument('--selection', default='evalset/selections/forms_pilot_v1.json')
    b.add_argument('--out', default='evalset/forms_candidates_v1')
    p = commands.add_parser('promote')
    p.add_argument('--candidates', required=True)
    p.add_argument('--decisions', required=True)
    p.add_argument('--out', required=True)
    a = ap.parse_args()
    try:
        result = build(a.source, a.out, a.selection) if a.command == 'build' else promote(a.candidates, a.decisions, a.out)
        print(json.dumps(result.get('selected_counts') if isinstance(result, dict) else {'selected': result}, ensure_ascii=False))
    except ValueError as e:
        raise SystemExit(str(e)) from e


if __name__ == '__main__':
    main()
