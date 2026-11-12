# gov · hana · hf 평가 후보 60쪽 (48개 소스 서식)

**사람 최종 선정 전 후보 세트입니다. 기준 HTML은 아직 없습니다.**

소스 커밋: [172748589e020d3f7fe91b7ebcfe8d687ac58a27](https://github.com/kimsh12191/document_gen/commit/172748589e020d3f7fe91b7ebcfe8d687ac58a27)

로컬에서 `index.html`을 열면 원본·선정 사유·계열·검수 항목을 볼 수 있습니다. 채택/보류/제외와 메모를 기록하고 결정을 JSON으로 내려받으세요.

전체 원본 목록과 1차 제외 사유는 `inventory.json`, 후보 메타데이터는 `manifest.json`에 있습니다.

## 사람이 확인할 것

- 실제 업무 대표성, 판독 가능성, 문서 전체 포함 여부
- 같은 양식의 개정판·유사 동의서 중복, 기존 학습/개발 노출 여부
- 반복 표인지 고정 격자인지, 필수 필드 누락, 빈칸 해석
- 난이도와 개발/테스트 분할은 미지정입니다. 같은 family의 모든 페이지를 함께 묶습니다.
- 다중 페이지에서 고른 한 장의 재현 평가이며 문서 전체 연결 평가는 아닙니다.
- source_fields.json은 원본 서식 전체의 참고 정의입니다. 선택 페이지의 필드를 따로 검수하세요.
- 페이지 평균은 많이 뽑은 서식을 과대 반영합니다. 계열 내 평균 후 계열 간 평균도 함께 보세요. family_weight를 기록했으며 기존 evaluate는 아직 페이지 평균입니다.
- 빈 원본만으로 부족한 값 추출 평가는 별도 합성값 입력 세트로 보완

## 채택 이후

```bash
python tools/prepare_form_candidates.py promote \
  --candidates evalset/forms_candidates_v2 --decisions decisions.json --out evalset/forms_selected_v1
```

채택 문서의 image.png/meta.json만 새 폴더로 옮깁니다. 모델로 기준 초안을 생성해 reference/에 넣고, `python -m tplgen review evalset/forms_selected_v1`에서 별도로 승인하세요.

source_fields.json과 source_text.txt는 원본 추출 참고자료이며 검수된 정답이 아닙니다. 기존 document_gen HTML은 절대 배치·전용 helper를 사용하므로 현재 tplgen 규격의 정답으로 그대로 복사하지 않습니다.

원본 PDF를 메타데이터의 raster_dpi(기본 120, 고난도 추가분 160) PNG로 변환했을 뿐 고객 값을 합성하거나 원본에 추가하지 않았습니다. 합성값 문서는 소스 저장소 지침에 따라 studio에서 준비해야 합니다.

| ID | 이름 | 난이도(제안) | 선정 이유 |
|---|---|---|---|
| [gov_business_proof](gov_business_proof/image.png) | 사업자등록증명 | 하 | 사업자 기본 항목·발급 문구 |
| [gov_financial_proof](gov_financial_proof/image.png) | 표준재무제표증명 | 하 | 증명서 표지·고정 문구와 변수 구분 |
| [gov_national_tax](gov_national_tax/image.png) | 납세증명서 | 하 | 납세 증명·신청인 항목 |
| [gov_pension](gov_pension/image.png) | 국민연금가입자 증명서 | 하 | 가입 증명·날짜와 번호 |
| [gov_foreign_household](gov_foreign_household/image.png) | 외국인체류확인서 | 중 | 외국인 체류 정보·목록 형태 |
| [gov_resident_copy](gov_resident_copy/image.png) | 주민등록표(등본) | 중 | 세대원 관계·목록과 주석 |
| [gov_seal](gov_seal/image.png) | 인감증명서 | 중 | 인감 영역·격자와 신원 항목 |
| [gov_signature](gov_signature/image.png) | 본인서명사실확인서 | 중 | 서명 영역·용도와 인적사항 |
| [gov_income](gov_income/image.png) | 소득금액증명 | 상 | 소득 구역·복합 표와 작은 글씨 |
| [gov_land](gov_land/image.png) | 토지대장 | 상 | 가로 서식·토지 이력 격자 |
| [gov_vat_base](gov_vat_base/image.png) | 부가가치세 과세표준증명 | 상 | 과세기간·금액 반복 행 |
| [gov_tax_payment_history](gov_tax_payment_history/image.png) | 납부내역증명 | 상 | 납부내역 표·여러 날짜와 금액 |
| [hana_official_028](hana_official_028/image.png) | 위임장 | 하 | 위임장·위임인과 대리인 구분 |
| [hana_official_029](hana_official_029/image.png) | 사용인감계(금융계좌개설용) | 하 | 인감 신고·도장 자리 |
| [hana_official_051](hana_official_051/image.png) | 대출계약 철회신청서 | 하 | 철회 신청·신청인과 계약 정보 |
| [hana_official_420](hana_official_420/image.png) | 비대면 계좌개설 안심차단 서비스 신청서 | 하 | 신청 종류 체크·고객 기본 정보 |
| [hana_official_011](hana_official_011/image.png) | 예금(신탁)잔액증명 의뢰서 | 중 | 잔액증명 의뢰·체크와 계좌 목록 |
| [hana_official_139](hana_official_139/image.png) | 《기업》 지급보증거래 신청서(서면.전자 지급보증 겸용) | 중 | 기업 지급보증·여러 금액과 조건 |
| [hana_official_157](hana_official_157/image.png) | 여신거래용 인감명판 등 신고서 | 중 | 인감명판 신고·복수 기재 영역 |
| [hana_official_060](hana_official_060/image.png) | [필수] 개인(신용)정보 수집이용 동의서(대출성상품 적합성적정성 판단용) | 중 | 동의서·고정 법정 문구 보존 |
| [hana_official_024](hana_official_024/image.png) | 금융거래정보제공(요구·동의)서 | 상 | 금융정보 동의·다수 선택지 |
| [hana_official_061](hana_official_061/image.png) | 적합성, 적정성 고객정보 확인서(개인 및 개인사업자용) | 상 | 적합성 질문·복합 체크 그룹 |
| [hana_official_408](hana_official_408/image.png) | 본인확인서(FATCA CRS 개인,개인사업자용)(국문) | 상 | FATCA CRS·국가 정보와 선택 항목 |
| [hana_official_419](hana_official_419/image.png) | [필수] 개인(신용)정보 수집 · 이용 동의서 (비여신 금융거래) | 상 | 밀집된 동의 문구·작은 글씨 |
| [hf007](hf007/image.png) | 질권실행 의뢰서(수신_제3자 질권용) | 중 | 예금·계좌 목록과 신청 내용 |
| [hf021](hf021/image.png) | 일괄처리(지급)요청서 | 상 | 일괄 지급·밀집된 표와 선택지 |
| [hf037](hf037/image.png) | 위탁유가증권 반환청구서 | 상 | 유가증권·많은 반복 셀 |
| [hf086](hf086/image.png) | 미래채권담보대출 협력기업 일괄추천서 | 상 | 협력기업 목록·고밀도 반복 행 |
| [hf144](hf144/image.png) | 동산담보 제공 예정내역서(개별동산용) | 중 | 동산 담보·품목별 반복 표 |
| [hf177](hf177/image.png) | 퇴직연금 운용상품지정 신청서(DC) | 상 | 퇴직연금 운용상품·표와 체크 혼합 |
| [hf181](hf181/image.png) | 이전 가입자 명부(DC,기업형 IRP용) | 상 | 가입자 명부·여러 열과 반복 행 |
| [hf201](hf201/image.png) | 거래외국환지정(변경)신청서(영문) | 하 | 영문 외환 신청·언어 다양성 |
| [hf293](hf293/image.png) | 「외국환서식관리프로그램」선적서류 수령증 및 수입화물 대도(T/R)신청서 | 상 | 무역·선적서류 목록과 작은 글씨 |
| [hf342](hf342/image.png) | 해외은행 계좌정보 수신서비스(SWIFT MT940) 이용신청서 | 중 | 전자금융·해외계좌 정보와 선택지 |
| [hf387](hf387/image.png) | HANA FX TRADING SYSTEM 자동결제 이용신청서 | 상 | 파생상품·자동결제 표와 체크 혼합 |
| [hf436](hf436/image.png) | 주주명부(법인 비대면 실명확인 서비스 용) | 중 | 주주명부·금액과 지분 목록 |
| [gov_withholding__p01](gov_withholding__p01/image.png) | 근로소득 원천징수영수증 | 상 | 근로소득 원천징수 본표: 인적사항·소득·세액 복합 표 |
| [gov_withholding__p02](gov_withholding__p02/image.png) | 근로소득 원천징수영수증 | 상 | 정산명세: 계층형 공제 항목·좌우 병렬 표 |
| [gov_withholding__p03](gov_withholding__p03/image.png) | 근로소득 원천징수영수증 | 상 | 소득·세액공제 명세: 다단 머리글·인적공제 표시 |
| [gov_withholding__p06](gov_withholding__p06/image.png) | 근로소득 원천징수영수증 | 상 | 연금·저축 공제명세: 여러 반복 표·계좌·금액 |
| [gov_withholding__p07](gov_withholding__p07/image.png) | 근로소득 원천징수영수증 | 상 | 월세·임차차입금 명세: 다단 머리글·긴 주소·금액 |
| [gov_retirement_withholding__p10](gov_retirement_withholding__p10/image.png) | 퇴직소득 원천징수영수증 | 상 | 퇴직소득 원천징수 앞쪽: 근속연수·과세표준·세액 격자 |
| [gov_pension_withholding__p20](gov_pension_withholding__p20/image.png) | 연금소득 원천징수영수증 | 상 | 연금소득 원천징수: 지급액·인적공제·정산 복합 격자 |
| [gov_income_tax_return__p03](gov_income_tax_return__p03/image.png) | 종합소득세 과세표준확정신고 및 납부계산서(일반) | 상 | 종합소득 신고 본표: 선택지·신고인·세액 계산 |
| [gov_income_tax_return__p09](gov_income_tax_return__p09/image.png) | 종합소득세 과세표준확정신고 및 납부계산서(일반) | 상 | 사업소득명세: 세로 항목 계층·사업장별 열 |
| [gov_income_tax_return__p19](gov_income_tax_return__p19/image.png) | 종합소득세 과세표준확정신고 및 납부계산서(일반) | 상 | 세액감면·공제명세: 상하 표·병합 헤더 |
| [gov_income_tax_return__p21](gov_income_tax_return__p21/image.png) | 종합소득세 과세표준확정신고 및 납부계산서(일반) | 상 | 가산세명세: 다단 행 그룹·세율·기준금액 |
| [gov_local_assessment__p01](gov_local_assessment__p01/image.png) | 지방세 세목별 과세증명서 | 상 | 지방세 세목별 과세증명: 한영 병기·세목별 내역 |
| [gov_local_assessment__p02](gov_local_assessment__p02/image.png) | 지방세 세목별 과세증명서 | 상 | 재산세 토지 부표: 필지별 반복 블록·세액 |
| [gov_building_general__p01](gov_building_general__p01/image.png) | 일반건축물대장(갑) | 상 | 건축물대장 앞쪽: 가로 배치·면적·용도·소유자 |
| [gov_building_general__p02](gov_building_general__p02/image.png) | 일반건축물대장(갑) | 상 | 건축물대장 계속면: 설비·인허가·변동 이력 |
| [hana_corporate_agreement__p01](hana_corporate_agreement__p01/image.png) | 여신거래약정서(기업용) | 상 | 기업 여신 약정: 조건별 선택·금액·금리 |
| [hana_corporate_agreement__p02](hana_corporate_agreement__p02/image.png) | 여신거래약정서(기업용) | 상 | 기업 여신 약정 계속: 긴 약관·상환 조건·선택지 |
| [hana_personal_agreement__p01](hana_personal_agreement__p01/image.png) | 대출거래약정서(가계용) | 상 | 가계 대출 약정: 금리 유형·상환 방식·조건별 칸 |
| [hana_official_413__p01](hana_official_413__p01/image.png) | 고객확인서(법인,고유번호나 납세번호가 있는 임의 단체용) | 상 | 법인 고객확인: 신원·대표자·연락처·업종 |
| [hana_official_413__p02](hana_official_413__p02/image.png) | 고객확인서(법인,고유번호나 납세번호가 있는 임의 단체용) | 상 | 법인 실제소유자 확인: 반복 인적사항·판단 단계 |
| [hana_official_428__p01](hana_official_428__p01/image.png) | 본인확인서(FATCA CRS 법인,임의단체용)(국문) | 상 | 법인 FATCA CRS: 분류 선택지·거주지국·납세번호 |
| [hana_official_428__p02](hana_official_428__p02/image.png) | 본인확인서(FATCA CRS 법인,임의단체용)(국문) | 상 | 법인 FATCA 추가확인: 계층형 질문·다수 선택지 |
| [hf174__p01](hf174__p01/image.png) | 퇴직연금 계약이전 동의서 | 상 | 퇴직연금 계약이전 동의: 고밀도 목록·반복 체크 |
| [hf038__p01](hf038__p01/image.png) | 수표(어음)발행사실 확인의뢰서 | 상 | 수표·어음 발행 확인: 많은 반복 셀·좁은 열 |

후보 화면을 로컬 웹으로 열려면 다음 명령 후 `http://127.0.0.1:8766`에 접속하세요.

```bash
python -m http.server 8766 --bind 127.0.0.1 --directory evalset/forms_candidates_v2
```
