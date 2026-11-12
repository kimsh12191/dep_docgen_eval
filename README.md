# docgen_eval — 서류 이미지 → SVG 서식, 모델별 평가

서류 이미지 한 장을 모델에 주고 **값 자리를 표시한 빈 SVG 서식**을 만들게 한 뒤, 정답과 비교해 **모델별·난이도별 통과율**을 냅니다.
만든 SVG 서식은 OCR·KIE 학습 데이터를 찍어 내는 틀로 쓰려는 것입니다.

- 파이썬 표준 라이브러리만으로 돕니다. 브라우저도 다른 저장소도 필요 없습니다. (SVG 를 그림으로 볼 때만 `resvg-py`)
- 모델은 OpenAI 호환 주소(vLLM)로 부릅니다. **실서류 이미지는 사내 모델 주소에만 보냅니다.**

## 쓰는 법

```bash
# 1) 모델마다 한 번씩 돌린다 → runs/<이름>/report.md
python -m formgen bench --endpoint http://host:8000/v1 --model NAME_A --out runs/A --repeat 3
python -m formgen bench --endpoint http://host:8001/v1 --model NAME_B --out runs/B --repeat 3

# 2) 모델 × 난이도 표
python -m formgen compare runs/A runs/B

# 이미지 한 장만 svg 로 (평가와 같은 코드)
python -m formgen make --image x.png --endpoint http://host:8000/v1 --model NAME_A --out drafts/x
```

- 끊기면 같은 `--out` 으로 다시 돌리면 이어서 합니다. 프록시 환경이면 모델 주소를 `NO_PROXY` 에 넣으세요.
- 모델 없이 길만 확인: `python -m formgen bench --mock ref --out runs/mock` (정답을 답으로 → 12/12 통과).
- 그 밖: `score` `validate` `stats` `render` `report` `selftest` — `python -m formgen` 만 치면 설명이 나옵니다.

## 평가 세트

[`bench/golden_v1`](bench/golden_v1/README.md): 하나은행 공개 원본 서식 12종 (하 4 · 중 4 · 상 4). 값을 채워 그린 그림과 정답 SVG.
난이도 기준과 서식 목록, 정답을 겹쳐 그린 확인용 그림이 그 폴더에 있습니다.

## 채점

모델이 내는 SVG 의 꼴은 [SVG_SPEC.md](SVG_SPEC.md). 값 자리는 이렇게 표시합니다.

```xml
<rect data-field="applicant.name" data-label="성명" data-type="text" x="120" y="180" width="180" height="24" fill="none" stroke="none"/>
```

| 점수 | 뜻 |
|---|---|
| 유효 `valid` | 규격대로인가. XML 이 깨짐, 잘림, 값 자리 없음, 금지 요소 → 유효하지 않음 |
| 값 자리 재현 `field_recall` | 정답 값 자리 중, 만든 것과 **자리가 맞고** 갈래(값 / 체크 / 도장·서명)가 같은 비율 |
| 값 자리 정밀 `field_precision` | 만든 값 자리 중 맞은 비율 (참고) |
| 항목명 `label_acc` · 종류 `type_acc` · 겹침 `iou_mean` | 짝지은 값 자리의 이름·세부 종류·자리가 얼마나 맞나 (참고) |
| 문구 `text_f1` | 인쇄 문구가 겹치는 정도 |

**통과(임시) = 유효 ∧ 값 자리 재현 ≥ 0.8 ∧ 문구 ≥ 0.8.** `formgen/bench.py` 의 `PASS_RULE` 한 줄입니다.
점수는 그대로 저장되므로, 기준을 고치고 `python -m formgen report runs/A` 를 돌리면 모델을 다시 부르지 않고 표가 바뀝니다.

- 자리를 먼저 보고 짝짓습니다. 항목명은 모델마다 다르게 적을 수 있어 통과 기준에 넣지 않았습니다.
- 정답에 빠진 칸이 있을 수 있어 정밀도는 통과 기준에 넣지 않았습니다.
- 표의 "이미지 통과"는 한 이미지의 반복 중 절반을 넘게 통과한 것입니다. 이미지가 12장뿐이라 95% 구간이 넓게 나옵니다.
- **재지 않는 것:** 그렸을 때 보기 좋은지(겹침·넘침), 표의 칸 구조.

## 지금 상태

| | |
|---|---|
| 확인함 | 채점기 자체 검증: 정답 12개를 12가지로 망가뜨린 144건이 모두 기대대로 (`python -m formgen selftest`). 실행 길: `python -m unittest discover -s tests` |
| **아직 안 함** | **실제 모델로 돌려 본 적이 없습니다.** 통과 기준 0.8, 프롬프트, 출력 한도(32000 토큰)는 가설입니다 |
| 사람이 할 일 | ① 사내 모델로 돌려 실패 유형을 본다 ② `check.png` 로 정답을 검수한다 ③ 출력 몇 개를 직접 보고 통과 기준이 눈과 맞는지 맞춘다 |

## 폴더

| | |
|---|---|
| `formgen/` | `make` 생성 · `bench` 벤치마크·표·비교 · `svg` 규격 검사·채점 · `selftest` · `llm` 모델 호출 · `match` 짝짓기 · `prompts/` 지시문 |
| `bench/golden_v1/` | 평가 세트 |
| `tools/` | `build_golden.py` 평가 세트 만들기 · `fake_vllm.py` 가짜 모델 서버 |
| `tests/` | 시험 |

예전 html 길, 실험용 채점기(v2·v3), 다중 모델 하네스는 걷어냈습니다. 필요하면 커밋 `1f8e29b` 에 있습니다.
