"""값을 넣은 HTML → 이미지(png) + 라벨(값마다 위치) + 깨진 곳 목록. 브라우저 엔진(Playwright Chromium)으로 그린다.

with Renderer() as r:
    out = r.render(html_text, "x.png")
    out = {"width", "height", "labels": [{"field", "text", "box": [x, y, w, h]}], "assets": [{"kind", "box"}], "problems": [...]}
좌표는 .page 왼쪽 위 기준의 CSS px (이미지는 scale 배). 페이지의 script 는 꺼 두고, 네트워크 요청은 모두 막는다.

problems (값을 바꿔 그렸을 때 깨졌는지):
  no_page            .page 가 없다
  overflow_x         쪽보다 내용이 넓다
  outside:<경로>      값이 쪽 밖으로 나갔다
  clipped:<경로|태그>  칸보다 내용이 커서 잘리거나 삐져나왔다
  overlap:<a>|<b>    서로 다른 값 둘이 겹쳤다
"""
from __future__ import annotations

from pathlib import Path
import os

JS = r"""
() => {
  const page = document.querySelector('.page');
  if (!page) return {problems: ['no_page'], labels: [], assets: [], width: 0, height: 0};
  const p = page.getBoundingClientRect(), problems = [];
  const box = e => { const r = e.getBoundingClientRect(); return [r.left - p.left, r.top - p.top, r.width, r.height].map(v => Math.round(v * 10) / 10); };
  const els = [...page.querySelectorAll('[data-field]')];
  const visible = e => {
    if (!e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.right > p.left && r.left < p.right && r.bottom > p.top && r.top < p.bottom;
  };
  const labels = els.map(e => ({field: e.getAttribute('data-field'), text: e.innerText.trim(), box: box(e), visible: visible(e)}));
  const walker = document.createTreeWalker(page, NodeFilter.SHOW_TEXT), fixed = [];
  while (walker.nextNode()) {
    const node = walker.currentNode, parent = node.parentElement;
    if (!parent.closest('[data-field], [data-asset], style, script') && visible(parent)) fixed.push(node.textContent);
  }
  const fixed_text = fixed.join(' ').replace(/\s+/g, ' ').trim();
  const assets = [...page.querySelectorAll('[data-asset]')].map(e => ({kind: e.getAttribute('data-asset'), box: box(e)}));
  let right = 0;
  for (const e of page.querySelectorAll('*')) { const r = e.getBoundingClientRect(); if (r.width > 0) right = Math.max(right, r.right); }
  if (page.scrollWidth > page.clientWidth + 2 || right > p.right + 2) problems.push('overflow_x');
  labels.forEach(l => { const [x, y, w, h] = l.box; if (x < -2 || y < -2 || x + w > p.width + 2 || y + h > p.height + 2) problems.push('outside:' + l.field); });
  for (const e of page.querySelectorAll('td, th, div, p, span[data-field]')) {
    if (e === page || e.clientWidth === 0) continue;
    if (e.scrollWidth > e.clientWidth + 2 || e.scrollHeight > e.clientHeight + 2)
      problems.push('clipped:' + (e.getAttribute('data-field') || e.tagName.toLowerCase() + (e.className ? '.' + String(e.className).split(' ')[0] : '')));
  }
  const frags = els.map(e => [...e.getClientRects()].filter(r => r.width > 0 && r.height > 0));   // 줄이 넘어간 값은 줄 조각마다 본다
  for (let i = 0; i < els.length; i++) for (let j = i + 1; j < els.length; j++) {
    if (els[i].contains(els[j]) || els[j].contains(els[i])) continue;
    let hit = false;
    for (const a of frags[i]) for (const b of frags[j]) {
      const w = Math.min(a.right, b.right) - Math.max(a.left, b.left), h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (w > 1 && h > 1 && w * h > 0.2 * Math.min(a.width * a.height, b.width * b.height)) hit = true;
    }
    if (hit) problems.push('overlap:' + labels[i].field + '|' + labels[j].field);
  }
  return {problems: [...new Set(problems)], labels, assets, fixed_text, width: Math.round(p.width), height: Math.round(p.height)};
}
"""


class Renderer:
    """브라우저 하나를 띄워 여러 장을 그린다."""

    def __init__(self, scale: float = 2):
        self.scale = scale

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(executable_path=os.environ.get("TPLGEN_CHROMIUM") or None)
        except Exception:
            self._pw.stop()
            raise
        self._ctx = self._browser.new_context(java_script_enabled=False, device_scale_factor=self.scale, viewport={"width": 1200, "height": 1200})
        self._ctx.route("**/*", lambda route: route.abort())
        self._page = self._ctx.new_page()
        return self

    def __exit__(self, *a):
        self._browser.close()
        self._pw.stop()

    def render(self, html: str, out_png=None) -> dict:
        self._page.set_content(html, wait_until="load")
        out = self._page.evaluate(JS)
        if out_png and out["width"]:
            Path(out_png).parent.mkdir(parents=True, exist_ok=True)
            self._page.locator(".page").first.screenshot(path=str(out_png))
        return out
