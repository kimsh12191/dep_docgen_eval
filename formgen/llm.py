"""모델 부르기: OpenAI 호환 /chat/completions (vLLM). 표준 라이브러리(urllib)만 쓴다."""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def image_part(path: str | Path) -> dict:
    p = Path(path)
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{MIME.get(p.suffix.lower(), 'image/png')};base64,{data}"}}


def chat(endpoint: str, model: str, messages: list[dict], max_tokens: int = 16000, temperature: float = 0.0,
         timeout: float = 1800, api_key: str | None = None, extra: dict | None = None) -> dict:
    """{"text", "finish_reason", "usage": {prompt_tokens, completion_tokens}, "seconds"} 또는 {"error": …}.
    endpoint 는 '/v1' 까지 (예: http://host:8000/v1)."""
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature, **(extra or {})}
    req = urllib.request.Request(endpoint.rstrip("/") + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {api_key}"} if api_key else {})})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}", "seconds": round(time.time() - t0, 2)}
    except Exception as e:   # 연결 실패·시간 초과 등
        return {"error": f"{type(e).__name__}: {e}"[:400], "seconds": round(time.time() - t0, 2)}
    try:
        choice = out["choices"][0]
        text = choice["message"].get("content") or ""
        if isinstance(text, list):   # 조각으로 오는 서버
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    except (KeyError, IndexError, TypeError):
        return {"error": f"응답 꼴이 다릅니다: {json.dumps(out, ensure_ascii=False)[:300]}", "seconds": round(time.time() - t0, 2)}
    usage = out.get("usage") or {}
    return {"text": text, "finish_reason": choice.get("finish_reason"), "seconds": round(time.time() - t0, 2),
            "usage": {"prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens")}}
