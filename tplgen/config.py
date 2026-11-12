"""실행 설정 파일(json). 모델 목록 · vLLM 옵션 · 고치기 횟수를 한 파일에 둔다. 예: configs/example.json

{
  "images": "samples",                 bench 가 쓸 입력 이미지 폴더 (*.png, *.jpg)
  "out": "runs/exp1",                  bench 결과 폴더. <out>/<모델 name>/<이미지 이름>/
  "rounds": 2,                         셀프 고치기 횟수. 0 = 한 번만 생성
  "defaults": {...},                   모든 모델에 공통인 호출 옵션
  "models": [{"name": "A", "endpoint": "http://host:8000/v1", "model": "served-name", ...}, ...]
}
모델 항목: name · endpoint · model · max_tokens · temperature · timeout · api_key_env(키가 든 환경변수 이름)
          · extra(요청 본문에 그대로 더함: top_p, repetition_penalty, chat_template_kwargs 등)
          · mock(모델 없이 길 검사: 회차마다 답으로 쓸 파일 경로를 쉼표로. 모자라면 마지막을 반복)
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

MODEL_DEFAULTS = {"max_tokens": 32000, "temperature": 0.0, "timeout": 1800, "api_key_env": None, "extra": {}, "mock": None}
MODEL_KEYS = {"name", "endpoint", "model", *MODEL_DEFAULTS}
TOP_KEYS = {"images", "out", "rounds", "defaults", "models"}


def load(path_or_dict) -> dict:
    raw = path_or_dict if isinstance(path_or_dict, dict) else json.loads(Path(path_or_dict).read_text(encoding="utf-8"))
    if set(raw) - TOP_KEYS:
        raise SystemExit(f"설정에 모르는 키: {sorted(set(raw) - TOP_KEYS)}")
    defaults = raw.get("defaults") or {}
    if set(defaults) - MODEL_KEYS:
        raise SystemExit(f"defaults 에 모르는 키: {sorted(set(defaults) - MODEL_KEYS)}")
    models = []
    for m in raw.get("models") or []:
        if set(m) - MODEL_KEYS:
            raise SystemExit(f"모델 {m.get('name')} 에 모르는 키: {sorted(set(m) - MODEL_KEYS)}")
        merged = {**MODEL_DEFAULTS, **defaults, **m, "extra": {**defaults.get("extra", {}), **m.get("extra", {})}}
        if not re.fullmatch(r"[\w.-]+", merged.get("name") or ""):
            raise SystemExit(f"모델 name 은 폴더 이름으로 쓸 수 있는 글자만: {merged.get('name')!r}")
        if not merged["mock"] and not (merged.get("endpoint") and merged.get("model")):
            raise SystemExit(f"모델 {merged['name']}: endpoint 와 model 이 필요합니다")
        models.append(merged)
    names = [m["name"] for m in models]
    if not models or len(set(names)) != len(names):
        raise SystemExit("models 가 비었거나 name 이 겹칩니다")
    return {"images": raw.get("images", "samples"), "out": raw.get("out", "runs/exp"), "rounds": int(raw.get("rounds", 0)), "models": models}


def api_key(m: dict) -> str | None:
    return os.environ.get(m["api_key_env"]) if m.get("api_key_env") else None


def pick(cfg: dict, name: str) -> dict:
    for m in cfg["models"]:
        if m["name"] == name:
            return m
    raise SystemExit(f"설정에 없는 모델: {name} (있는 것: {', '.join(m['name'] for m in cfg['models'])})")
