"""이미지 한 장 → html (값 자리를 표시한 서식). 벤치마크(bench.py)도 이 함수를 그대로 부른다.

프로토콜
  P1  한 번에 만든다.
  P2  P1 뒤에, 규격 검사에서 나온 문제를 글로 돌려주고 고쳐 쓰게 한다 (최대 rounds 번 더).
모델은 '그림 + 글 → html' 만 한다. 반복과 검사는 여기서 돌린다.

실행: python -m formgen make --image x.png --endpoint http://host:8000/v1 --model NAME --out drafts/x
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from . import htmldoc, llm
from .validate import feedback, validate

PROMPT_VERSION = "v1"
ASK = "이 서류 이미지를 규칙대로 html 로 만드세요. html 만 출력합니다."
FIX = "방금 만든 html 을 검사하니 아래 문제가 있습니다. 문제를 고쳐서 전체 html 을 처음부터 끝까지 다시 출력하세요.\n\n{issues}"
FENCE = re.compile(r"```(?:html)?\s*(.*?)```", re.S | re.I)
THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def prompt_text(version: str = PROMPT_VERSION) -> str:
    return (Path(__file__).parent / "prompts" / f"{version}.md").read_text(encoding="utf-8")


def extract_html(text: str) -> tuple[str, list]:
    """모델 답에서 html 을 꺼낸다. (html, 문제 목록). </html> 로 끝나지 않으면 잘린 것으로 본다."""
    text = THINK.sub("", text or "")
    fenced = FENCE.findall(text)
    if fenced:
        text = max(fenced, key=len)
    low = text.lower()
    start = min([i for i in (low.find("<!doctype"), low.find("<html")) if i >= 0], default=0)
    end = low.rfind("</html>")
    issues = []
    if end < 0:
        issues.append(("truncated", "</html> 로 끝나지 않습니다 (출력이 잘렸거나 html 이 아님)"))
        html = text[start:]
    else:
        html = text[start:end + len("</html>")]
    return html.strip(), issues


def make(image: str | Path, out_dir: str | Path, endpoint: str = "", model: str = "", protocol: str = "P1", rounds: int = 2,
         max_tokens: int = 16000, temperature: float = 0.0, prompt_version: str = PROMPT_VERSION, api_key: str | None = None,
         mock: str | None = None, timeout: float = 1800) -> dict:
    """out_dir 에 out.html · raw_<회차>.txt · make.json 을 쓰고 make.json 내용을 돌려준다.
    mock 을 주면 모델을 부르지 않고 그 글을 모델의 답으로 쓴다 (길 검사용)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    messages = [{"role": "system", "content": prompt_text(prompt_version)},
                {"role": "user", "content": [llm.image_part(image), {"type": "text", "text": ASK}]}]
    log = {"image": str(image), "model": model, "protocol": protocol, "prompt": prompt_version, "max_tokens": max_tokens,
           "temperature": temperature, "calls": [], "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    html, issues, doc = "", [], None
    for turn in range(1 + (rounds if protocol == "P2" else 0)):
        res = {"text": mock, "finish_reason": "stop", "usage": {}, "seconds": 0.0} if mock is not None else \
            llm.chat(endpoint, model, messages, max_tokens=max_tokens, temperature=temperature, api_key=api_key, timeout=timeout)
        call = {k: res.get(k) for k in ("finish_reason", "usage", "seconds", "error")}
        log["calls"].append(call)
        if res.get("error"):
            break
        (out / f"raw_{turn + 1}.txt").write_text(res["text"], encoding="utf-8")
        html, issues = extract_html(res["text"])
        if res.get("finish_reason") == "length" and not any(c == "truncated" for c, _ in issues):
            issues.append(("truncated", "출력 토큰 한도에 걸렸습니다"))
        doc = htmldoc.parse(html)
        fb = feedback(doc, issues)
        call["issues"] = len(fb)
        if protocol != "P2" or not fb or mock is not None:
            break
        messages += [{"role": "assistant", "content": res["text"]}, {"role": "user", "content": FIX.format(issues="\n".join(fb))}]
    (out / "out.html").write_text(html, encoding="utf-8")
    v = validate(doc, issues) if doc is not None else {"valid": False, "invalid_why": ["request_error"], "bad_fields": 0, "issue_counts": {}}
    log.update(valid=v["valid"], invalid_why=v["invalid_why"], issue_counts=v["issue_counts"], rounds_used=len(log["calls"]),
               error=next((c["error"] for c in log["calls"] if c.get("error")), None),
               seconds=round(sum(c.get("seconds") or 0 for c in log["calls"]), 2),
               prompt_tokens=sum((c.get("usage") or {}).get("prompt_tokens") or 0 for c in log["calls"]),
               completion_tokens=sum((c.get("usage") or {}).get("completion_tokens") or 0 for c in log["calls"]),
               truncated=any(c == "truncated" for c, _ in issues), html_bytes=len(html.encode("utf-8")))
    (out / "make.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    return log


def main(argv=None):
    ap = argparse.ArgumentParser(prog="formgen make", description="이미지 한 장 → 값 자리를 표시한 html")
    ap.add_argument("--image", required=True)
    ap.add_argument("--endpoint", required=True, help="OpenAI 호환 주소, /v1 까지 (예: http://host:8000/v1)")
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--protocol", default="P1", choices=["P1", "P2"])
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--api-key", default=None)
    a = ap.parse_args(argv)
    log = make(a.image, a.out, a.endpoint, a.model, a.protocol, a.rounds, a.max_tokens, api_key=a.api_key)
    print(json.dumps({k: log[k] for k in ("valid", "invalid_why", "issue_counts", "rounds_used", "seconds", "completion_tokens", "truncated", "error")},
                     ensure_ascii=False))
    print(Path(a.out) / "out.html")


if __name__ == "__main__":
    main()
