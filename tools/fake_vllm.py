"""가짜 vLLM 서버 (OpenAI 호환 /v1/chat/completions). 모델 없이 make·bench 의 HTTP 길을 확인할 때 쓴다.
늘 --answer 파일의 내용을 답으로 준다. 이미지가 없는 요청은 400.

  python tools/fake_vllm.py --port 8099 --answer bench/official_pilot_v1/gov_pension/ref.svg
  python -m formgen make --image bench/official_pilot_v1/gov_pension/image.png --endpoint http://127.0.0.1:8099/v1 --model fake --out drafts/x
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--answer", required=True, help="늘 이 파일의 내용을 답으로 준다")
    a = ap.parse_args()
    answer = Path(a.answer).read_text(encoding="utf-8")

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            parts = [p for m in body.get("messages", []) if isinstance(m.get("content"), list) for p in m["content"]]
            images = sum(1 for p in parts if p.get("type") == "image_url" and p["image_url"]["url"].startswith("data:image/"))
            out = {"choices": [{"message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 1000 * images, "completion_tokens": len(answer) // 3}, "model": body.get("model")}
            data = json.dumps(out).encode("utf-8")
            self.send_response(200 if self.path.endswith("/chat/completions") and images else 400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    HTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
