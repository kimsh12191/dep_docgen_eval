"""schema → 값(json). 대량 생성용 임의 값과, 꾸러미가 견디는지 보는 시험용 값 묶음.

값은 가짜다 (실제 개인정보를 쓰지 않는다). 더 그럴듯한 값이 필요하면 schema.json 을 LLM 에 주고 같은 꼴의 json 을 받아 render 에 넣으면 된다.
"""
from __future__ import annotations

import random

LAST = "김이박최정강조윤장임한오서신권황안송류홍"
FIRST = ["민준", "서연", "도윤", "지우", "하준", "수아", "은우", "지민", "현우", "채원", "영수", "미경", "정훈", "혜진", "상철", "보람"]
COMPANY = ["한빛상사", "대성무역", "누리로지스", "푸른건설", "새한전자", "동아유통", "미래테크", "가온산업"]
CITY = ["서울특별시 중구 을지로", "부산광역시 해운대구 센텀로", "대전광역시 유성구 대학로", "경기도 성남시 분당구 판교로", "인천광역시 연수구 송도대로"]
WORDS = ["사업자금", "급여 수령", "주택 구입", "운영 자금", "물품 대금", "계좌 정리", "투자 목적", "생활비", "해당 없음", "신규 거래"]
LONG = "거래처 대금 결제 및 운영 자금 확보를 위한 신청"


def value(f: dict, rng: random.Random, long: bool = False):
    t, digits = f.get("type"), lambda n: "".join(rng.choice("0123456789") for _ in range(n))
    name = rng.choice(LAST) + rng.choice(FIRST)
    if t == "bool":
        return rng.random() < 0.5
    if t == "choice":
        return rng.choice(f.get("options") or [""])
    if t in ("name", "sign", "seal"):
        return name + ("(대리인 " + rng.choice(LAST) + rng.choice(FIRST) + ")" if long and t == "name" else "")
    if t == "company":
        return ("주식회사 " if rng.random() < 0.5 else "(주)") + rng.choice(COMPANY) + (" 해외영업본부 서울지사" if long else "")
    if t == "date":
        return f"{rng.randint(2019, 2026)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
    if t in ("year", "month", "day"):
        return {"year": str(rng.randint(2019, 2026)), "month": str(rng.randint(1, 12)), "day": str(rng.randint(1, 28))}[t]
    if t == "amount":
        return f"{rng.randint(1, 999_999_999_999 if long else 99_999_999):,}"
    if t == "number":
        return str(rng.randint(1, 999_999 if long else 99))
    if t == "phone":
        return f"010-{digits(4)}-{digits(4)}"
    if t == "account":
        return f"{digits(3)}-{digits(6)}-{digits(5)}"
    if t == "idnum":
        return f"{digits(6)}-{digits(7)}"
    if t == "email":
        return f"user{digits(4)}@example.com"
    if t == "address":
        return f"{rng.choice(CITY)} {rng.randint(1, 999)}, {rng.randint(1, 30)}층" + (" 한빛타워 비동 1203호 (우편번호 04523)" if long else "")
    return LONG if long else rng.choice(WORDS)


def make(schema: dict, rng: random.Random, rows: int | None = None, long: bool = False, empty: bool = False) -> dict:
    """값 한 벌. rows = 표마다 행 수 (None 이면 표의 min~max 안에서 임의)."""
    blank = lambda f: False if f.get("type") == "bool" else ""
    one = (lambda f: blank(f)) if empty else (lambda f: value(f, rng, long))
    data = {f["name"]: one(f) for f in schema.get("fields") or []}
    for tb in schema.get("tables") or []:
        lo, hi = int(tb.get("min_rows", 1)), int(tb.get("max_rows", 30))
        n = rng.randint(lo, max(lo, min(hi, 12))) if rows is None else rows
        data[tb["name"]] = [{c["name"]: one(c) for c in tb.get("columns") or []} for _ in range(n)]
    return data


def stress(schema: dict, sample: dict, seed: int = 0) -> list[tuple[str, dict]]:
    """꾸러미가 견디는지 보는 값 묶음: 예시 그대로 · 임의 값 · 긴 값 · 빈 값 · 표 행 1개 · 표 행 많이."""
    rng = random.Random(seed)
    rows = lambda d: {tb["name"]: len(sample.get(tb["name"]) or []) for tb in schema.get("tables") or []}
    same_rows = max(rows(sample).values(), default=0)
    out = [("sample", sample), ("random", make(schema, rng, same_rows)), ("long", make(schema, rng, same_rows, long=True)),
           ("empty", make(schema, rng, same_rows, empty=True))]
    if schema.get("tables"):
        many = max(int(tb.get("max_rows", 30)) for tb in schema["tables"])
        out += [("rows_1", make(schema, rng, 1)), ("rows_many", make(schema, rng, min(max(many, 20), 40)))]
    return out
