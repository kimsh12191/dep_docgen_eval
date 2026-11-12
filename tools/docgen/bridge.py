"""document_gen(docgen) 연결: 서식·초안 폴더를 그려 라벨을 받는다.

docgen 은 이 저장소에 들어 있지 않다. 환경변수 DOCGEN_ROOT (document_gen 을 받은 폴더) 로 찾고,
없으면 이미 import 되는 docgen 을 쓴다 (내부망 docgen-studio 컨테이너는 그렇게 잡혀 있다).
이 저장소의 코드는 파이썬 표준 라이브러리만 쓴다. 브라우저·글꼴·jinja2 는 docgen 쪽 환경의 것을 그대로 쓴다.
그리기·검사는 모두 docgen.preview 를 그대로 쓴다 (studio·분석기와 같은 코드).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


def docgen_root() -> Path:
    """docgen 을 찾는다: DOCGEN_ROOT 가 있으면 그 폴더, 없으면 이미 import 되는 docgen (studio 컨테이너는 PYTHONPATH 에 잡혀 있다)."""
    root = os.environ.get("DOCGEN_ROOT")
    if root:
        p = Path(root).resolve()
        if not (p / "docgen" / "preview.py").is_file():
            raise SystemExit(f"DOCGEN_ROOT 에 docgen 이 없습니다: {p}")
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
        return p
    try:
        import docgen.preview as _pv
    except ImportError:
        raise SystemExit("docgen 을 찾지 못했습니다. document_gen 폴더를 지정하세요: export DOCGEN_ROOT=/path/to/document_gen "
                         "(studio 컨테이너 안에서는 지정하지 않아도 됩니다)")
    return Path(_pv.__file__).resolve().parents[1]


class Renderer:
    """브라우저 하나를 띄워 두고 서식(등록된 ID) 또는 초안 폴더를 그린다. 끝나면 close()."""

    def __init__(self, cache_dir: str | Path):
        docgen_root()
        from docgen.preview import Previewer

        self.cache = Path(cache_dir)
        self.pv = Previewer(str(self.cache))

    def close(self) -> None:
        self.pv.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def form(self, doc_id: str, seed: int = 0, rows: str | None = None, blank: bool = False) -> dict:
        """등록된 서식을 그린다. 라벨(dict)에 쪽 전체 글자 박스(texts)를 함께 받는다."""
        draft = {"texts": True}
        if blank:
            draft["blank"] = True
        label = self.pv.render(doc_id, seed=seed, draft=draft, rows=rows)
        label["_dir"] = str(self.cache)
        return label

    def draft(self, folder: str | Path, seed: int = 0, rows: str | None = "min", run_script: bool = False) -> dict:
        """초안 폴더(template.html.j2 + form.json)를 그린다. docgen.preview --dir 와 같은 길.

        run_script=False 면 폴더의 generate.py 를 실행하지 않는다 (모델이 쓴 코드를 돌리지 않기 위한 기본값).
        템플릿·form.json 이 깨져 있으면 예외가 난다 (부르는 쪽이 유효성 실패로 적는다)."""
        from docgen import htmlform
        from docgen.registry import GROUPS, REGISTRY, DocSpec, load_all

        d = Path(folder).resolve()
        form = json.loads((d / "form.json").read_text(encoding="utf-8"))
        if not isinstance(form, dict):
            raise ValueError("form.json 은 JSON 객체여야 합니다")
        template = (d / "template.html.j2").read_text(encoding="utf-8")
        script = d / htmlform.SCRIPT
        value = {"template": template, "form": form, "script": str(script) if run_script and script.exists() else None}
        load_all()
        doc_id = "draft_" + hashlib.sha1(str(d).encode()).hexdigest()[:12]
        REGISTRY[doc_id] = DocSpec(doc_id, form.get("name") or doc_id, form.get("group") if form.get("group") in GROUPS else "imported",
                                   form.get("category", "external"), htmlform.PREFIX + doc_id, htmlform.make_generate(doc_id),
                                   form.get("page", "a4"), False, "formgen 초안", form.get("origin", "analyzer"))
        try:
            label = self.pv.render(doc_id, seed, force=True, draft={**value, "texts": True}, rows=rows)
        finally:
            REGISTRY.pop(doc_id, None)
        label["_dir"] = str(self.cache)
        return label
