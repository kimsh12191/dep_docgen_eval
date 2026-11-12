# 출력 규격: 값 자리를 표시한 html 한 파일

모델이 서류 이미지를 보고 내놓는 것, 그리고 평가 세트의 정답(`ref.html`)이 따르는 꼴입니다.
채점기(`formgen/`)는 이 꼴의 html 을 글자로 읽어 채점합니다. 브라우저로 그리지 않습니다.

## 1. 파일

- html 파일 하나. `<!doctype html>` 로 시작해 `</html>` 로 끝납니다.
- 모양은 `<style>` 안의 CSS 로 적습니다. `<script>`, 외부 주소(그림·글꼴·스타일의 `http…`)는 쓰지 않습니다.
- 쪽은 A4 세로(794 × 1123px)를 기준으로 합니다.

## 2. 인쇄 문구

서류에 **인쇄돼 있는 글자**(제목, 항목명, 안내문, 보기 글자)는 보이는 그대로 적습니다.
고객마다 달라지는 **값**(이름, 번호, 금액, 날짜, 체크 표시, 도장, 서명)은 적지 않고 값 자리로 표시합니다.

## 3. 값 자리

값이 들어갈 자리마다 빈 `<span>` 하나를 둡니다.

```html
<span data-field="holder.name" data-label="예금주" data-type="text"></span>
```

| 속성 | 뜻 |
|---|---|
| `data-field` | 키. 영어 소문자·숫자·밑줄, 점으로 나눈 경로 (`applicant.name`, `loan.amount`). "누구의 무엇"으로 짓습니다 |
| `data-label` | 서류에 인쇄된 항목명 그대로 (`예금주`) |
| `data-type` | `text` `number` `amount` `date` `checkbox` `seal` `signature` 중 하나 |
| `data-options` | 체크 칸만. 보기를 `\|` 로 이어 적습니다 (`발행\|미발행`) |

- **체크 칸**: 보기 묶음 하나에 값 자리 하나를 보기들 **앞에** 둡니다. 보기 글자와 상자(□)는 인쇄 문구로 그대로 적습니다.

  ```html
  <span data-field="passbook" data-label="통장발행" data-type="checkbox" data-options="발행|미발행"></span>□ 발행 □ 미발행
  ```

- **도장·서명**: 찍거나 쓰는 자리에 `data-type="seal"` / `"signature"` 값 자리를 둡니다. 도장·서명 그림은 그리지 않습니다.
- **값 자리 안의 글자는 채점하지 않습니다.** 비워 두는 것이 기본입니다.

## 4. 표

- 선으로 나뉜 칸은 `<table>` 로 적습니다. 합친 칸은 `rowspan` · `colspan` 으로 적습니다.
- 값이 들어갈 빈 칸에는 값 자리를 넣습니다.
- **행 수가 서류마다 달라지는 표**(거래 내역 등)는 값 행을 **한 번만** 적어도 됩니다.
  채점기는 칸 나눔과 인쇄 문구가 같은 연속된 행을 한 행으로 봅니다.

## 5. 예

```html
<!doctype html>
<html><head><meta charset="utf-8"><style>
  .page { width: 794px; padding: 56px; font-size: 12px; }
  table { width: 100%; border-collapse: collapse; }
  td, th { border: 1px solid #000; padding: 2px 6px; height: 26px; }
  th { background: #f2f2f2; font-weight: normal; }
</style></head><body><div class="page">
  <h1>거 래 내 역 확 인 서</h1>
  <table>
    <tr><th>예금주</th><td><span data-field="holder.name" data-label="예금주" data-type="text"></span></td>
        <th>계좌번호</th><td><span data-field="account.number" data-label="계좌번호" data-type="text"></span></td></tr>
    <tr><th>용도</th><td colspan="3"><span data-field="purpose" data-label="용도" data-type="checkbox" data-options="대출신청|기타"></span>□ 대출신청 □ 기타</td></tr>
  </table>
  <table>
    <tr><th>거래일</th><th>적요</th><th>출금</th><th>입금</th></tr>
    <tr><td><span data-field="rows.date" data-label="거래일" data-type="date"></span></td>
        <td><span data-field="rows.memo" data-label="적요" data-type="text"></span></td>
        <td><span data-field="rows.out" data-label="출금" data-type="amount"></span></td>
        <td><span data-field="rows.in" data-label="입금" data-type="amount"></span></td></tr>
  </table>
  <p><span data-field="issue_date" data-label="발급일" data-type="date"></span></p>
  <p>○○은행장 <span data-field="seal.bank" data-label="은행장" data-type="seal"></span></p>
</div></body></html>
```

## 6. 유효하지 않은 것

| 코드 | 뜻 |
|---|---|
| `empty` | 내용이 없다 |
| `no_fields` | 값 자리가 하나도 없다 |
| `script` · `external` | `<script>` 또는 외부 주소가 있다 |
| `unclosed_table` · `truncated` | 표가 닫히지 않았거나 `</html>` 로 끝나지 않는다 (출력이 잘림) |

값 자리의 속성이 빠졌거나 틀린 것(`field_key` `field_type` `field_label` `field_options`)은 유효성은 깨지 않고 개수만 셉니다.
