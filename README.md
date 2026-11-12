# docgen_eval: 서류 이미지 → SVG 서식 생성 평가

서류 이미지 한 장을 모델에 주고 **값 자리를 표시한 빈 SVG 서식**을 만들게 한 뒤, 정답 SVG 와 비교해 채점합니다.

| 만들려는 것 | 지금 상태 |
|---|---|
| 1. 모델별·난이도별 **통과율 표** | 표를 만드는 코드는 있음. **믿을 만한 표는 아직 없음** (승인된 정답 0개, 실제 모델로 돌린 적 없음, 통과 기준은 임시) |
| 2. 사람이 새 이미지를 견줄 **난이도 기준·대표 사례** | 초안: [docs/DIFFICULTY_GUIDE.md](docs/DIFFICULTY_GUIDE.md). 사례 3개의 라벨은 검수 전 |
| 3. 고른 모델로 **SVG 를 만드는 코드** | 있음. 벤치마크·하네스가 같은 함수를 부름. 실제 모델로는 아직 안 돌려 봄 |

모델은 사용자가 표와 사례를 보고 직접 고릅니다. 자동 모델 선택, 값 채우기, 학습 데이터 생산은 지금 범위가 아닙니다.
무엇이 확인됐고 무엇이 아닌지는 [docs/PURPOSE_AUDIT.md](docs/PURPOSE_AUDIT.md) 에 있습니다.

- **단독으로 돕니다.** 생성·채점·벤치마크는 파이썬 표준 라이브러리만 씁니다. 브라우저도 다른 저장소도 필요 없습니다.
- SVG 를 그림으로 볼 때만 `resvg-py` 하나가 필요합니다 (`requirements-svg.txt`).
- 채점은 규칙 기반입니다. 같은 입력이면 늘 같은 점수가 나옵니다.
- **실서류 이미지는 사내 모델 주소에만 보냅니다.** 이 저장소에는 공개 서식과 합성 그림만 둡니다.

## 쓰는 법

```bash
# 이미지 한 장 → svg 서식 (out.svg · raw.txt · make.json)
python -m formgen make --image x.png --endpoint http://host:8000/v1 --model NAME --out drafts/x

# 모델 하나를 평가 세트로 재기 → runs/NAME/report.md (난이도별 통과율 표)
python -m formgen bench --items bench/official_pilot_v1 --endpoint http://host:8000/v1 --model NAME --out runs/NAME --repeat 3 --allow-candidates

# 통과 기준을 바꾼 뒤 표만 다시 만들기 (모델 호출 없음)
python -m formgen report runs/NAME

# 여러 모델 서버에 같은 이미지를 보내 생성 (선택: 그려 보고 고쳐 쓰기 P2) → docs/HARNESS.md
python -m formgen harness generate --help

# 낱개 도구
python -m formgen score ref.svg out.svg        # 정답과 채점
python -m formgen validate out.svg             # 규격 검사
python -m formgen stats ref.svg                # 난이도 특징 세기 (수동 분류 보조)
python -m formgen render out.svg --out out.png --font-file 글꼴.ttf   # 그림으로 (resvg-py 필요)
python -m formgen selftest                     # 채점기 자체 검증 (모델 없이)
```

- `--endpoint` 는 OpenAI 호환 주소를 `/v1` 까지 적습니다 (vLLM). 사내 프록시 환경변수가 있으면 모델 주소를 `NO_PROXY` 에 넣으세요.
- `--repeat 3` 은 항목마다 세 번 돌립니다. 중간에 끊겨도 같은 `--out` 으로 다시 돌리면 이어서 합니다. 모델·프롬프트가 다르면 새 `--out` 을 요구합니다.
- `--allow-candidates` 가 없으면 승인되지 않은 정답(`gold_approved` 가 true 가 아님)으로는 돌지 않습니다. 붙여서 돌린 표에는 "진단용"이 찍힙니다.
- 모델 없이 길만 확인: `--mock ref` (정답을 그대로 답으로 → 전부 통과), `--mock nofields`, `--mock empty`, 가짜 서버 `tools/fake_vllm.py`.
- 이미지는 원본 크기 그대로 보냅니다 (크기 줄이기는 모델 서버 설정을 따릅니다).

## 모델이 내는 것

SVG 한 파일입니다. 인쇄 문구는 `<text>`, 선은 `rect`·`line` 등으로 그리고, 값이 들어갈 자리마다 보이지 않는 `rect` 를 둡니다.

```xml
<rect data-field="applicant.name" data-label="성명" data-type="text" x="120" y="180" width="180" height="24" fill="none" stroke="none"/>
```

규격 전체는 [SVG_SPEC.md](SVG_SPEC.md), 모델에 주는 지시문은 `formgen/prompts/svg_v1.md` 입니다.

## 채점 규칙

| 점수 | 재는 것 | 규칙 |
|---|---|---|
| `valid` | 규격대로인가 | XML 이 깨짐, 값 자리 없음, `<text>` 없음, 금지 요소·속성(script, image, href, style 등), 숨긴 내용, 값 자리가 쪽 밖, 출력이 잘림 → 유효하지 않음 |
| `typed_field_f1` | 값 자리를 빠짐없이, 맞는 종류로 | 항목명이 비슷한(≥0.8) 것끼리 1:1 로 짝짓고, 종류와 체크 보기까지 같으면 맞음 |
| `located_field_f1` | 위 + 자리도 맞게 | 위 조건에 더해 정답 상자와 겹침(IoU) ≥ 0.5 |
| `field_iou_mean` | 자리가 얼마나 겹치나 | 맞은 값 자리의 IoU 합 ÷ 정답 값 자리 수 |
| `text_f1` `text_r` | 인쇄 문구 | `<text>` 글자의 두 글자 묶음이 겹치는 정도 (F1, 재현율) |

- **통과(임시)** = 유효 ∧ `typed_field_f1` ≥ 0.8 ∧ `located_field_f1` ≥ 0.8 ∧ `text_r` ≥ 0.8. 사람 판정으로 맞추기 전의 가설이고 `formgen/bench.py` 의 `PASS_RULE` 한 곳에 있습니다. 점수는 `results.jsonl` 에 그대로 남으므로 기준을 바꿔도 모델을 다시 돌리지 않습니다.
- 실패는 유형으로 남깁니다: `request_error` `truncated` `invalid:…` `low_fields` `low_position` `low_text`.
- 표에는 **이미지 수와 시도 수를 따로** 적습니다. 같은 이미지를 세 번 돌린 것은 이미지 세 장이 아닙니다. 이미지 통과율에는 95% 구간을 붙입니다.
- **재지 않는 것:** 그렸을 때 글자·선이 겹치거나 넘치는지, 표의 칸 구조, 원본과 보기에 닮았는지. 값 자리는 모델이 적어 낸 좌표를 믿고 비교합니다.

## 실험 중인 진단 채점 (v2 · v3)

통과율 표와 따로, 더 자세히 보는 채점기가 `python -m formgen svg …` 아래에 있습니다. 둘 다 사람 판정으로 맞추지 않은 진단값이고 통과 여부를 내지 않습니다.

| 채점기 | 보는 것 | 필요한 것 | 문서 |
|---|---|---|---|
| v2 `svg score`, `svg bench --visual` | 값 자리를 **자리 먼저** 보고 짝지은 뒤 찾기·항목명·종류·위치를 따로 채점, 문구 위치, (선택) 그린 그림의 잉크·윤곽 겹침 | 그림 비교만 `requirements-svg-visual.txt` | [docs/SCORER_V2.md](docs/SCORER_V2.md) |
| v3 `svg score-v3`, `svg bench --v3` | 원본 이미지와 그린 SVG 의 닮음 0~100 (쪽 전체 70% + 표 영역 30%). **정답 SVG 없이** 원본 이미지와 표 영역 표시만으로 채점 | 위 + 항목마다 `table_regions.json` | [docs/SCORER_V3.md](docs/SCORER_V3.md) |

`python -m formgen bench` 는 줄마다 v2 의 값 자리·문구 위치 점수도 `results.jsonl` 에 함께 남깁니다 (`v2_…`). 통과 기준에는 아직 쓰지 않습니다.
어느 채점기로 "통과"를 정할지는 실제 모델 출력과 사람 판정을 본 뒤 정합니다. 그때 벤치마크 길도 하나로 합칩니다.

## 평가 세트

`<세트>/<id>/` = `image.png` (모델 입력) + `ref.svg` (정답) + `meta.json` (출처·난이도·승인 여부). 자세한 것은 [bench/README.md](bench/README.md).

| 세트 | 항목 | 정답 | 상태 |
|---|---|---|---|
| `bench/official_pilot_v1` | 3 (하 1 · 중 1 · 상 1) | SVG | 공개 정부 서식 PDF. **정답 후보** (주석 누락 있음, 승인 0) |
| `bench/official_gold_v1` | 9 | HTML 만 | 수집·검수 중인 후보. SVG 정답이 없어 아직 벤치마크에 못 씀 |
| `bench/roundtrip_v0` | 60 | HTML | 예전 html 길의 세트 (기록용) |

## 지금까지 확인한 것

| 무엇 | 결과 | 기록 |
|---|---|---|
| SVG 채점기 자체 검증 (정답 3개를 10가지로 망가뜨림) | 30건 모두 기대대로: 그대로 = 1.0 / 값 자리 절반 = 0.67 / 종류 바꿈 = 바꾼 비율만큼 하락 / 다른 서식 = 값 자리 0.12~0.18 / 빈 답·잘림·값 자리 없음 = 유효하지 않음 | `results/selftest_svg/` |
| 실행 길 (모델 없이) | 정답을 답으로 = 3/3 통과, 값 자리를 지운 답 = 0/3 (`invalid:no_fields`), 끊긴 뒤 이어하기, 가짜 서버로 HTTP 호출 | `tests/test_bench.py`, `tests/test_svg.py` |
| 코드 정리 전후 채점 결과 | 30건 점수가 글자 하나까지 같음 | `docs/DECISIONS.md` D008 |
| 전체 시험 | 48개 통과 (v2·v3 채점기와 하네스의 시험 포함, 브라우저 시험 1개는 건너뜀) | `python -m unittest discover -s tests` |

**아직 확인하지 않은 것:** 실제 모델 출력, 통과 기준 숫자, 난이도 경계, 프롬프트, 사내 환경에서 `resvg-py` 설치와 한글 글꼴.

## 폴더

| 곳 | 하는 일 |
|---|---|
| `formgen/` | `make` 생성 · `bench` 벤치마크와 표 · `svg` 규격 검사·채점·그리기 · `selftest` 채점기 검증 · `llm` 모델 호출 · `match` 짝짓기·문구 비교 |
| 〃 | `harness` `harness_refine` 여러 모델 생성·고쳐 쓰기 · `svg_eval_v2` `svg_eval_v3` `svg_cli` 실험 중인 진단 채점 |
| `formgen/prompts/` | 모델에 주는 지시문 (버전마다 파일 하나) |
| `formgen/html/` | 예전 html 길 (`python -m formgen html …`). 기록·회귀 확인용 |
| `bench/` | 평가 세트 |
| `tests/` | `python -m unittest discover -s tests` |
| `results/` | 실행 기록 (`selftest_svg` 외에는 html 길의 기록) |
| `docs/` | 난이도 가이드, 목적 대비 점검, 결정 기록, 상태. `docs/legacy/` 는 html 길의 문서 |
| `tools/` | `fake_vllm.py` 가짜 모델 서버. 나머지는 **평가 세트를 만들 때만** 쓰는 도구 (외부 패키지·브라우저 필요) |
| `목적.md` | 프로젝트 목적과 설계 이력 (맨 위 "현재 확정 범위"가 우선) |

다른 LLM·에이전트는 [AGENTS.md](AGENTS.md) → [docs/STATE.json](docs/STATE.json) → [docs/DECISIONS.md](docs/DECISIONS.md) 순서로 읽으세요.
