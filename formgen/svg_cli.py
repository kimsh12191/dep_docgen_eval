"""SVG commands; no imports of browser or authoring libraries."""
import argparse
import json
import re
from pathlib import Path
from . import svg,llm


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


def main(argv=None):
    ap=argparse.ArgumentParser(prog='python -m formgen svg')
    sub=ap.add_subparsers(dest='action',required=True)
    m=sub.add_parser('make')
    for k in ['image','out','endpoint','model']:m.add_argument('--'+k,required=True)
    m.add_argument('--max-tokens',type=int,default=16000);m.add_argument('--api-key')
    s=sub.add_parser('score');s.add_argument('ref');s.add_argument('pred');s.add_argument('--out')
    r=sub.add_parser('render');r.add_argument('input');r.add_argument('--out',required=True);r.add_argument('--font-file',action='append')
    v=sub.add_parser('validate');v.add_argument('input')
    b=sub.add_parser('bench')
    for k in ['items','out','endpoint','model']:b.add_argument('--'+k,required=True)
    b.add_argument('--allow-candidates',action='store_true');b.add_argument('--max-tokens',type=int,default=16000);b.add_argument('--api-key')
    args=ap.parse_args(argv)
    read=lambda p:Path(p).read_text(encoding='utf-8-sig')
    if args.action=='make':result=make(args.image,args.out,args.endpoint,args.model,args.max_tokens,args.api_key)
    elif args.action=='validate':result=svg.parse(read(args.input))
    elif args.action=='score':
        result=svg.score(read(args.ref),read(args.pred))
        if args.out:dump(args.out,result)
    elif args.action=='render':
        result=svg.render(read(args.input),args.out,args.font_file);dump(str(args.out)+'.json',result)
    else:
        items=sorted(p for p in Path(args.items).iterdir() if (p/'ref.svg').exists() and (p/'image.png').exists())
        if not items:raise SystemExit('No SVG items')
        metas={p.name:json.loads(read(p/'meta.json')) if (p/'meta.json').exists() else {} for p in items}
        if not args.allow_candidates and any(metas[p.name].get('gold_approved') is not True for p in items):raise SystemExit('Gold is not approved; use --allow-candidates for diagnostics only')
        out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
        if (out/'summary.json').exists():raise SystemExit('Use a fresh output directory to avoid mixing runs')
        rows=[]
        for p in items:
            d=out/p.name;log=make(p/'image.png',d,args.endpoint,args.model,args.max_tokens,args.api_key)
            row={'id':p.name,'tier':metas[p.name].get('tier'),'generation':log,**svg.score(read(p/'ref.svg'),read(d/'out.svg'))}
            row['valid']=row['valid'] and log['valid'];rows.append(row);dump(d/'score.json',row)
        result={'version':svg.VERSION,'model':args.model,'prompt':'svg_v1','protocol':'P1','n':len(rows),'results':rows,'final_pass':None}
        dump(out/'summary.json',result)
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
