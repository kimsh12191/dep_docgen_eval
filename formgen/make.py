"""이미지 한 장 → svg 서식 (값 자리를 표시한 빈 서식). 벤치마크(bench.py)도 이 함수를 그대로 부른다.

0회차: 지시문(prompts/svg_v1.md) + 이미지 → svg.
1회차부터 (rounds ≥ 1, 셀프 고치기): 원본 이미지 + 직전 svg 를 그린 그림(값 자리는 빨간 상자로 덧그림) + 직전 svg 원문·규격 검사 결과
  → 고친 svg 전체 (prompts/svg_v1_fix.md). 정답은 쓰지 않는다.
out/round<k>/ 에 쓰는 것:  out.svg · raw.txt (모델 답 그대로) · make.json (설정·시간·토큰·규격 검사) · view.png (다음 회차에 보여준 그림)

실행: python -m formgen make --config configs/example.json --name A --image x.png --out drafts/x [--rounds 2]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from . import config, llm, svg

PROMPT_VERSION = "svg_v1"
FIX_VERSION = "svg_v1_fix"
ASK = "이 문서를 빈 SVG 서식으로 만드세요. SVG만 출력하세요."
THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
SVG_BLOCK = re.compile(r"<svg\b.*?</svg\s*>", re.S)
FIELD_TAG = re.compile(r"<rect\b([^>]*\bdata-field=[^>]*?)\s*/>")


def prompt_text(version: str) -> str:
    return (Path(__file__).parent / "prompts" / f"{version}.md").read_text(encoding="utf-8")


def extract_svg(text: str) -> str:
    """모델 답에서 svg 를 꺼낸다. 생각 글(<think>)은 버리고, svg 가 여럿이면 가장 긴 것. 없으면 답 전체 (→ 규격 검사에서 걸린다)."""
    text = THINK.sub("", text or "")
    blocks = SVG_BLOCK.findall(text)
    return max(blocks, key=len) if blocks else text


def show_fields(value: str) -> str:
    """값 자리 rect 를 빨간 테두리로 보이게 바꾼다 (피드백 그림용)."""
    return FIELD_TAG.sub(lambda m: "<rect" + re.sub(r'\s(fill|stroke|stroke-width)="[^"]*"', "", m.group(1))
                         + ' fill="none" stroke="red" stroke-width="1.5"/>', value)


def feedback(value: str, folder: Path, font_files=None) -> tuple[list[dict], dict]:
    """직전 svg → (모델에 보낼 내용 조각, 기록). 그릴 수 없으면 글만 보낸다."""
    checked = svg.parse(value)
    info = {"issues": checked["issues"], "fields": len(checked["fields"]), "texts": len(checked["texts"]), "picture": False}
    parts = []
    if checked["valid"]:
        try:
            svg.render(show_fields(value), folder / "view.png", font_files, scale=2)
            parts.append(llm.image_part(folder / "view.png"))
            info["picture"] = True
        except Exception as e:   # resvg_py 없음·글꼴 없음 등 → 글만
            info["picture_error"] = f"{type(e).__name__}: {e}"[:200]
    text = (prompt_text(FIX_VERSION).replace("{picture}", "있음" if info["picture"] else "없음 (그릴 수 없었음)")
            .replace("{issues}", ", ".join(info["issues"]) or "없음").replace("{fields}", str(info["fields"]))
            .replace("{texts}", str(info["texts"])).replace("{svg}", value))
    return parts + [{"type": "text", "text": text}], info


def make(image, out, m: dict, rounds: int = 0, font_files=None, answers: list[str] | None = None) -> list[dict]:
    """회차마다 make.json 내용의 목록. m = 설정의 모델 항목. answers 를 주면 모델 대신 회차마다 그 글을 답으로 쓴다 (길 검사용)."""
    out, logs, value = Path(out), [], None
    image_sha = hashlib.sha256(Path(image).read_bytes()).hexdigest() if Path(image).is_file() else None
    for k in range(rounds + 1):
        d = out / f"round{k}"
        d.mkdir(parents=True, exist_ok=True)
        info = None
        if k == 0:
            user = [llm.image_part(image) if Path(image).is_file() else {"type": "text", "text": "(이미지 없음)"}, {"type": "text", "text": ASK}]
        else:
            parts, info = feedback(value, out / f"round{k - 1}", font_files)
            user = [llm.image_part(image)] + parts
        if answers is not None:
            response = {"text": answers[min(k, len(answers) - 1)], "finish_reason": "stop", "seconds": 0.0, "usage": {}}
        else:
            messages = [{"role": "system", "content": prompt_text(PROMPT_VERSION)}, {"role": "user", "content": user}]
            response = llm.chat(m["endpoint"], m["model"], messages, max_tokens=m["max_tokens"], temperature=m["temperature"],
                                timeout=m["timeout"], api_key=config.api_key(m), extra=m["extra"])
        raw = response.pop("text", "") or ""
        value = extract_svg(raw)
        (d / "raw.txt").write_text(raw, encoding="utf-8")
        (d / "out.svg").write_text(value, encoding="utf-8")
        checked = svg.parse(value)
        truncated = response.get("finish_reason") == "length"
        log = {**response, "round": k, "feedback": info,
               "valid": checked["valid"] and not response.get("error") and not truncated, "issues": checked["issues"], "truncated": truncated,
               "model": m.get("model") or "mock", "prompt": PROMPT_VERSION if k == 0 else FIX_VERSION,
               "max_tokens": m["max_tokens"], "temperature": m["temperature"], "extra": m["extra"],
               "image": Path(image).name, "image_sha256": image_sha, "svg_bytes": len(value.encode("utf-8"))}
        (d / "make.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        logs.append(log)
        if response.get("error"):
            break
    return logs


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m formgen make", description="이미지 한 장 → 값 자리를 표시한 svg 서식")
    ap.add_argument("--config", required=True, help="설정 파일 (configs/example.json 꼴)")
    ap.add_argument("--name", required=True, help="설정의 models 중 쓸 모델 name")
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rounds", type=int, default=None, help="셀프 고치기 횟수 (없으면 설정 파일의 값)")
    a = ap.parse_args(argv)
    cfg = config.load(a.config)
    m = config.pick(cfg, a.name)
    if m["mock"]:
        raise SystemExit("mock 모델은 정답이 있는 bench 에서만 씁니다")
    logs = make(a.image, a.out, m, cfg["rounds"] if a.rounds is None else a.rounds, cfg["font_files"])
    for log in logs:
        print(f"round{log['round']}: valid={log['valid']} issues={log['issues']} tokens={(log.get('usage') or {}).get('completion_tokens')} "
              f"{log.get('seconds')}s {log.get('error') or ''}")
    print(Path(a.out) / f"round{logs[-1]['round']}" / "out.svg")


if __name__ == "__main__":
    main()
