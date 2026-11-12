"""1단계: 난이도 기준 v0 을 저장소의 html·코드 서식(템플릿이 있는 것)에 적용해 분포를 본다.

서식마다 seed 0 으로 그려서 (docgen.preview) 라벨에서 쪽 수·칸 수·칸 종류를, 그린 html 에서 표 병합 칸 수·글자 수를 센다.
실행: cd <document_gen> && python3 <이 파일> <결과 폴더>
"""
import json
import re
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

from docgen.entities import make_profile
from docgen.preview import Previewer
from docgen.registry import load_all
from docgen.render import render

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
FORMS = Path("docgen/forms")

SPAN = re.compile(r'(?:rowspan|colspan)\s*=\s*["\']?(\d+)', re.I)
TAG = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.S | re.I)

# 기준 v0 (문서 "요소 1"). 하나라도 윗단계면 윗단계.
def tier(pages, fields, spans, checks):
    def lv(x, mid, high):
        return 2 if x >= high else 1 if x >= mid else 0
    parts = {"pages": 2 if pages >= 2 else 0, "fields": lv(fields, 11, 31), "spans": lv(spans, 3, 11), "checks": lv(checks, 3, 11)}
    top = max(parts.values())
    return "하중상"[top], [k for k, v in parts.items() if v == top and top > 0]


def main():
    reg = load_all()
    ids = sorted(d.name for d in FORMS.iterdir() if (d / "look" / "template.html.j2").is_file() and d.name in reg)
    missing = sorted(d.name for d in FORMS.iterdir() if (d / "look" / "template.html.j2").is_file() and d.name not in reg)
    print(f"templates in registry: {len(ids)}  (template but not registered: {len(missing)} {missing[:5]})", flush=True)
    pv = Previewer(str(OUT / "pv"))
    rows, types = [], Counter()
    try:
        for i, doc_id in enumerate(ids):
            t0 = time.time()
            rec = {"id": doc_id, "name": reg[doc_id].name, "group": reg[doc_id].group}
            try:
                label = pv.render(doc_id, seed=0)
                fl = label["fields"]
                tc = Counter(f.get("type") for f in fl)
                types.update(tc)
                html, _, _ = render(reg[doc_id], make_profile(0), 0)
                body = html[html.find("<body"):] if "<body" in html else html
                spans = sum(1 for n in SPAN.findall(body) if int(n) > 1)
                text = re.sub(r"\s+", "", TAG.sub("", body))
                checks = sum(v for k, v in tc.items() if k in ("checkbox", "check", "choice", "agree"))
                marks = sum(v for k, v in tc.items() if k in ("seal", "signature", "sign", "stamp"))
                rec.update(pages=len(label["images"]), fields=len(fl), checks=checks, marks=marks, spans=spans,
                           tables=len(re.findall(r"<table\b", body, re.I)), chars=len(text), html_kb=round(len(html) / 1024),
                           overflow=bool(label.get("overflow")), variant=(label.get("template_variant") or {}).get("id"),
                           types=dict(tc), image=label["images"][0])
                rec["tier"], rec["why"] = tier(rec["pages"], rec["fields"], rec["spans"], rec["checks"])
            except Exception as e:  # 서식 하나가 실패해도 계속
                rec["error"] = f"{type(e).__name__}: {e}"[:300]
                traceback.print_exc(limit=1)
            rec["sec"] = round(time.time() - t0, 1)
            rows.append(rec)
            print(f"[{i + 1}/{len(ids)}] {doc_id} {rec.get('tier', 'ERR')} {({k: rec.get(k) for k in ('pages', 'fields', 'checks', 'spans', 'chars')})} {rec['sec']}s", flush=True)
    finally:
        pv.close()
    (OUT / "difficulty_v0.json").write_text(json.dumps({"rows": rows, "types": dict(types)}, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = [r for r in rows if "error" not in r]
    print("\ntypes:", dict(types))
    print("errors:", len(rows) - len(ok))
    print("tier:", dict(Counter(r["tier"] for r in ok)))
    print("why (윗단계로 올린 기준):", dict(Counter(w for r in ok for w in r["why"])))


if __name__ == "__main__":
    main()
