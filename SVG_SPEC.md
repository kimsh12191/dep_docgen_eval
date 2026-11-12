# SVG 서식 규격 (svg-v1)

모델이 내는 것과 정답(`ref.svg`)이 따르는 꼴입니다. 검사는 `python -m formgen validate x.svg`, 코드는 `formgen/svg.py`.

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="794" height="1123" viewBox="0 0 794 1123">
  <text x="30" y="60" font-size="16" font-family="Malgun Gothic">성명</text>
  <rect x="100" y="40" width="200" height="30" fill="none" stroke="black"/>
  <rect data-field="applicant.name" data-label="성명" data-type="text"
        x="100" y="40" width="200" height="30" fill="none" stroke="none"/>
</svg>
```

| 무엇 | 규칙 |
|---|---|
| 쪽 | SVG 하나 = 한 쪽. `viewBox="0 0 W H"` (A4 는 794×1123, 다른 비율이면 그 비율로). 한 변 5000 이하 |
| 인쇄 문구 | `<text>` 로 적습니다. 글자를 선(path)으로 그리지 않습니다 |
| 선·칸 | `rect` `line` `path` 등으로 그립니다 |
| 값 자리 | 루트 바로 아래의 `<rect>`. 보이지 않는 표시이므로 칸의 테두리는 따로 그립니다. `transform` 금지, 쪽 안에 있어야 함 |
| `data-field` | 문서 안에서 하나뿐인 키. 영문 소문자·숫자·밑줄, 점으로 나눈 경로 |
| `data-label` | 서류에 인쇄된 항목명 |
| `data-type` | `text` `number` `amount` `date` `checkbox` `seal` `signature`. 전화·계좌·식별번호는 `text` |
| `data-options` | 체크 칸만. 보기를 `\|` 로 이음 (`신청\|미신청`). 보기 묶음 하나가 값 자리 하나 |
| 채워진 값 | 이름·번호·금액·날짜·체크 표시·도장·서명은 지우고 값 자리로 표시합니다 |
| 허용 요소 | `svg g rect line polyline polygon path circle ellipse text tspan title desc` |
| 금지 | `script` `style` `image` `use` `foreignObject`, `href`·`style`·`class`·이벤트 속성, `url()`, DOCTYPE, 숨긴 내용 |

유효하지 않은 것: XML 이 깨짐(잘림 포함), 값 자리 없음, `<text>` 없음, 위 금지 사항, 값 자리 속성이 빠지거나 틀림.

모델에 주는 지시문은 `formgen/prompts/svg_v1.md` 입니다. 지시문을 바꾸면 새 파일(`svg_v2.md`)로 두고 `formgen/make.py` 의 `PROMPT_VERSION` 을 바꿉니다.
