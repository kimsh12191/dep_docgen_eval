# docgen_eval: 이미지 → SVG 서식 생성 평가

**현재 목표:** 모델별·난이도별 신뢰할 만한 SVG 생성 통과율 표와 [수동 난이도 분류 가이드](docs/DIFFICULTY_GUIDE.md).
모델은 사용자가 직접 선택합니다. 자동 모델 선택과 값 채우기·학습 데이터 생산은 현재 범위에서 제외합니다.

**현재 신규 개발 경로는 SVG입니다.** 내부망에서 브라우저 없이 생성·채점하고, `resvg-py`로 PNG를 만듭니다.
[SVG_SPEC.md](SVG_SPEC.md)의 `python -m formgen svg ...`를 사용하세요.
다른 LLM/에이전트는 [AGENTS.md](AGENTS.md) → [docs/STATE.json](docs/STATE.json) → [docs/DECISIONS.md](docs/DECISIONS.md) 순서로 읽으세요.
아래 HTML 설명은 기존 경로의 기록입니다.

공식 PDF 기반 새 파일럿과 브라우저 평가 보강: [EVALUATION_V2.md](EVALUATION_V2.md).
3종의 상·중·하 자료는 아직 주석 검토가 필요한 **gold 후보**이며 자동 승인하지 않습니다.

서류 이미지 한 장을 주면 **값 자리를 표시한 html 서식**을 만들어 내는 능력을 모델별로 잽니다.
만든 html 은 OCR·문서분류·KIE 학습 데이터를 찍어 내는 틀로 씁니다.

- **단독으로 돕니다.** 파이썬 표준 라이브러리만 씁니다. 설치할 패키지, 브라우저, 다른 저장소가 필요 없습니다.
- 평가 데이터는 **(이미지, 정답 html) 쌍**입니다. 이미지를 모델에 넣고, 나온 html 을 정답 html 과 비교합니다.
- 채점은 규칙 기반입니다. 같은 입력이면 늘 같은 점수가 나옵니다.

설계 문서(하려는 일·핵심 요소·가설·결정 기록): <https://claude.ai/artifact/LfqfEPoHU7uisoW7jYPNmK>

## 쓰는 법

```bash
# 이미지 한 장 → html
python -m formgen make --image x.png --endpoint http://host:8000/v1 --model NAME --out drafts/x

# 모델 하나를 평가 세트로 재기 → runs/NAME/report.md
python -m formgen bench --items bench/roundtrip_v0 --endpoint http://host:8000/v1 --model NAME --out runs/NAME

# 정답과 만든 html 채점 / html 의 난이도 / 채점기 자체 검증
python -m formgen score ref.html out.html
python -m formgen tier ref.html
python -m formgen selftest
```

- `--endpoint` 는 OpenAI 호환 주소를 `/v1` 까지 적습니다 (vLLM).
- `--protocol P2` 는 규격 검사에서 나온 문제를 모델에 돌려주고 고쳐 쓰게 합니다 (`--rounds` 번까지).
- `--repeat 3` 은 항목마다 세 번 돌립니다. 중간에 끊겨도 같은 `--out` 으로 다시 돌리면 이어서 합니다.
- 모델 없이 길만 확인: `--mock ref` (정답을 그대로 답으로 → 전부 통과해야 함), `tools/fake_vllm.py` (가짜 서버).
- 사내 프록시 환경변수가 있으면 vLLM 주소를 `NO_PROXY` 에 넣으세요.
- 이미지는 원본 크기 그대로 보냅니다 (크기 줄이기는 모델 서버 쪽 설정을 따릅니다).

## 채점 규칙 (요약)

모델이 내는 html 의 꼴은 [SPEC.md](SPEC.md). 정답도 같은 꼴입니다.

| 점수 | 재는 것 | 규칙 |
|---|---|---|
| 유효성 `valid` | 규격대로 읽히나 | 빈 문서, 값 자리 없음, `<script>`·외부 주소, 닫히지 않은 표·`</html>` 없음(잘림)이면 유효하지 않음 |
| 값 자리 `field_f1` | 값 자리를 빠짐없이, 맞는 갈래로 | 정답과 1:1 로 짝짓는다. 짝 조건: 항목명이 비슷(≥0.8) 또는 둘레(같은 칸·왼쪽 칸·위 칸의 글자)가 비슷(≥0.8). 짝이고 갈래(값/체크/도장·서명)가 같으면 맞음 |
| 값 자리(엄격) `field_f1_strict` | 위 + 이름도 자리도 | 항목명과 둘레가 **둘 다** 비슷해야 맞음 |
| 표 `table_f1` | 표의 칸 구조 | 표를 격자로 펴고, 맞닿은 칸끼리의 관계(왼쪽→오른쪽, 위→아래)가 정답과 겹치는 정도 |
| 합친 칸 `span_recall` | rowspan·colspan | 정답의 합친 칸(글자, 세로·가로 합침 수) 중 살린 비율 |
| 문구 `text_f1` | 인쇄 글자 | 두 글자 묶음(띄어쓰기 무시)이 겹치는 정도. 값 자리 안의 글자는 뺀다 |

- 연속으로 같은 꼴인 표의 행(빈 반복 행)은 한 번만 셉니다. 같은 모양을 더 촘촘한 격자로 적어도 같은 표로 봅니다.
- **통과(임시)** = 유효 ∧ 값 자리 ≥ 0.8 ∧ 표 ≥ 0.8 ∧ 합친 칸 ≥ 0.8 ∧ 문구 ≥ 0.8. 숫자는 가설이고, 사람 판정으로 한 번 맞춘 뒤 고정합니다.
- 실패는 유형으로 남깁니다: `request_error` `truncated` `invalid:…` `low_fields` `low_merged_cells` `low_table` `low_text`.
- 브라우저로 그리지 않으므로 **보이는 모양이 원본과 닮았는지, 한 쪽에 들어가는지는 재지 않습니다.**

자세한 규칙은 각 파일 맨 위에 있습니다: `formgen/score.py`, `formgen/tables.py`, `formgen/validate.py`.

## 평가 세트

`bench/roundtrip_v0/<id>/` = `image.png` (모델 입력) + `ref.html` (정답) + `meta.json` (출처·난이도).

| 세트 | 항목 | 하 / 중 / 상 | 출처 |
|---|---|---|---|
| `roundtrip_v0` | 60 | 3 / 32 / 25 | document_gen 의 서식을 값까지 채워 그린 그림 1쪽, 정답은 같은 서식의 html 에서 값을 지운 것 |

- 난이도 기준(v1 초안, `formgen/difficulty.py`): 값 자리 11·31, 합친 칸 3·11, 체크 칸 3·11, 인쇄 글자 600·1700 을 넘으면 중·상. 하나라도 윗단계면 윗단계.
- **"하"가 3개뿐입니다.** 수준별 20장을 채우려면 쉬운 서식과 인터넷·실서류 이미지를 더해야 합니다 (정답 html 은 사람이 한 번 확인).
- 이 세트는 html 에서 나온 그림이라 실제 스캔보다 쉽습니다.
- 새 항목을 더하려면 폴더에 `image.png` 와 `ref.html` 을 두면 됩니다. `meta.json` 이 없으면 난이도는 `ref.html` 에서 계산합니다.

## 지금까지 확인한 것

| 무엇 | 결과 | 기록 |
|---|---|---|
| 채점기 자체 검증 (정답을 일부러 망가뜨려 넣음, 60항목) | 그대로·값 채움 = 전부 1.0 / 빈 문서·표시 없음 = 전부 유효하지 않음 / 체크→값 = 정확히 그만큼 하락 / 다른 서식 = 값 자리 0.13, 엄격 0.05, 표 0.12, 문구 0.14 / 합치기 버림 = 합친 칸 0.0, 표 0.86 | `results/selftest_html/` |
| 합친 칸이 많은 표에서 틀린 꼴 7가지 | 점수가 기대한 순서로 하락 | `results/table_structure_demo.txt` |
| 실행 길 (모델 없이) | 정답을 답으로 = 60/60 통과, 합치기를 지운 답 = 16/60 통과 (실패는 모두 `low_merged_cells`) | `results/mock_ref/`, `results/mock_nospan/` |

**아직 확인하지 않은 것**: 실제 모델로 돌린 적이 없습니다. 통과 기준 숫자, 난이도 경계, 프롬프트(`formgen/prompts/v1.md`)는 파일럿 전의 가설입니다.
모델이 표를 `<table>` 이 아닌 `div` 로 짜면 표 점수가 낮게 나옵니다 (프롬프트에서 `<table>` 을 쓰라고 합니다).

## 폴더

| 폴더 | 하는 일 |
|---|---|
| `formgen/` | 생성기와 벤치마크 (표준 라이브러리만): `make` `bench` `score` `tables` `htmldoc` `validate` `difficulty` `llm` `selftest` |
| `formgen/prompts/` | 모델에 주는 지시문 (버전마다 파일 하나) |
| `bench/` | 평가 세트 |
| `results/` | 실행 기록 |
| `experiments/` | 실험 스크립트 |
| `tools/fake_vllm.py` | 가짜 모델 서버 (길 검사용) |
| `tools/docgen/` | **평가 세트를 만들 때만** 쓰는 도구. document_gen 과 브라우저가 있는 곳에서만 돕니다. `formgen/` 은 부르지 않습니다 |
| `data/` | 1단계 기록 (난이도 기준 v0 을 템플릿 139종에 적용) |

## 알아 둘 점

- 실서류 이미지는 사내 모델에만 줍니다. 이 저장소에는 합성 그림과 공개 서식만 둡니다.
- 평가 세트를 정한 뒤에는 고치지 않습니다. 바꾸면 새 이름(`roundtrip_v1`)으로 둡니다.
