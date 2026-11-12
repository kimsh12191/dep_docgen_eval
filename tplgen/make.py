"""이미지 한 장 → 템플릿 꾸러미. 모델을 부르고, 만든 꾸러미를 실제로 돌려 본 결과를 다시 보여 주며 고치게 한다 (셀프 고치기 루프).

0회차: 지시문(prompts/template_v1.md) + 이미지 → 꾸러미
k회차: 원본 이미지 + 직전 꾸러미를 예시 값으로 그린 그림 + 규칙 검사·시험 결과 + 직전 파일 → 고친 꾸러미 (prompts/template_v1_fix.md)
회차마다 check 로 잰다 (정답이 필요 없는 점수라 루프 안에서 써도 된다). final 은 그중 점수가 가장 좋은 회차다.

out/round<k>/  template.html · schema.json · sample.json · raw.txt(모델 답 그대로) · make.json(설정·시간·토큰·점수) · tests/(시험마다 그린 그림)
out/final/     가장 좋은 회차의 꾸러미 (template.html · schema.json · sample.json) + result.json

실행: python -m tplgen make --config configs/local.json --name A --image x.png --out out/x [--rounds 2]
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from . import check as C, config, llm, package as P
from .render import Renderer

PROMPT, FIX = "template_v1", "template_v1_fix"
ASK = "이 문서 이미지를 템플릿 꾸러미로 만드세요. 세 파일만 출력하세요."


def prompt_text(version: str) -> str:
    return (Path(__file__).parent / "prompts" / f"{version}.md").read_text(encoding="utf-8")


def feedback(folder: Path, result: dict) -> list[dict]:
    """직전 회차 → 모델에 보낼 내용 조각 (그림이 있으면 그림 + 글)."""
    view = folder / "tests" / "sample.png"
    tests = "\n".join(f"- {name}: " + (", ".join(problems[:12]) + (" …" if len(problems) > 12 else "") if problems else "이상 없음")
                      for name, problems in result["tests"].items()) or "- 규칙 위반으로 그려 보지 못함"
    files = "\n".join(f"=== {n} ===\n" + ((folder / n).read_text(encoding="utf-8") if (folder / n).is_file() else "") for n in P.FILES)
    text = (prompt_text(FIX).replace("{picture}", "있음" if view.is_file() else "없음 (그릴 수 없었음)")
            .replace("{issues}", ", ".join(result["issues"]) or "없음").replace("{tests}", tests).replace("{files}", files))
    return ([llm.image_part(view)] if view.is_file() else []) + [{"type": "text", "text": text}]


def rank(result: dict) -> tuple:
    """회차를 고르는 순서. 닮음은 0.05 단위로만 본다 (그보다 작은 차이는 점수의 오차다 → 같으면 뒤 회차를 고른다)."""
    return (result["pass"], result["valid"], result["robust"], -result["leak"], -int((result.get("missing") or 0.0) * 20), int((result["layout"] or 0.0) * 20))


def make(image, out, m: dict, rounds: int = 0, renderer: Renderer | None = None) -> list[dict]:
    """회차마다의 기록(make.json 내용) 목록. m = 설정의 모델 항목."""
    out, logs, result = Path(out), [], None
    mock = [Path(p.strip()).read_text(encoding="utf-8") for p in m["mock"].split(",")] if m.get("mock") else None
    own = renderer is None
    r = renderer or Renderer().__enter__()
    try:
        for k in range(rounds + 1):
            d = out / f"round{k}"
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True)
            user = [llm.image_part(image)] + ([{"type": "text", "text": ASK}] if k == 0 else feedback(out / f"round{k - 1}", result))
            if mock:
                response = {"text": mock[min(k, len(mock) - 1)], "finish_reason": "stop", "seconds": 0.0, "usage": {}}
            else:
                messages = [{"role": "system", "content": prompt_text(PROMPT)}, {"role": "user", "content": user}]
                response = llm.chat(m["endpoint"], m["model"], messages, max_tokens=m["max_tokens"], temperature=m["temperature"],
                                    timeout=m["timeout"], api_key=config.api_key(m), extra=m["extra"])
            raw = response.pop("text", "") or ""
            (d / "raw.txt").write_text(raw, encoding="utf-8")
            P.save(P.split(raw), d)
            result = C.check(d, image, d / "tests", r)
            if response.get("finish_reason") == "length":
                result["issues"].append("truncated")
            log = {**response, "round": k, "model": m.get("model") or "mock", "prompt": PROMPT if k == 0 else FIX, "max_tokens": m["max_tokens"],
                   "temperature": m["temperature"], "extra": m["extra"], "image": Path(image).name, "pictures_sent": sum(p["type"] == "image_url" for p in user),
                   "result": result}
            (d / "make.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
            logs.append(log)
            if response.get("error"):
                break
    finally:
        if own:
            r.__exit__()
    best = max(logs, key=lambda g: (rank(g["result"]), g["round"]))
    final = out / "final"
    if final.exists():
        shutil.rmtree(final)
    final.mkdir(parents=True)
    for n in P.FILES:
        shutil.copy(out / f"round{best['round']}" / n, final / n)
    (final / "result.json").write_text(json.dumps({"round": best["round"], **best["result"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    return logs


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m tplgen make", description="이미지 한 장 → 템플릿 꾸러미")
    ap.add_argument("--config", required=True)
    ap.add_argument("--name", required=True, help="설정의 models 중 쓸 모델 name")
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rounds", type=int, default=None, help="셀프 고치기 횟수 (없으면 설정 파일의 값)")
    a = ap.parse_args(argv)
    cfg = config.load(a.config)
    logs = make(a.image, a.out, config.pick(cfg, a.name), cfg["rounds"] if a.rounds is None else a.rounds)
    for g in logs:
        print(f"round{g['round']}: {C.brief(g['result'])}  토큰={(g.get('usage') or {}).get('completion_tokens')} {g.get('seconds')}s {g.get('error') or ''}")
    print("final =", Path(a.out) / "final", f"(round{json.loads((Path(a.out) / 'final' / 'result.json').read_text(encoding='utf-8'))['round']})")


if __name__ == "__main__":
    main()
