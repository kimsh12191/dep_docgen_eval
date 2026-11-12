# svg 채점기 자체 검증 (svg-v1, bench/official_pilot_v1)

| 항목 | 망가뜨린 방법 | 유효 | 값 자리 | 값 자리+위치 | 겹침 | 문구 F1 | 문구 재현 | 기대대로 |
|---|---|---|---|---|---|---|---|---|
| gov_business_proof | same | 예 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 예 |
| gov_business_proof | drop_half | 예 | 0.67 | 0.67 | 0.50 | 1.00 | 1.00 | 예 |
| gov_business_proof | shift_small | 예 | 1.00 | 1.00 | 0.97 | 1.00 | 1.00 | 예 |
| gov_business_proof | retype | 예 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 | 예 |
| gov_business_proof | half_text | 예 | 1.00 | 1.00 | 1.00 | 0.73 | 0.58 | 예 |
| gov_business_proof | no_text | 아니오 | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 예 |
| gov_business_proof | no_fields | 아니오 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 | 예 |
| gov_business_proof | other_form | 예 | 0.18 | 0.06 | 0.07 | 0.23 | 0.55 | 예 |
| gov_business_proof | truncated | 아니오 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 예 |
| gov_business_proof | empty | 아니오 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 예 |
| gov_income | same | 예 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 예 |
| gov_income | drop_half | 예 | 0.69 | 0.69 | 0.52 | 1.00 | 1.00 | 예 |
| gov_income | shift_small | 예 | 1.00 | 1.00 | 0.84 | 1.00 | 1.00 | 예 |
| gov_income | retype | 예 | 0.13 | 0.13 | 0.13 | 1.00 | 1.00 | 예 |
| gov_income | half_text | 예 | 1.00 | 1.00 | 1.00 | 0.66 | 0.50 | 예 |
| gov_income | no_text | 아니오 | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 예 |
| gov_income | no_fields | 아니오 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 | 예 |
| gov_income | other_form | 예 | 0.14 | 0.00 | 0.00 | 0.06 | 0.04 | 예 |
| gov_income | truncated | 아니오 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 예 |
| gov_income | empty | 아니오 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 예 |
| gov_pension | same | 예 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 예 |
| gov_pension | drop_half | 예 | 0.67 | 0.67 | 0.50 | 1.00 | 1.00 | 예 |
| gov_pension | shift_small | 예 | 1.00 | 1.00 | 0.96 | 1.00 | 1.00 | 예 |
| gov_pension | retype | 예 | 0.50 | 0.50 | 0.50 | 1.00 | 1.00 | 예 |
| gov_pension | half_text | 예 | 1.00 | 1.00 | 1.00 | 0.78 | 0.64 | 예 |
| gov_pension | no_text | 아니오 | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 예 |
| gov_pension | no_fields | 아니오 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 | 예 |
| gov_pension | other_form | 예 | 0.12 | 0.00 | 0.00 | 0.18 | 0.19 | 예 |
| gov_pension | truncated | 아니오 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 예 |
| gov_pension | empty | 아니오 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 예 |
