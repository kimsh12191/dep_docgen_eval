# 평가 세트

항목 하나 = 폴더 하나: `image.png` (모델 입력) + 정답 (`ref.svg` 또는 `ref.html`) + `meta.json`.
`python -m formgen bench` 는 `image.png` 와 `ref.svg` 가 둘 다 있는 폴더만 항목으로 봅니다.

| 세트 | 항목 | 정답 | 쓰임 | 상태 |
|---|---|---|---|---|
| `official_pilot_v1` | 3 (하 1 · 중 1 · 상 1) | `ref.svg` (+ `ref.html`) | 지금 SVG 벤치마크가 도는 유일한 세트 | **후보.** 주석 누락이 확인됨, `gold_approved: false` |
| `official_gold_v1` | 9 (난이도 미분류) | `ref.html` 만 | 다음 SVG 정답으로 만들 재료 | **후보.** SVG 정답 없음 → 벤치마크 불가. 3개는 pilot 과 같은 서식 |
| `roundtrip_v0` | 60 (하 3 · 중 32 · 상 25) | `ref.html` | 예전 html 길 (`python -m formgen html bench`) | 기록용. html 을 그린 그림이라 실제 스캔보다 쉬움 |

## meta.json 에서 벤치마크가 읽는 것

- `tier`: `하` · `중` · `상`. 표의 난이도 줄을 정합니다. 기준은 [docs/DIFFICULTY_GUIDE.md](../docs/DIFFICULTY_GUIDE.md).
- `gold_approved`: `true` 가 아니면 후보입니다. 후보가 섞이면 `--allow-candidates` 없이는 돌지 않고, 표에 "진단용"이 찍힙니다.

## 새 항목을 더할 때

1. 원본(PDF·스캔)에서 한 쪽을 `image.png` 로 둡니다. 정답을 그린 그림을 입력으로 쓰지 않습니다.
2. `ref.svg` 를 [SVG_SPEC.md](../SVG_SPEC.md) 대로 만들고 `python -m formgen validate ref.svg` 로 확인합니다.
3. `python -m formgen stats ref.svg` 와 원본을 보고 난이도를 정해 `meta.json` 에 `tier`, 이유, 출처, 해시를 적습니다.
4. 원본의 모든 기재 칸이 주석됐는지 다른 사람이 확인한 뒤에만 `gold_approved: true` 로 바꿉니다. 자기 자신과 채점해 1.0 이 나오는 것은 승인 근거가 아닙니다.
5. 세트를 정한 뒤에는 고치지 않습니다. 바꾸면 새 이름(`…_v2`)으로 둡니다.

## 알아 둘 점

- 여기 있는 서식은 공개된 빈 서식과 합성 그림뿐입니다. 실서류는 넣지 않습니다.
- 공식 서식 PDF 는 누구나 내려받을 수 있는 것이지만 **재배포 허용 여부는 확인하지 않았습니다** (`rights_status`). 저장소를 밖에 공개하기 전에 확인이 필요합니다.
- 채워진 실제 스캔·사진은 아직 없습니다. 빈 서식에서 잰 통과율이 채워진 스캔에도 그대로 나온다고 볼 근거는 없습니다.
