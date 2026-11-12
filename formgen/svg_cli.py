"""Experimental diagnostic SVG CLI (svg-eval-v2 / v3): python -m formgen svg score|score-v3|bench|make|validate|render.

The pass-rate table lives in formgen/bench.py (python -m formgen bench). No imports of browser or authoring libraries.
"""
import argparse
import json
import hashlib
from statistics import fmean
import re
from pathlib import Path
from . import svg,svg_eval_v2,svg_eval_v3,llm


def dump(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


# 생성은 formgen/make.py 한 곳에서 한다 (make · bench · harness 가 같은 함수를 쓴다).
from .make import make  # noqa: E402,F401


def _read(path):
    return Path(path).read_text(encoding="utf-8-sig")


def _summary(rows):
    metrics = [("fields", "field_detection_f1"), ("fields", "field_semantic_f1"),
               ("fields", "field_located_semantic_f1"), ("recognition", "text_f1"),
               ("text_geometry", "text_located_f1")]
    def group(subset):
        scores = {}
        for section, key in metrics:
            values = [r[section].get(key) for r in subset if r[section].get(key) is not None]
            scores[key + "_mean"] = round(fmean(values), 4) if values else None
        visual = [r["visual"].get("prediction_vs_source", {}).get("ink", {}).get("f1")
                  for r in subset if r["visual"].get("status") == "ok"]
        visual = [n for n in visual if n is not None]
        return {"n_images": len({r["id"] for r in subset}), "n_attempts": len(subset),
                "valid_attempts": sum(bool(r["valid"]) for r in subset),
                "visual_attempts": len(visual),
                "ink_f1_mean": round(fmean(visual), 4) if visual else None,
                **scores}
    def v3_group(subset):
        result=group(subset)
        items=[r["similarity_v3"] for r in subset if "similarity_v3" in r]
        if items:
            scored=[v["score_0_100"] for v in items if v["score_0_100"] is not None]
            result["v3"]={"n_attempts":len(items),"n_scored":len(scored),
                          "score_mean":round(fmean(scored),2) if scored else None,
                          "n_unscored":len(items)-len(scored)}
        return result
    tiers = sorted({r["tier"] for r in rows if r.get("tier")})
    return {"all": v3_group(rows), "by_tier": {tier:v3_group([r for r in rows if r.get("tier") == tier]) for tier in tiers},
            "final_pass": None,
            "note": "Diagnostic means across attempts; repeats of the same image are correlated"}

def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m formgen svg")
    sub = ap.add_subparsers(dest="action", required=True)
    m = sub.add_parser("make")
    for key in ("image", "out", "endpoint", "model"): m.add_argument("--" + key, required=True)
    m.add_argument("--max-tokens", type=int, default=16000)
    m.add_argument("--api-key")
    s = sub.add_parser("score")
    s.add_argument("ref"); s.add_argument("pred"); s.add_argument("--out")
    s.add_argument("--source-image"); s.add_argument("--visual", action="store_true")
    s.add_argument("--font-file", action="append")
    s3 = sub.add_parser("score-v3")
    s3.add_argument("--source-image", required=True)
    s3.add_argument("--pred", required=True)
    s3.add_argument("--regions", required=True)
    s3.add_argument("--out")
    s3.add_argument("--font-file", action="append")
    s3.add_argument("--tolerance", type=int, default=2)
    s3.add_argument("--require-grits", action="store_true")
    r = sub.add_parser("render")
    r.add_argument("input"); r.add_argument("--out", required=True); r.add_argument("--font-file", action="append")
    v = sub.add_parser("validate"); v.add_argument("input")
    b = sub.add_parser("bench")
    for key in ("items", "out", "endpoint", "model"): b.add_argument("--" + key, required=True)
    b.add_argument("--allow-candidates", action="store_true")
    b.add_argument("--max-tokens", type=int, default=16000); b.add_argument("--api-key")
    b.add_argument("--repeat", type=int, default=1)
    b.add_argument("--visual", action="store_true"); b.add_argument("--font-file", action="append")
    b.add_argument("--v3", action="store_true")
    b.add_argument("--v3-require-grits", action="store_true")
    args = ap.parse_args(argv)
    read = _read
    if args.action == "make":
        result = make(args.image, args.out, args.endpoint, args.model, args.max_tokens, args.api_key)
    elif args.action == "validate":
        result = svg.parse(read(args.input))
    elif args.action == "score":
        if args.visual and not (args.source_image and args.out):
            ap.error("--visual requires --source-image and --out")
        result = svg_eval_v2.evaluate(read(args.ref), read(args.pred),
                    source_image=args.source_image,
                    output_dir=Path(args.out).parent / "visual_assets" if args.out else None,
                    font_files=args.font_file, visual=args.visual)
        if args.out: dump(args.out, result)
    elif args.action == "score-v3":
        result = svg_eval_v3.evaluate(args.source_image, args.pred, args.regions,
            output_dir=Path(args.out).parent / "v3_visual_assets" if args.out else None,
            font_files=args.font_file, tolerance=args.tolerance, require_grits=args.require_grits)
        if args.out:dump(args.out,result)
    elif args.action == "render":
        result = svg.render(read(args.input), args.out, args.font_file)
        dump(str(args.out) + ".json", result)
    else:
        if args.repeat < 1: ap.error("--repeat must be >= 1")
        items = sorted(p for p in Path(args.items).iterdir()
                       if (p / "ref.svg").is_file() and (p / "image.png").is_file())
        if not items: raise SystemExit("No SVG items")
        metas = {p.name:json.loads(read(p / "meta.json")) if (p / "meta.json").exists() else {} for p in items}
        if not args.allow_candidates and any(m.get("gold_approved") is not True for m in metas.values()):
            raise SystemExit("Gold unapproved: --allow-candidates allows diagnostics only")
        if args.v3:
            missing=[p.name for p in items if not (p / "table_regions.json").is_file()]
            if missing:raise SystemExit("Missing table_regions.json: " + ", ".join(missing))
        out = Path(args.out)
        if out.exists() and any(out.iterdir()):
            raise SystemExit("Use an empty output directory to avoid mixing runs")
        out.mkdir(parents=True, exist_ok=True)
        rows = []
        for p in items:
            reference = read(p / "ref.svg")
            for repeat in range(args.repeat):
                directory = out / "items" / p.name / f"r{repeat}"
                log = make(p / "image.png", directory, args.endpoint, args.model,
                           args.max_tokens, args.api_key)
                row = {"id":p.name, "repeat":repeat, "tier":metas[p.name].get("tier"),
                       "generation":log,
                       **svg_eval_v2.evaluate(reference, read(directory / "out.svg"),
                           source_image=p / "image.png", output_dir=directory / "visual_assets",
                           font_files=args.font_file, visual=args.visual)}
                if args.v3:
                    row["similarity_v3"] = svg_eval_v3.evaluate(
                        p / "image.png", directory / "out.svg", p / "table_regions.json",
                        output_dir=directory / "v3_visual_assets",
                        font_files=args.font_file, require_grits=args.v3_require_grits)
                row["valid"] = bool(row["valid"] and log["valid"])
                rows.append(row)
                dump(directory / "score.json", row)
        result = {"version":svg_eval_v2.VERSION, "model":args.model, "n_images":len(items),
                  "repeat":args.repeat, "prompt":"svg_v1", "protocol":"P1",
                  "results":rows, "summary":_summary(rows), "final_pass":None}
        dump(out / "summary.json", result)
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
