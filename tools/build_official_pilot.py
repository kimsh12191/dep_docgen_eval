"""Download official originals and adapt existing source-compared HTML into review candidates.

Requires PyMuPDF, Jinja2, BeautifulSoup4 and Playwright (system Chrome supported).
Never promotes imported annotations to human-verified gold automatically.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import urllib.request

import pymupdf as fitz
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup, escape
from playwright.sync_api import sync_playwright


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def build(forms, out, executable, ids=None):
    selection = [('gov_pension', '하', '필드 6개, 단순 단일 페이지'),
                 ('gov_business_proof', '중', '인적사항과 사업자 정보, 여러 기재 구역'),
                 ('gov_income', '상', '밀집된 소득 표, 반복 구역과 분할 날짜 필드')]
    if ids:
        selection = [(name, None, 'Unclassified: source-level annotation review required') for name in ids]
    index = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 794, "height": 1123}, device_scale_factor=2)
        page.route('**/*', lambda route: route.continue_() if route.request.url.startswith('file:') else route.abort())
        for name, tier, reason in selection:
            source_dir, dest = forms / name, out / name
            dest.mkdir(parents=True, exist_ok=True)
            info = json.loads((source_dir / 'form.json').read_text(encoding='utf-8'))
            definitions = json.loads((source_dir / 'fields.json').read_text(encoding='utf-8')).get('fields', {})
            url = info['source']['url']
            with urllib.request.urlopen(url, timeout=60) as response:
                pdf = response.read()
            if not pdf.startswith(b'%PDF'):
                raise ValueError(f'Not a PDF: {url}')
            digest = hashlib.sha256(pdf).hexdigest()
            if digest != info['source']['sha256']:
                raise ValueError(f'Source changed: {name}; review version before importing')
            (dest / 'source.pdf').write_bytes(pdf)
            doc = fitz.open(stream=pdf, filetype='pdf')
            source_page_index = info['source'].get('source_pages', [0])[0]
            source_page = doc[source_page_index]
            source_page.get_pixmap(matrix=fitz.Matrix(8/3, 8/3)).save(dest / 'image.png')
            text_dict = source_page.get_text('dict')
            text_dict['blocks'] = [b for b in text_dict['blocks'] if b['type'] == 0]
            dump(dest / 'source_text.json', text_dict)
            env = Environment(loader=FileSystemLoader([str(source_dir / 'look'), str(forms / '_common/templates')]), undefined=StrictUndefined)
            used = []
            def field(key, label=None, **kwargs):
                f = definitions[key]
                typ = f.get('type', 'text')
                if key in {'official.issued', 'official.first_joined', 'official.qual'}:
                    typ = 'date'
                if key in {'official.salary', 'official.tax', 'official.salary_income'}:
                    typ = 'amount'
                used.append({'key': key, 'label': label or f['label'], 'type': typ,
                             'scope': 'document_instance', 'required': True, 'review_status': 'candidate'})
                return Markup(f'<span data-field="{escape(key)}" data-label="{escape(label or f["label"])}" data-type="{typ}"></span>')
            field.set_corr_name = lambda value: ''
            html = env.get_template('template.html.j2').render(spec=info, d={'items':[]}, f=field)
            soup = BeautifulSoup(html, 'html.parser')
            for el in soup.select('script, .sample-mark'):
                el.decompose()
            # Keep just the explicit source page; these pilot selections are single-page.
            for extra_page in soup.select('.page')[1:]:
                extra_page.decompose()
            style = soup.new_tag('style')
            style.string = '.entry [data-field]{width:100%;height:100%;min-height:12px}.page{margin:0!important}'
            soup.head.append(style)
            (dest / 'ref.html').write_text(str(soup), encoding='utf-8')
            page.goto((dest / 'ref.html').resolve().as_uri())
            page.evaluate('''() => { for(const e of document.querySelectorAll('.printed')) {
                const w=e.getBoundingClientRect().width, target=Number(e.dataset.width);
                if(w>0 && target>0)e.style.transform=`scaleX(${target/w})`;
            }}''')
            (dest / 'ref.html').write_text(page.content(), encoding='utf-8')
            page.screenshot(path=str(dest / 'ref.png'), full_page=True)
            boxes = page.locator('[data-field]').evaluate_all('''els=>els.map(e=>{const r=e.getBoundingClientRect();return {key:e.dataset.field,label:e.dataset.label,type:e.dataset.type,bbox:[r.x,r.y,r.width,r.height]}})''')
            dump(dest / 'fields.json', {'fields':used, 'rendered_fields':boxes, 'coordinate_space':'CSS pixels at 96 dpi'})
            meta = {'id':name, 'name':info['name'], 'tier':tier, 'tier_reason':reason,
                    'difficulty_rule':'official-pilot-expert-v0 (provisional)', 'source':info['source'],
                    'downloaded_at':'2026-11-12', 'download_sha256':digest,
                    'input_kind':'official_blank_pdf_raster', 'source_page':source_page_index+1,
                    'source_page_count':len(doc), 'item_scope':'one source page, not the entire multipage form',
                    'reference_origin':'adapted_local_official_compared_html',
                    'review_status':'candidate', 'gold_approved':False,
                    'limitations':['Official blank form, not a real filled scan',
                                   'Inherited field coverage needs independent annotation review',
                                   'Some printed glyphs are SVG paths, so DOM text scores are incomplete'],
                    'rights_status':'publicly downloadable; redistribution license not established'}
            dump(dest / 'meta.json', meta)
            index.append(meta)
            print(name, digest, len(used), flush=True)
        browser.close()
    dump(out / 'manifest.json', index)


if __name__ == '__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--forms', type=Path, required=True)
    ap.add_argument('--out', type=Path, default=Path('bench/official_pilot_v1'))
    ap.add_argument('--browser', default='C:/Program Files/Google/Chrome/Application/chrome.exe')
    ap.add_argument('--ids', nargs='+', help='Explicit source form IDs; no inherited tier assignment')
    args=ap.parse_args()
    build(args.forms, args.out, args.browser, args.ids)
