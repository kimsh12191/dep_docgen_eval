문서 이미지 한 장을 **수정 가능한 HTML 템플릿 꾸러미**로 바꾼다. 이 꾸러미에 다른 값을 넣어 같은 문서의 다른 사본을 대량으로 찍는다.

출력은 아래 세 파일뿐이다. 각 파일은 `=== 파일이름 ===` 줄로 시작한다. 설명 글은 쓰지 않는다.

=== template.html ===
(Jinja2 템플릿)
=== schema.json ===
(값의 목록)
=== sample.json ===
(원본 이미지의 내용대로 채운 값)

## template.html
1. `<!doctype html>` 로 시작하는 완결된 HTML. CSS 는 `<style>` 안에만. 외부 파일·글꼴·이미지·`<script>` 금지.
2. 쪽은 `<div class="page">` 하나. 폭 794px(A4 세로, 96dpi), `min-height: 1123px`. 가로 문서면 폭 1123px. 내용이 늘면 아래로 길어져도 된다.
3. 원본과 **같은 배치**로 만든다: 제목, 문단, 표, 칸의 순서와 대략의 위치·크기·정렬. 글꼴은 `sans-serif` 로 두고 맞추려 하지 않는다.
4. **배치는 흐름으로** 만든다: 표는 `<table>`, 나란한 것은 flex/grid, 간격은 margin/padding. `position:absolute` 는 도장처럼 겹쳐 찍는 것에만 쓴다. 표와 그 아래 내용은 절대 위치로 두지 않는다 (행이 늘면 밀려야 한다).
5. 문서마다 달라지는 내용(이름, 번호, 날짜, 금액, 주소, 체크 표시, 서명, 도장, 자유 기재)은 **글자로 박지 않고 값으로** 뺀다:
   `<span data-field="applicant_name">{{ applicant_name }}</span>`
   - 값을 감싼 요소에 `data-field="값의 경로"` 를 단다. 경로는 schema 의 이름과 같다.
   - 인쇄된 항목명, 안내문, 법정 문구, 기관명은 고정 글자로 둔다.
   - 원본에서 비어 있는 기재란도 값으로 만든다 (sample 에서는 빈 문자열).
6. **반복되는 표 행**은 반복문으로 쓴다. 행 수는 값 목록의 길이를 따른다. 원본에 미리 그어진 빈 행도 목록의 행으로 본다.
   ```
   {% for row in items %}<tr>
     <td data-field="items.{{ loop.index0 }}.name">{{ row.name }}</td>
     <td data-field="items.{{ loop.index0 }}.amount">{{ row.amount }}</td>
   </tr>{% endfor %}
   ```
7. 체크 칸: `<span data-field="agree">{{ "☑" if agree else "☐" }}</span> 동의함`. 여럿 중 하나를 고르는 것은 값 하나(choice)로 두고 `{{ "☑" if kind == "신고" else "☐" }} 신고` 처럼 보기마다 쓴다. 이때 data-field 는 보기 묶음 전체를 감싼 요소에 단다.
8. 서명·도장: `<span class="sign" data-field="applicant_sign">{{ applicant_sign }}</span>` / `<span class="seal" data-field="applicant_seal">{{ applicant_seal }}</span>`. 값은 이름 글자다. `.seal` 은 붉은 테두리의 둥근 도장처럼, `.sign` 은 기울인 글씨처럼 CSS 로 꾸민다.
9. 바코드, 로고, 사진, QR 은 그리지 않는다. 같은 크기의 빈 상자로 자리만 남긴다: `<div class="asset" data-asset="barcode" style="width:230px;height:36px"></div>` (종류: barcode, logo, photo, qr, stamp). 로고 옆의 기관명 글자는 글자로 쓴다.
10. 값이 길어지거나 행이 늘어도 깨지지 않게 한다: 칸에 고정 높이를 주지 말고 `min-height` 를 쓰고, 긴 값은 줄바꿈되게 둔다.
11. Jinja2 는 `{{ }}`, `{% for %}`, `{% if %}`, `loop.index0` 만 쓴다.

## schema.json
```
{"title": "문서 이름",
 "fields": [{"name": "applicant_name", "label": "성명", "type": "name"}, ...],
 "tables": [{"name": "items", "label": "거래내역", "min_rows": 1, "max_rows": 30,
             "columns": [{"name": "name", "label": "종류", "type": "text"}, ...]}]}
```
- name: 영문 소문자·숫자·밑줄. template 의 값 이름과 같아야 한다. 모든 항목이 template 에 쓰여야 한다.
- label: 문서에 인쇄된 항목명.
- type: text, name, company, date, year, month, day, amount, number, phone, account, idnum, address, email, bool, choice, sign, seal 중 하나.
  choice 는 `"options": ["신고", "취하"]` 를 함께 쓴다. bool 은 체크 하나.
- 날짜가 년/월/일 칸으로 나뉘어 있으면 year, month, day 세 개로 나눈다. 인쇄된 "20" 뒤에 두 자리만 적는 칸이어도 year 로 두고 값은 네 자리(2026)로 받아 template 에서 `{{ date_year[2:] }}` 처럼 자른다.
- 표가 없으면 `"tables": []`.

## sample.json
schema 의 모든 항목에 대해 **원본 이미지에 적힌 값**을 넣는다. 비어 있으면 `""`, 체크는 true/false, 표는 행의 목록.
이 값으로 template 을 그리면 원본 이미지와 같은 문서가 되어야 한다.
