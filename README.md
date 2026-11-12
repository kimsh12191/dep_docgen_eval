# docgen_eval — 서류 이미지 → SVG 서식, 모델별 평가

서류 이미지 한 장을 모델에 주고 **값 자리를 표시한 빈 SVG 서식**을 만들게 한 뒤, 정답과 비교해 **모델별·난이도별 통과율**을 냅니다.
만든 SVG 서식은 OCR·KIE 학습 데이터를 찍어 내는 틀로 쓰려는 것입니다.

- 파이썬 표준 라이브러리만으로 돕니다. 브라우저도 다른 저장소도 필요 없습니다. (SVG 를 그림으로 볼 때만 `resvg-py`)
- 모델은 OpenAI 호환 주소(vLLM)로 부릅니다. **실서류 이미지는 사내 모델 주소에만 보냅니다.**

## 쓰는 법

모델 주소·vLLM 옵션·셀프 고치기 횟수는 설정 파일 하나에 둡니다. [`configs/example.json`](configs/example.json) 을 `configs/local.json` 으로 복사해 고치세요 (`configs/local*.json` 은 커밋되지 않습니다).

```bash
# 설정의 모델을 차례로 → runs/<out>/<name>/report.md, runs/<out>/compare.md
python -m formgen bench configs/local.json            # --only model_a 로 하나만

# 이미지 한 장만 svg 로 (평가와 같은 코드, 같은 설정)
python -m formgen make --config configs/local.json --name model_a --image x.png --out drafts/x
```

| 설정 키 | 뜻 |
|---|---|
| `rounds` | 셀프 고치기 횟수. 0 = 한 번만 생성. N 이면 회차 0…N 을 모두 채점해 **한 번만 생성(0회차)과 고친 뒤(N회차)를 같은 표에** 냅니다 |
| `repeat` | 항목마다 돌리는 횟수 (온도 > 0 일 때 흔들림을 보려면 3) |
| `models[]` | `name` `endpoint`(…/v1) `model`(vLLM 이 내놓은 이름), 그리고 `max_tokens` `temperature` `timeout` `api_key_env`(키가 든 환경변수 이름) `extra`(요청 본문에 그대로: `top_p`, `repetition_penalty`, `chat_template_kwargs` 등). `defaults` 에 두면 모든 모델에 공통 |
| `font_files` | 고치기 피드백 그림에 쓸 한글 글꼴 파일. 비우면 시스템 글꼴 |

**셀프 고치기 한 회차**에 모델이 받는 것: 원본 이미지 + 직전 SVG 를 그린 그림(값 자리는 빨간 상자로 덧그림) + 직전 SVG 원문과 규격 검사 결과 ([`formgen/prompts/svg_v1_fix.md`](formgen/prompts/svg_v1_fix.md)).
**정답은 루프에 쓰지 않습니다.** 직전 SVG 가 규격에 안 맞아 그릴 수 없으면 그림 없이 글만 갑니다. 그림은 `resvg-py` 가 있어야 그려집니다 (`requirements-svg.txt`).

- 끊기면 같은 명령을 다시 치면 이어서 합니다. 설정(모델·출력 한도·옵션·회차)을 바꿨으면 `out` 이나 `name` 을 바꾸라고 멈춥니다. 프록시 환경이면 모델 주소를 `NO_PROXY` 에 넣으세요.
- 모델 없이 길만 확인: `python -m formgen bench configs/mock.json` (정답을 답으로 → 12/12, 값 자리 없는 답을 고쳐 정답으로 → 0회차 0/12, 1회차 12/12).
- 그 밖: `compare` `report` `score` `validate` `stats` `render` `selftest` — `python -m formgen` 만 치면 설명이 나옵니다.

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
| 셀프 고치기의 가설 | 값 자리 재현이 0회차보다 오른다. **틀렸다고 볼 때:** 보고서의 "0회차 → N회차" 줄에서 내린 시도가 오른 시도보다 많거나 평균이 오르지 않음. 오른다 해도 누적 토큰·초가 함께 나오니 비용 대비로 판단합니다. 이미지 12장으로는 난이도별 차이를 가리기 어렵습니다 |
| 사람이 할 일 | ① 사내 모델로 돌려 실패 유형을 본다 ② `check.png` 로 정답을 검수한다 ③ 출력 몇 개를 직접 보고 통과 기준이 눈과 맞는지 맞춘다 |

## 폴더

| | |
|---|---|
| `configs/` | 실행 설정 (`example.json` 본보기, `mock.json` 길 검사) |
| `formgen/` | `config` 설정 읽기 · `make` 생성·셀프 고치기 · `bench` 벤치마크·표·비교 · `svg` 규격 검사·채점 · `selftest` · `llm` 모델 호출 · `match` 짝짓기 · `prompts/` 지시문 |
| `bench/golden_v1/` | 평가 세트 |
| `tools/` | `build_golden.py` 평가 세트 만들기 · `fake_vllm.py` 가짜 모델 서버 |
| `tests/` | 시험 |

예전 html 길, 실험용 채점기(v2·v3), 다중 모델 하네스는 걷어냈습니다. 필요하면 커밋 `1f8e29b` 에 있습니다.
