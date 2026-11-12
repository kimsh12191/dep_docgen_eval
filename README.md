# docgen_eval: 이미지 → html 서식 생성 벤치마크

서류 이미지 한 장을 주면 **칸(키·항목명·종류·위치)이 달린 html 서식**을 만들어 내는 능력을 모델별로 재는 벤치마크입니다.
만든 서식은 OCR·문서분류·KIE 학습 데이터를 찍어 내는 틀로 씁니다 ([document_gen](https://github.com/kimsh12191/document_gen) 의 `docgen/manual/NEW_FORM_SPEC.md` 초안 폴더 꼴).

하려는 일·핵심 요소·가설·결정 기록은 설계 문서에 있습니다: <https://claude.ai/artifact/LfqfEPoHU7uisoW7jYPNmK>

## 지금 있는 것 / 아직 없는 것

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | 난이도 기준을 기존 템플릿 139종에 적용 (`scripts/measure_difficulty.py`, `data/step1_difficulty.json`) | 완료. 기준 v0 은 틀림 → v1 초안 |
| 2 | 채점기 + 자체 검증 (`formgen/score.py`, `python -m formgen selftest`) | 진행 중. 결과는 `results/` |
| 3 | 생성기 (`make`), 벤치마크 실행 (`bench`), 파일럿 | 없음 |
| 4~6 | 평가 세트 60장, 통과 기준선, 전체 실행, 모델 선택 규칙 | 없음 |

채점에서 아직 없는 것: 표 구조(L2), 모양 유사도(L4). 지금은 유효성(L0)·인쇄 문구(L1)·칸(L3)만 봅니다.

## 실행

docgen 은 이 저장소에 들어 있지 않습니다. document_gen 을 받아 두고 위치를 알려 줍니다.

```bash
pip install jinja2 pillow playwright      # 브라우저(chromium)는 docgen 이 쓰는 것과 같음
export DOCGEN_ROOT=/path/to/document_gen
python -m formgen selftest --pool data/roundtrip_pool_v0.json --out results/selftest
```

## 폴더

| 폴더 | 하는 일 |
|---|---|
| `formgen/bridge.py` | docgen 연결: 등록된 서식·초안 폴더를 그려 라벨을 받는다 |
| `formgen/sheet.py` | 라벨 → 채점용 쪽 요약 (좌표 정규화, 반복 행은 열마다 한 번, 고정 문구만) |
| `formgen/match.py` | 정답 칸과 만든 칸을 1:1 로 짝짓기 (전체 밀림·늘어남은 맞춘 뒤) |
| `formgen/score.py` | 채점 (유효성·문구·칸) |
| `formgen/selftest.py` | 채점기 자체 검증 (모델 없이) |
| `data/` | 1단계 측정 결과, 왕복 세트 후보 |
| `examples/spec_example/` | NEW_FORM_SPEC 9절의 초안 폴더 예시 (초안 경로 검사용) |

## 알아 둘 점

- 실서류 이미지는 사내 모델에만 줍니다. 이 저장소에는 합성 그림과 공개 서식만 둡니다.
- 모델이 쓴 `generate.py` 는 실행하지 않습니다 (`Renderer.draft(run_script=False)`).
