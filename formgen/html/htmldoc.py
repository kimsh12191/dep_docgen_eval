"""html 한 파일 → 채점용 요약 (파이썬 표준 라이브러리만 쓴다. 브라우저 없음).

doc = {
  "texts":  [인쇄 문구 조각],                 값 자리 안의 글자, script·style·head 는 뺀다
  "tables": [[칸, …], …],                    칸 = {text, nfields, r0, r1, c0, c1}  (rowspan·colspan 을 푼 격자)
  "fields": [값 자리, …],                    {key, label, type, kind, options, own, left, up, before, prev, next, rank, in_table}
  "issues": [(코드, 설명), …],                규격에서 벗어난 것 (validate.py 가 유효성으로 정리)
}

값 자리 = data-field 속성이 붙은 요소 (docs/legacy/HTML_SPEC.md). 표에서 연속으로 같은 꼴인 행(빈 반복 행)은 한 번만 남긴다.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

from . import tables as T

TYPES = ("text", "number", "amount", "date", "checkbox", "seal", "signature")
KIND = {"checkbox": "check", "seal": "mark", "signature": "mark"}
KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_*]+)*$")
VOID = {"br", "hr", "img", "input", "col", "meta", "link", "wbr", "area", "base", "embed", "source", "track"}
SKIP = {"script", "style", "head", "title", "template", "noscript"}
BLOCK = {"p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "th", "table", "section", "article",
         "header", "footer", "br", "hr", "caption", "thead", "tbody", "tfoot", "dd", "dt", "blockquote", "pre", "form", "fieldset"}
EXTERNAL = re.compile(r"^\s*(https?:)?//", re.I)


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.texts, self.fields, self.issues, self.done = [], [], [], []
        self.stack = []                 # 열려 있는 표
        self.skip, self.fopen = 0, None  # 버리는 요소 깊이 / 열려 있는 값 자리 [태그, 겹침 수]
        self.recent = ""                # 같은 덩어리(문단·칸) 안에서 지금까지 나온 글자
        self.n_tags = 0

    def _cell(self):
        return self.stack[-1]["cell"] if self.stack else None

    def handle_starttag(self, tag, attrs):
        self.n_tags += 1
        a = dict(attrs)
        if tag == "script":
            self.issues.append(("script", "<script> 는 쓸 수 없습니다"))
        for k in ("src", "href"):
            if a.get(k) and EXTERNAL.match(a[k]):
                self.issues.append(("external", f"외부 주소를 쓸 수 없습니다: {a[k][:60]}"))
        if tag in SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag in BLOCK:
            self.recent = ""
        if tag == "table":
            self.stack.append({"rows": [], "row": None, "cell": None})
        elif self.stack and tag == "tr":
            t = self.stack[-1]
            t["row"], t["cell"] = [], None
            t["rows"].append(t["row"])
        elif self.stack and tag in ("td", "th"):
            t = self.stack[-1]
            if t["row"] is None:
                t["row"] = []
                t["rows"].append(t["row"])
            t["cell"] = {"text": [], "frefs": [], "rowspan": T.to_int(a.get("rowspan")), "colspan": T.to_int(a.get("colspan"))}
            t["row"].append(t["cell"])
        if self.fopen:
            if tag == self.fopen[0]:
                self.fopen[1] += 1
            return
        if "data-field" in a:
            f = {"key": (a.get("data-field") or "").strip(), "label": (a.get("data-label") or "").strip(),
                 "type": (a.get("data-type") or "").strip().lower(),
                 "options": [o.strip() for o in (a.get("data-options") or "").split("|") if o.strip()],
                 "before": self.recent[-40:], "order": len(self.fields), "cell": self._cell(), "pos": len(self.texts)}
            self.fields.append(f)
            cell = self._cell()
            if cell is not None:
                cell["frefs"].append(f)
                cell["text"].append(T.FIELD)
            if tag not in VOID:
                self.fopen = [tag, 0]

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if self.fopen and tag == self.fopen[0]:
            if self.fopen[1] == 0:
                self.fopen = None
            else:
                self.fopen[1] -= 1
        if tag in BLOCK:
            self.recent = ""
        if not self.stack:
            return
        t = self.stack[-1]
        if tag in ("td", "th"):
            t["cell"] = None
        elif tag == "tr":
            t["row"], t["cell"] = None, None
        elif tag == "table":
            self.done.append(self.stack.pop()["rows"])

    def handle_data(self, data):
        if self.skip or self.fopen:
            return
        s = " ".join(data.split())
        if not s:
            return
        self.texts.append(s)
        self.recent += s + " "
        cell = self._cell()
        if cell is not None:
            cell["text"].append(s)


def _static(text: str) -> str:
    return " ".join(text.replace(T.FIELD, " ").split())


def _neighbor(cells, cell, axis):
    """왼쪽(axis='c') 또는 위(axis='r')로 가며 인쇄 문구가 있는 가장 가까운 칸의 글자."""
    lo, hi, olo, ohi = (("c0", "c1", "r0", "r1") if axis == "c" else ("r0", "r1", "c0", "c1"))
    best = None
    for other in cells:
        if other is cell or other[hi] >= cell[lo] or not (other[olo] <= cell[ohi] and cell[olo] <= other[ohi]):
            continue
        if not _static(other["text"]):
            continue
        if best is None or other[hi] > best[hi]:
            best = other
    return _static(best["text"]) if best else ""


def parse(html: str) -> dict:
    p = _Parser()
    try:
        p.feed(html)
        p.close()
    except Exception as e:   # 표준 파서는 거의 실패하지 않지만, 실패하면 빈 문서로 본다
        return {"texts": [], "tables": [], "fields": [], "issues": [("parse", f"{type(e).__name__}: {e}")], "n_tags": 0}
    rows_open = [t["rows"] for t in p.stack]   # 닫히지 않은 표 (잘린 출력)
    if rows_open:
        p.issues.append(("unclosed_table", "닫히지 않은 <table> 이 있습니다 (출력이 잘렸을 수 있음)"))
    tables, dropped = [], set()
    for rows in p.done + rows_open:
        cells = T.grid(rows)
        cells, gone = T.collapse_rows(cells)
        dropped |= {id(f) for f in gone}
        if cells:
            tables.append(cells)
    fields = []
    cell_of = {id(f): (cells, c) for cells in tables for c in cells for f in c["frefs"]}
    for f in p.fields:
        if id(f) in dropped:
            continue
        t = f["type"] if f["type"] in TYPES else "text"
        out = {"key": f["key"], "label": f["label"], "type": t, "kind": KIND.get(t, "value"), "options": f["options"],
               "before": " ".join(f["before"].split()), "own": "", "left": "", "up": "", "in_table": False,
               "prev": p.texts[f["pos"] - 1][-20:] if f["pos"] > 0 else "", "next": p.texts[f["pos"]][:20] if f["pos"] < len(p.texts) else ""}
        hit = cell_of.get(id(f))
        if hit:
            cells, c = hit
            out.update(own=_static(c["text"]), left=_neighbor(cells, c, "c"), up=_neighbor(cells, c, "r"), in_table=True)
        if not f["key"]:
            p.issues.append(("field_key", "data-field 값이 비어 있습니다"))
        elif not KEY.match(f["key"]):
            p.issues.append(("field_key", f"키 형식이 다릅니다: {f['key'][:40]}"))
        if f["type"] not in TYPES:
            p.issues.append(("field_type", f"data-type 이 없거나 모르는 종류입니다: {f['key'][:40]} ({f['type'] or '없음'})"))
        if not f["label"]:
            p.issues.append(("field_label", f"data-label 이 없습니다: {f['key'][:40]}"))
        if t == "checkbox" and not f["options"]:
            p.issues.append(("field_options", f"체크 칸에 data-options 가 없습니다: {f['key'][:40]}"))
        fields.append(out)
    for i, f in enumerate(fields):
        f["rank"] = i / (len(fields) - 1) if len(fields) > 1 else 0.0
    for cells in tables:
        for c in cells:
            c.pop("frefs", None)
    return {"texts": p.texts, "tables": tables, "fields": fields, "issues": p.issues, "n_tags": p.n_tags}
