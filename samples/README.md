# 입력 예시 이미지

| 파일 | 무엇 | 출처 · 라이선스 |
|---|---|---|
| `hf138.png` `hf153.png` `hf225.png` | 하나은행 공개 서식에 가짜 값을 채워 깨끗하게 그린 것 | document_gen 저장소의 원본 서식 (공개 서식 PDF) |
| `hf153_scan.jpg` | `hf153.png` 을 스캔한 것처럼 만든 것 (기울임 1.2°·종이색·얼룩·잡음·jpeg) | `python tools/scanify.py samples/hf153.png samples/hf153_scan.jpg` |
| `receipt_photo.jpg` | 실제로 찍은 한국어 영수증 사진 (배경·구김 있음) | Hugging Face `HumynLabs/Korean_Receipts_Dataset` 의 첫 장 · CC-BY-4.0 · 올린 쪽이 익명화했다고 밝힘 |
| `statement.jpg` | 합성 은행 거래내역서 (거래 표가 길게 이어짐) | Hugging Face `Panhapich/bank-statement-structure-recognition` 의 첫 장 · MIT · 합성 데이터 |

실제 스캔본(사람이 스캐너로 뜬 관공서·기관 문서)은 아직 없다. 실서류는 여기 넣지 않는다.
