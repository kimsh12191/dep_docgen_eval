# 평가용 정답 라벨 `labels.json`

원본 이미지에 **무엇이 어디에 있는지**를 미리 적어 둔 파일. 평가는 이 파일과 모델 템플릿을 그린 결과를 맞춰 본다 (평가 때 OCR·PDF 가 필요 없다).
항목 폴더마다 하나: `evalset/v1/<id>/labels.json`, `evalset/forms_candidates_v2/<id>/labels.json`. 만드는 법은 `tools/build_labels.py`.

```
{
  "image": "image.png", "image_sha256": "…", "width": 1588, "height": 2246,
  "frame": null | {"kind": "paper", "width", "height", "how"},   사진이면 좌표는 편 종이 기준 (tplgen.check.paper 와 같은 방법)
  "texts":  [{"text": "질권설정등록청구서", "box": [x0,y0,x1,y1], "role": "fixed" | "value", "key": 값 이름 | null, "box_estimated"?: true}],
  "rules":  [[x0,y0,x1,y1], …]                 가로·세로 선 (표의 칸)
  "slots":  [{"box", "kind": text|check|seal|sign, "label", "key", "filled": 값이 적혀 있나, "source"}]   기재란
  "assets": [{"kind": image|logo|barcode|qr, "box"}]
  "provenance": {texts·rules·slots·assets 를 어디서 얻었나}, "source": {…}, "reviewed_by_human": false
}
```
- `role: fixed` = 템플릿에 고정 글자로 있어야 하는 것, `value` = 값 자리로 빠져야 하는 것 (원본에 적힌 값).
- `key` 는 기준 꾸러미(`reference/`)나 서식 정의의 값 이름이다. 평가는 이름이 아니라 **위치와 글자**로 맞추므로 모델이 다른 이름을 써도 된다.
- 빈 서식(후보 60쪽)에는 값이 없다 → `texts` 는 모두 fixed, 기재란은 `slots` 로만 안다.

## 출처와 정확도

| 항목 | 글자 | 선 | 기재란 | 정확도 |
|---|---|---|---|---|
| 후보 60쪽 (gov·hana·hf 빈 서식) | 원본 PDF 글자층 | PDF 벡터 | hana·hf 30쪽: 서식 정의 칸 · gov 30쪽: **없음** | 정확 (PDF 와 같은 좌표계) |
| v1 `hf138` `hf153` | PDF 글자층 + docgen 이 채운 값 (같은 seed 로 다시 그려 이미지 해시 일치 확인) | PDF 벡터 | 서식 정의 칸 | 정확 |
| v1 `hf153_scan` | hf153 라벨을 scanify 의 회전(1.2°)으로 옮김 | 같음 (기울어진 상자) | 같음 | 정확 (잡음은 위치를 안 바꿈) |
| v1 `irs_f8949` `irs_fw9` | IRS PDF 글자층 | PDF 벡터 | PDF 입력 칸 | 정확 |
| v1 `statement` `invoice_handwritten` `invoice_photo_skewed` | OCR 위치 + 기준 꾸러미의 같은 줄 글자 (+ `tools/labels_manual/` 고침) | 이미지에서 찾은 긴 선 | 값 글자 위치 | 위치 ±몇 px, 글자는 기준 꾸러미를 따름 |
| v1 `receipt_photo` | OCR 검출 상자 + 사진을 보고 직접 적은 글자 (한글 OCR 인식이 쓸 수 없는 수준) | 이미지 선 | 값 글자 위치 | 대략. 맨 아래 두 줄·바코드·QR 상자는 눈대중 |

`box_estimated: true` = 한 줄 상자를 항목명과 값으로 나눌 때 글자 폭(한글 2)으로 어림한 것.

## 한계
- **사람이 검수하지 않았다.** 겹쳐 그린 그림으로 9개 v1 과 후보 3쪽을 눈으로 확인했다 (상자가 글자 위에 맞게 놓임).
- OCR 항목의 글자·역할은 기준 꾸러미를 따른다 — 기준 꾸러미가 틀렸으면 라벨도 틀린다. 기준 꾸러미는 이미지와 대조해 만들었지만 사람 검수는 없다.
- gov 빈 서식 30쪽은 기재란 정의가 없다. 빈 칸은 선(`rules`)과 항목명으로 판단해야 한다.
- 체크 표시·서명·도장은 글자가 아니라 `texts` 에 없다.
- 이미지에서 찾은 선(`image_lines`)은 짧은 선·점선·흐린 선을 놓친다.
