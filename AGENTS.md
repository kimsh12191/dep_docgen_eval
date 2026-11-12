# 에이전트 안내 (Codex · Claude 등)

먼저 `README.md` 를 읽으세요. 목적은 하나입니다: **golden set 으로 여러 모델의 SVG 서식 생성 수준을 재서 비교한다.**

- **간결하게 유지합니다.** 채점기 하나(`formgen/svg.py`), 벤치마크 하나(`formgen/bench.py`), 생성 함수 하나(`formgen/make.py`). 두 번째 것을 옆에 더하지 말고 있는 것을 고치세요.
- 실행에 필요한 것은 파이썬 표준 라이브러리뿐이어야 합니다 (그리기만 `resvg-py`). 브라우저·온라인 내려받기를 실행 길에 넣지 않습니다.
- 통과 기준은 `bench.PASS_RULE` 한 곳. 임시값이며 실제 모델 출력과 사람 판정 없이 확정하지 않습니다.
- 채점 규칙을 바꾸면 `svg.SCORER` 를 올리고 `python -m formgen selftest` 가 전부 기대대로인지 확인합니다.
- 평가 세트는 고치지 않고 새 이름(`golden_v2`)으로 더합니다. 실서류는 저장소에 넣지 않고, 사내 모델 주소에만 보냅니다.
- 안 돌려 본 것을 된 것처럼 적지 않습니다. README 의 "지금 상태" 표를 사실대로 유지합니다.
- 시험: `python -m unittest discover -s tests`. main 에 올리기 전에 pull 하고, 강제로 덮어쓰지 않습니다.
