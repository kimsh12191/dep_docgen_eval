"""표 구조 점수 실험: 합친 칸이 많은 표(원천징수영수증의 거주구분 표)를 정답으로 두고,
모델이 흔히 내는 틀린 꼴을 손으로 만들어 점수가 순서대로 떨어지는지 본다.

실행: python experiments/table_structure_demo.py
기대: 그대로 = 촘촘한 격자 = 오타 ≈ 1.0  >  경계 하나 틀림  >  한 행 빠짐  >  합치기를 모두 버림
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from formgen.html.tables import parse_tables, shape, table_score  # noqa: E402

F = lambda key, label, t="text": f'<span data-field="{key}" data-label="{label}" data-type="{t}"></span>'
C = lambda key, label: F(key, label, "checkbox")

# 격자 열 5개 (A B C D E). 행마다 나뉘는 자리가 달라 거의 모든 칸이 합친 칸이다.
ROWS = [
    [("거주구분", 2), (C("residency", "거주구분") + "거주자1 / 비거주자2", 3)],
    [("거주지국", 1), (F("residence.country", "거주지국"), 1), ("거주지국코드", 2), (F("residence.code", "거주지국코드"), 1)],
    [("내·외국인", 2), (C("foreigner", "내·외국인") + "내국인1 / 외국인9", 3)],
    [("외국인단일세율적용", 3), (C("flat_tax", "외국인단일세율적용") + "여1 / 부2", 2)],
    [("외국법인소속 파견근로자 여부", 3), (C("dispatched", "외국법인소속 파견근로자 여부") + "여1 / 부2", 2)],
    [("종교관련종사자 여부", 3), (C("religious", "종교관련종사자 여부") + "여1 / 부2", 2)],
    [("국적", 1), (F("nationality", "국적"), 1), ("국적코드", 2), (F("nationality.code", "국적코드"), 1)],
    [("세대주 여부", 2), (C("householder", "세대주 여부") + "세대주1 / 세대원2", 3)],
    [("연말정산 구분", 2), (C("settlement", "연말정산 구분") + "계속근로1 / 중도퇴사2", 3)],
]


def html(rows):
    out = ["<table>"]
    for row in rows:
        out.append("<tr>" + "".join(f'<td colspan="{n}">{t}</td>' if n > 1 else f"<td>{t}</td>" for t, n in row) + "</tr>")
    return "\n".join(out + ["</table>"])


def no_spans(rows):          # 합치기를 모두 버림: 모든 행을 4칸으로 (모자라면 빈 칸)
    return [[(t, 1) for t, _ in row] + [("", 1)] * (4 - len(row)) for row in rows]


def two_cols(rows):          # 2열로 펴기: 4칸짜리 행을 두 행으로 나눔
    out = []
    for row in rows:
        cells = [(t, 1) for t, _ in row]
        out += [cells[:2], cells[2:]] if len(cells) == 4 else [cells]
    return out


def same_boundary(rows):     # 경계 하나 틀림: 여/부 행의 나뉘는 자리를 다른 행과 같게 (3+2 → 2+3)
    return [[(row[0][0], 2), (row[1][0], 3)] if [n for _, n in row] == [3, 2] else row for row in rows]


def typo(rows):              # 글자만 조금 다름 (띄어쓰기·한 글자)
    return [[(t.replace("파견근로자 여부", "파견근로자여부").replace("세대주 여부", "세대주여부").replace("연말정산", "년말정산"), n) for t, n in row] for row in rows]


def finer(rows):             # 같은 모양을 두 배 촘촘한 격자로 (colspan 을 모두 2배)
    return [[(t, n * 2) for t, n in row] for row in rows]


VARIANTS = [
    ("그대로", ROWS),
    ("같은 모양, 더 촘촘한 격자", finer(ROWS)),
    ("글자만 조금 다름", typo(ROWS)),
    ("경계 하나 틀림 (여/부 행)", same_boundary(ROWS)),
    ("한 행 빠짐", ROWS[:4] + ROWS[5:]),
    ("2열로 펴기 (합치기 없음)", two_cols(ROWS)),
    ("합치기를 모두 버림 (4칸 격자)", no_spans(ROWS)),
    ("칸 표시를 안 함 (값 자리 없음)", [[(t.split("</span>")[-1], n) for t, n in row] for row in ROWS]),
]

if __name__ == "__main__":
    gt = parse_tables(html(ROWS))[0]
    print("정답 표:", shape(gt))
    print(f'{"만든 것":28s} 표구조F1  합친칸재현  칸수  합친칸  값자리')
    for name, rows in VARIANTS:
        s = table_score(gt, parse_tables(html(rows))[0])
        print(f'{name:28s} {s["table_f1"]:7.3f}  {s["span_recall"]:9.3f}  {s["cells_pred"]:4d}  {s["spans_pred"]:5d}  {s["fields_pred"]:5d}')
