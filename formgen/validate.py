"""유효성(L0): 만든 html 이 규격(SPEC.md)대로 읽히는가. 채점 전에 보고, 고쳐 쓰기(P2)에서는 모델에게 돌려준다.

못 쓰는 것 (valid = False)
  empty           인쇄 문구도 값 자리도 없다
  no_fields       값 자리(data-field)가 하나도 없다
  script          <script> 가 있다
  external        외부 주소(src·href 가 http…)를 쓴다
  unclosed_table  <table> 이 닫히지 않았다 (출력이 잘렸을 때)
  truncated       </html> 로 끝나지 않는다 (make.py 가 원문을 보고 더한다)
고칠 것 (valid 는 그대로, 개수만 센다)
  field_key · field_type · field_label · field_options
"""
from __future__ import annotations

from collections import Counter

FATAL = ("empty", "no_fields", "script", "external", "unclosed_table", "truncated", "parse")


def validate(doc: dict, extra_issues: list | None = None) -> dict:
    issues = list(doc.get("issues") or []) + list(extra_issues or [])
    if not doc["fields"] and not doc["texts"]:
        issues.append(("empty", "내용이 없습니다"))
    elif not doc["fields"]:
        issues.append(("no_fields", "값 자리(data-field)가 하나도 없습니다"))
    codes = Counter(c for c, _ in issues)
    fatal = [c for c in FATAL if codes.get(c)]
    return {"valid": not fatal, "invalid_why": fatal, "bad_fields": sum(v for c, v in codes.items() if c.startswith("field_")),
            "issue_counts": dict(codes)}


def feedback(doc: dict, extra_issues: list | None = None, limit: int = 12) -> list[str]:
    """모델에게 돌려줄 글 (중복 없이, 많으면 앞의 몇 개만)."""
    seen, out = set(), []
    for code, msg in list(doc.get("issues") or []) + list(extra_issues or []):
        line = f"[{code}] {msg}"
        if line not in seen:
            seen.add(line)
            out.append(line)
    if not doc["fields"]:
        out.append("[no_fields] 값 자리(data-field)가 하나도 없습니다")
    return out[:limit]
