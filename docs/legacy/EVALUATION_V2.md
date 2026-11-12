# (기록) html 길의 평가 보강 및 공식 원본 파일럿

> 예전 html 길의 문서입니다. 명령은 `python -m formgen html …` 로 옮겼습니다. 지금 쓰는 길은 [README.md](../../README.md) 와 [SVG_SPEC.md](../../SVG_SPEC.md) 입니다.

**2026-11-12 변경:** 신규 생성/평가 방향은 독립 SVG로 전환했습니다. 현재 계약은 [SVG_SPEC.md](../../SVG_SPEC.md),
구현 상태는 [docs/STATE.json](../STATE.json)을 따릅니다. 이 문서의 HTML/브라우저 경로와
아래의 “SVG 미지원” 설명은 전환 이전 단계의 기록입니다. SVG 경로에서는 requirements-svg.txt만 사용합니다.

현재 v1은 결정적 내용·구조 회귀 지표로 보존합니다. 새 `formgen.evaluate`는
브라우저 기반 진단을 더하며, 검증되지 않은 하나의 종합 점수/통과율을 만들지 않습니다.

## 실행

### 내부망 기본 모드: Python 표준 라이브러리만

```powershell
python -m formgen html evaluate --ref ref.html --pred out.html --out runs/review
```

설치할 pip 패키지, Playwright, Chromium이 없습니다. 이미지 입력 모델 서버가 내부망에 있으면
기존 `formgen make`/`bench`도 표준 라이브러리로 호출할 수 있습니다.
기본 모드는 문구·HTML 표 구조·필드 타입·체크 옵션만 평가합니다.
화면 위치·숨김·넘침·시각 유사도는 **미측정(null)** 으로 저장하며 전체 통과로 판정하지 않습니다.
`python -S -m formgen.evaluate ...`로 site-packages 없이 실행 가능한지 확인할 수 있습니다.

### 선택 모드: 렌더러가 준비된 환경

```powershell
python -m pip install -r requirements-eval.txt
python -m formgen html evaluate --ref bench/official_pilot_v1/gov_pension/ref.html --pred output.html --source-image bench/official_pilot_v1/gov_pension/image.png --out runs/review --browser "C:/Program Files/Google/Chrome/Application/chrome.exe"
```

브라우저와 패키지를 내부망에 사전 반입해야 합니다. Linux에서도 `--browser`에 Chromium 경로를 지정할 수 있습니다.
위 설치는 선택 모드에만 해당합니다. 인터넷 없는 내부망에서 pip 온라인 설치를 전제하지 않습니다.
렌더링 중 네트워크를 차단하고 문서 JavaScript 실행을 끕니다. 평가 코드의 DOM 측정만 수행합니다.
`evaluation.json`, `reference.png`, `prediction.png`, `filled_stress.png`를 저장합니다.

## 지표와 해석

| 항목 | 의미 | 제한 |
|---|---|---|
| typed_field_f1 | 라벨을 매칭하고 정확한 타입·체크 옵션까지 맞아야 정답 | 별칭과 날짜 분할 동등성은 미구현 |
| located_typed_field_f1 | 위 조건 + 정규화한 필드 중심 거리 합 ≤ 0.04 | 임시 허용 오차. 빈 span은 부모 좌표 사용을 기록 |
| hidden_fields | display/visibility/opacity 및 크기 검사 | 모든 가림·색상 조합을 탐지하지는 않음 |
| outside_page | 텍스트 및 필드가 지정 화면 밖에 존재 | 화면 검사이며 인쇄 페이지 수 검사가 아님 |
| overflow_fields | 긴 값을 주입한 필드의 scrollWidth 초과 | 범용 스트레스 값은 각 필드의 실제 유효값이 아님 |
| ink_f1 | 공식 빈 원본 대비 2px 허용 오차의 전경 정밀도·재현율 | 글꼴 영향 있음. 정답 필드 영역만 제외, 아직 QR 등 별도 마스크 없음 |

`reference_visual`도 같이 측정하여 참조 HTML 자체의 차이를 드러냅니다.
시각 점수에 예측 필드 영역을 마스킹하지 않습니다. 예측이 거대한 필드를 만들어 오차를 숨기는 것을 피하기 위함입니다.
`final_pass`는 미보정 상태에서 항상 null입니다. `legacy.pass`는 예전 기준의 결과일 뿐 최종 품질 판정이 아닙니다.
새 점수로 모델 순위를 확정하려면 사람의 사용 가능/수정 필요/불가 판정과의 상관·오탐/미탐부터 확인해야 합니다.

## 재현과 검사

```powershell
python -m tools.build_official_pilot --forms <공식대조 서식 폴더>
python -m unittest discover -s tests -v
```

타입 변경, 체크 옵션 누락, 잘못된 필드 위치, 전체 숨김, 페이지 밖 배치를 회귀 검사합니다.
원본 다운로드가 실패하거나 해시가 달라지면 import를 중단합니다. 정답 후보를 자동 승인하지 않습니다.

## 다음 검증 단계

### SVG 출력에 대한 결정

SVG는 고정 페이지 좌표와 선·텍스트·필드 영역을 직접 표현하므로 대안이 될 수 있습니다.
그러나 한글 글꼴과 SVG→PNG 렌더러가 여전히 필요합니다. 현재 CLI는 HTML을 대상으로 하며,
standalone SVG를 완전히 지원한다고 간주하지 않습니다. SVG 도입 시 `text`는 검색 가능한 문자로
유지하고 `data-field`, 타입, 옵션, bbox를 명시한 별도 필드 명세를 함께 저장합니다.
모든 글자를 path나 배경 이미지로 변환하면 값 교체와 OCR/KIE 주석 검증이 어려워집니다.
기존 공식 HTML은 SVG 선 + 절대좌표 HTML 글자 혼합이므로 단순 확장자 변경으로 전환할 수 없습니다.

공식 3종은 출처가 확인되고 시각 비교된 출발점입니다. 주석 누락을 해결하고 독립 검토하기 전에는
완성된 gold set이 아닙니다. 실제 채워진 스캔/촬영 사례, 지역별·기관별 다양한 서식, 다중 페이지,
필드별 실제 값 주입과 OCR/KIE downstream 측정은 추가 작업이 필요합니다.
