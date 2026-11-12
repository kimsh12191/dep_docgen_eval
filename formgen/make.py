"""이미지 한 장 → svg 서식 (값 자리를 표시한 빈 서식). 벤치마크(bench.py)도 이 함수를 그대로 부른다.

모델은 OpenAI 호환 주소(vLLM)로 한 번 부른다 (P1). 프롬프트는 prompts/svg_v1.md.
out 폴더에 쓰는 것:  out.svg (꺼낸 svg) · raw.txt (모델 답 그대로) · make.json (설정·시간·토큰·규격 검사 결과)

실행: python -m formgen make --image x.png --endpoint http://host:8000/v1 --model NAME --out drafts/x
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from . import llm, svg

PROMPT_VERSION = "svg_v1"
ASK = "이 문서를 빈 SVG 서식으로 만드세요. SVG만 출력하세요."
THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
SVG_BLOCK = re.compile(r"<svg\b.*?</svg\s*>", re.S)


def prompt_text(version: str = PROMPT_VERSION) -> str:
    return (Path(__file__).parent / "prompts" / f"{version}.md").read_text(encoding="utf-8")


def extract_svg(text: str) -> str:
    """모델 답에서 svg 를 꺼낸다. 생각 글(<think>)은 버리고, svg 가 여럿이면 가장 긴 것. 없으면 답 전체 (→ 규격 검사에서 걸린다)."""
    text = THINK.sub("", text or "")
    blocks = SVG_BLOCK.findall(text)
    return max(blocks, key=len) if blocks else text


def dump(path, value) -> None:
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def make(image, out, endpoint: str = "", model: str = "", max_tokens: int = 16000, api_key: str | None = None,
         temperature: float = 0.0, mock: str | None = None, timeout: float = 1800) -> dict:
    """make.json 내용을 돌려준다. mock 을 주면 모델을 부르지 않고 그 글을 모델의 답으로 쓴다 (길 검사용)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if mock is not None:
        response = {"text": mock, "finish_reason": "stop", "seconds": 0.0, "usage": {}}
    else:
        messages = [{"role": "system", "content": prompt_text()},
                    {"role": "user", "content": [llm.image_part(image), {"type": "text", "text": ASK}]}]
        response = llm.chat(endpoint, model, messages, max_tokens=max_tokens, temperature=temperature, api_key=api_key, timeout=timeout)
    raw = response.pop("text", "") or ""
    value = extract_svg(raw)
    (out / "raw.txt").write_text(raw, encoding="utf-8")
    (out / "out.svg").write_text(value, encoding="utf-8")
    checked = svg.parse(value)
    truncated = response.get("finish_reason") == "length"
    log = {**response,
           "valid": checked["valid"] and not response.get("error") and not truncated,
           "issues": checked["issues"], "truncated": truncated,
           "model": model or "mock", "prompt": PROMPT_VERSION, "protocol": "P1", "max_tokens": max_tokens, "temperature": temperature,
           "image": Path(image).name, "image_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest() if Path(image).is_file() else None,
           "svg_bytes": len(value.encode("utf-8"))}
    dump(out / "make.json", log)
    return log


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m formgen make", description="이미지 한 장 → 값 자리를 표시한 svg 서식")
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--endpoint", required=True, help="OpenAI 호환 주소, /v1 까지 (예: http://host:8000/v1). 실서류는 사내 모델 주소만")
    ap.add_argument("--model", required=True)
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--api-key", default=None)
    a = ap.parse_args(argv)
    log = make(a.image, a.out, a.endpoint, a.model, a.max_tokens, a.api_key)
    print(json.dumps(log, ensure_ascii=False, indent=2))
    print(Path(a.out) / "out.svg")


if __name__ == "__main__":
    main()
