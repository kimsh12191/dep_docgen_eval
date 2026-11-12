"""SVG commands; no imports of browser or authoring libraries."""
import argparse
import json
import hashlib
from statistics import fmean
import re
from pathlib import Path
from . import svg,svg_eval_v2,llm


def dump(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def make(image,out,endpoint,model,max_tokens=16000,api_key=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    prompt=(Path(__file__).parent/'prompts/svg_v1.md').read_text(encoding='utf-8')
    response=llm.chat(endpoint,model,[{'role':'system','content':prompt},{'role':'user','content':[llm.image_part(image),{'type':'text','text':'이 문서를 빈 SVG 서식으로 만드세요. SVG만 출력하세요.'}]}],max_tokens=max_tokens,api_key=api_key)
    raw=response.pop('text','');(out/'raw.txt').write_text(raw,encoding='utf-8')
    match=re.search(r'<svg\b.*?</svg\s*>',raw,re.S)
    value=match.group() if match else raw
    (out/'out.svg').write_text(value,encoding='utf-8')
    validation=svg.parse(value)
    log={**response,'valid':validation['valid'] and not response.get('error') and response.get('finish_reason')!='length',
         'issues':validation['issues'],'model':model,'prompt':'svg_v1','protocol':'P1',
         'max_tokens':max_tokens,'temperature':0.0}
    dump(out/'make.json',log)
    return log



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
    tiers = sorted({r["tier"] for r in rows if r.get("tier")})
    return {"all": group(rows), "by_tier": {tier:group([r for r in rows if r.get("tier") == tier]) for tier in tiers},
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
    r = sub.add_parser("render")
    r.add_argument("input"); r.add_argument("--out", required=True); r.add_argument("--font-file", action="append")
    v = sub.add_parser("validate"); v.add_argument("input")
    b = sub.add_parser("bench")
    for key in ("items", "out", "endpoint", "model"): b.add_argument("--" + key, required=True)
    b.add_argument("--allow-candidates", action="store_true")
    b.add_argument("--max-tokens", type=int, default=16000); b.add_argument("--api-key")
    b.add_argument("--repeat", type=int, default=1)
    b.add_argument("--visual", action="store_true"); b.add_argument("--font-file", action="append")
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
