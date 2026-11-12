"""docgen 서식 → 평가 항목 (그림 + 정답 html). 평가 세트를 만들 때 한 번 쓴다 (docgen·브라우저 필요).

항목 폴더 <out>/<id>/
  image.png   서식을 값까지 채워 그린 그림 1쪽 (모델의 입력)
  ref.html    정답 html: 같은 서식의 html 에서 값을 지우고 값 자리를 규격(docs/legacy/HTML_SPEC.md)의 표시로 바꾼 것
  meta.json   출처·seed·난이도

docgen 이 그린 html 은 값 자리를 <span class="fv" data-field=…>값</span>, 체크 보기를 data-opt, 도장·서명을 data-mark 로 적는다.
그것을 브라우저 안에서 규격의 표시로 바꾼다:
  값        <span data-field data-label data-type></span>                    (안의 값은 지움)
  체크      보기들 앞에 <span data-field data-type="checkbox" data-options="a|b"></span> 하나, 상자는 모두 □
  도장·서명 <span data-field data-type="seal|signature"></span>               (그림은 지움)

실행: DOCGEN_ROOT=… python -m tools.docgen.export_items --pool data/roundtrip_pool_v0.json --out bench/roundtrip_v0
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from formgen.html import difficulty, htmldoc

from .bridge import Renderer, docgen_root
from .sheet import type7

JS = r"""
(info) => {
  const mk = (key, type, options) => {
    const m = document.createElement('span');
    const meta = info[key] || {};
    m.setAttribute('data-field', key);
    m.setAttribute('data-label', meta.label || '');
    m.setAttribute('data-type', type || meta.type || 'text');
    if (options) m.setAttribute('data-options', options.join('|'));
    return m;
  };
  // 체크 보기 묶음
  const groups = new Map();
  document.querySelectorAll('[data-opt]').forEach(el => {
    const key = el.getAttribute('data-opt').split('#')[0];
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(el);
  });
  for (const [key, els] of groups) {
    const options = els.map(el => {
      const c = el.cloneNode(true);
      c.querySelectorAll('[data-box]').forEach(b => b.remove());
      return c.textContent.replace(/\s+/g, ' ').trim();
    }).filter(Boolean);
    els.forEach(el => {
      el.querySelectorAll('[data-box]').forEach(b => { b.textContent = '□'; b.removeAttribute('data-box'); });
      el.querySelectorAll('[data-field]').forEach(f => f.replaceWith(document.createTextNode(f.textContent)));
      el.removeAttribute('data-opt');
    });
    els[0].parentNode.insertBefore(mk(key, 'checkbox', options), els[0]);
  }
  document.querySelectorAll('[data-box]').forEach(b => b.removeAttribute('data-box'));
  // 도장·서명
  Array.from(document.querySelectorAll('[data-mark]')).forEach(el => {
    const key = el.getAttribute('data-mark');
    const type = (info[key] && info[key].type) || (key.startsWith('sign') ? 'signature' : 'seal');
    el.parentNode.insertBefore(mk(key, type), el);
    el.removeAttribute('data-mark');
    if (/\b(scribble|seal|sigimg|stamp)\b/.test(el.className || '')) el.setAttribute('data-drop', '1');
  });
  document.querySelectorAll('[data-drop]').forEach(el => el.remove());
  // 값
  document.querySelectorAll('[data-field]').forEach(el => {
    if (el.hasAttribute('data-type')) return;
    const key = el.getAttribute('data-field');
    const meta = info[key] || {};
    el.setAttribute('data-label', meta.label || '');
    el.setAttribute('data-type', meta.type || 'text');
    el.textContent = '';
  });
  ['data-pg-format', 'data-pg-cont'].forEach(a => document.querySelectorAll('[' + a + ']').forEach(el => el.removeAttribute(a)));
  return '<!doctype html>\n' + document.documentElement.outerHTML;
}
"""


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tools.docgen.export_items")
    ap.add_argument("--pool", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--structure", default="varies", help="pool 에서 이 structure 인 서식만 (표·흐름으로 짠 코드 서식 = varies)")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)
    root = docgen_root()
    from docgen.entities import make_profile
    from docgen.registry import load_all
    from docgen.render import render
    from playwright.sync_api import sync_playwright

    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    pool = [x for x in json.loads(Path(a.pool).read_text(encoding="utf-8")) if x.get("structure") == a.structure]
    if a.limit:
        pool = pool[:a.limit]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    reg, index, skipped = load_all(), [], []
    with Renderer(out / "_cache") as R, sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception:
            browser = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = browser.new_page()
        for n, x in enumerate(pool):
            doc_id = x["id"]
            label = R.form(doc_id, a.seed)
            if len(label["images"]) != 1:
                skipped.append((doc_id, f"{len(label['images'])}쪽"))
                continue
            info = {f["key"]: {"label": f.get("label") or "", "type": type7(f.get("type"))} for f in label["fields"]}
            html = render(reg[doc_id], make_profile(a.seed), a.seed)[0]
            page.set_content(html)
            ref = page.evaluate(JS, info)
            doc = htmldoc.parse(ref)
            if not doc["fields"]:
                skipped.append((doc_id, "값 자리 없음"))
                continue
            d = out / doc_id
            d.mkdir(exist_ok=True)
            shutil.copyfile(Path(label["_dir"]) / label["images"][0], d / "image.png")
            (d / "ref.html").write_text(ref, encoding="utf-8")
            diff = difficulty.of_html(ref)
            meta = {"id": doc_id, "name": label["doc_name"], "group": label["group"], "source": "docgen-roundtrip",
                    "docgen_commit": commit, "seed": a.seed, "layout": (label.get("template_variant") or {}).get("id"),
                    "image": {"width": label["pages"][0]["width"], "height": label["pages"][0]["height"], "fill": "filled"},
                    "label_fields": len(label["fields"]), "ref_issues": sorted({c for c, _ in doc["issues"]}), **diff}
            (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            index.append({"id": doc_id, "tier": diff["tier"], "why": diff["why"], **diff["features"]})
            print(f"[{n + 1}/{len(pool)}] {doc_id} {diff['tier']} {diff['features']} issues={meta['ref_issues']}", flush=True)
        browser.close()
    shutil.rmtree(out / "_cache", ignore_errors=True)
    (out / "index.json").write_text(json.dumps({"items": index, "skipped": skipped, "docgen_commit": commit, "seed": a.seed,
                                                "difficulty_rule": difficulty.VERSION}, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print("items", len(index), "tiers", dict(Counter(i["tier"] for i in index)), "skipped", skipped)


if __name__ == "__main__":
    main()
