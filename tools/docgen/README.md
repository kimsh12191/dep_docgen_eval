# tools/docgen: 평가 세트를 만들 때만 쓰는 도구

여기 있는 것은 **document_gen(docgen)과 브라우저가 있는 곳에서만** 돕니다. 벤치마크를 돌릴 때는 쓰지 않습니다.
`formgen/` 은 이 폴더를 부르지 않습니다.

| 파일 | 하는 일 |
|---|---|
| `export_items.py` | docgen 서식을 그려 평가 항목(그림 + 정답 html)으로 내보낸다 → `bench/` |
| `measure_difficulty.py` | 1단계: 난이도 기준 v0 을 템플릿 139종에 적용 (기록) |
| `bridge.py`, `sheet.py`, `posscore.py`, `posselftest.py` | 2단계 기록: 그려서 잰 위치로 채점하던 방식과 그 자체 검증 |

```bash
export DOCGEN_ROOT=/path/to/document_gen
python -m tools.docgen.export_items --pool data/roundtrip_pool_v0.json --out bench/roundtrip_v0
```
