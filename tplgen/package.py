"""템플릿 꾸러미: template.html (Jinja2) · schema.json · sample.json 읽기·쓰기·규칙 검사.

규칙의 본문은 prompts/template_v1.md. 여기서는 그려 보지 않고 알 수 있는 것만 검사한다 (그려 보는 검사는 check.py).
모델이 쓴 템플릿은 믿을 수 없는 입력이다 → Jinja2 는 sandbox 로만 돌리고, script·외부 참조는 막는다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from jinja2 import TemplateError
from jinja2.sandbox import SandboxedEnvironment

FILES = ("template.html", "schema.json", "sample.json")
TYPES = {"text", "name", "company", "date", "year", "month", "day", "amount", "number", "phone", "account", "idnum", "address", "email", "bool", "choice", "sign", "seal"}
NAME = re.compile(r"[a-z][a-z0-9_]*")
MARK = re.compile(r"^=== *(template\.html|schema\.json|sample\.json) *=== *$", re.M)
THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
FENCE = re.compile(r"^\s*```[a-zA-Z0-9]*\s*\n(.*?)\n```\s*$", re.S)
FORBIDDEN = {"script": re.compile(r"<\s*script\b", re.I), "external": re.compile(r"""(?:src|href)\s*=\s*["']?\s*(?:https?:|//|file:)|@import|url\(""", re.I),
             "embed": re.compile(r"<\s*(?:iframe|object|embed|link|img)\b", re.I)}
ENV = SandboxedEnvironment(autoescape=True)


def split(answer: str) -> dict[str, str]:
    """모델 답 → {파일이름: 내용}. `=== 파일이름 ===` 줄로 나눈다. 코드 울타리는 벗긴다."""
    text = THINK.sub("", answer or "")
    marks = list(MARK.finditer(text))
    parts = {}
    for m, nxt in zip(marks, marks[1:] + [None]):
        body = text[m.end():nxt.start() if nxt else len(text)].strip()
        fenced = FENCE.match(body)
        parts[m.group(1)] = (fenced.group(1) if fenced else body).strip() + "\n"
    return parts


def save(parts: dict[str, str], folder) -> None:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        (folder / name).write_text(parts.get(name, ""), encoding="utf-8")


def load(folder) -> dict:
    """꾸러미 폴더 → {"template", "schema", "sample", "issues"}. 읽을 수 없는 것은 issues 에 적고 빈 값으로 둔다."""
    folder, issues = Path(folder), []
    read = lambda n: (folder / n).read_text(encoding="utf-8-sig") if (folder / n).is_file() else ""
    pkg = {"template": read("template.html"), "schema": {}, "sample": {}}
    for key, name in (("schema", "schema.json"), ("sample", "sample.json")):
        try:
            pkg[key] = json.loads(read(name))
            if not isinstance(pkg[key], dict):
                raise ValueError
        except ValueError:
            pkg[key] = {}
            issues.append(f"bad_json:{name}" if read(name).strip() else f"missing:{name}")
    if not pkg["template"].strip():
        issues.append("missing:template.html")
    pkg["issues"] = issues + (validate(pkg) if not issues else [])
    return pkg


def columns(table: dict) -> list[dict]:
    return [c for c in table.get("columns") or [] if isinstance(c, dict)]


def validate(pkg: dict) -> list[str]:
    """그려 보지 않고 아는 규칙 위반의 목록 (없으면 빈 목록)."""
    issues, t, schema, sample = [], pkg["template"], pkg["schema"], pkg["sample"]
    issues += [f"forbidden:{k}" for k, rx in FORBIDDEN.items() if rx.search(t)]
    if 'class="page"' not in t and "class='page'" not in t:
        issues.append("no_page")
    try:
        ENV.from_string(t)
    except TemplateError as e:
        issues.append(f"template_error:{type(e).__name__}:{str(e)[:80]}")
    fields, tables = schema.get("fields"), schema.get("tables")
    if not isinstance(fields, list) or not isinstance(tables, list):
        return issues + ["schema_shape"]

    def entry(e, where):
        if not isinstance(e, dict) or not NAME.fullmatch(str(e.get("name", ""))):
            issues.append(f"bad_name:{where}")
            return False
        if e.get("type") not in TYPES:
            issues.append(f"bad_type:{where}.{e['name']}")
        if e.get("type") == "choice" and not (isinstance(e.get("options"), list) and e["options"]):
            issues.append(f"no_options:{where}.{e['name']}")
        return True
    names = []
    for f in fields:
        if entry(f, "fields"):
            names.append(f["name"])
            if f["name"] not in sample:
                issues.append(f"sample_missing:{f['name']}")
            if not re.search(rf'data-field=["\']{f["name"]}["\']', t):
                issues.append(f"not_in_template:{f['name']}")
    for tb in tables:
        if not entry({**tb, "type": "text"} if isinstance(tb, dict) else tb, "tables"):
            continue
        names.append(tb["name"])
        if not columns(tb):
            issues.append(f"no_columns:{tb['name']}")
        rows = sample.get(tb["name"])
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            issues.append(f"sample_missing:{tb['name']}")
        if not re.search(rf'data-field=["\']{tb["name"]}\.\{{\{{\s*loop\.index0\s*\}}\}}\.', t):
            issues.append(f"no_row_loop:{tb['name']}")
        for c in columns(tb):
            entry(c, tb["name"])
    if len(set(names)) != len(names):
        issues.append("duplicate_name")
    if not names:
        issues.append("no_fields")
    return issues


def html(pkg: dict, data: dict) -> str:
    """템플릿에 값을 넣은 HTML. 없는 값은 빈 글자로 나온다."""
    return ENV.from_string(pkg["template"]).render(**data)


def paths(schema: dict, data: dict) -> list[str]:
    """이 값으로 그리면 있어야 하는 data-field 경로들."""
    out = [f["name"] for f in schema.get("fields") or [] if isinstance(f, dict) and "name" in f]
    for tb in schema.get("tables") or []:
        for i, _ in enumerate(data.get(tb.get("name")) or []):
            out += [f"{tb['name']}.{i}.{c['name']}" for c in columns(tb) if "name" in c]
    return out
