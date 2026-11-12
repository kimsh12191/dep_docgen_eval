"""V2 diagnostic evaluation: exact field types, browser checks and optional source ink comparison.

python -m formgen html evaluate --ref ref.html --pred out.html --out runs/check --browser /path/to/chrome
No final gold pass until annotation review and visual thresholds are calibrated.
"""
import argparse
import json
from pathlib import Path
from .score import score_html, passed
from ..match import hungarian, label_sim


def semantic_fields(gold, pred, width, height):
    def similarity(a,b):
        lab=label_sim(a['label'],b['label'])
        x,y,w,h=a['bbox']; u,v,s,t=b['bbox']
        distance=abs((x+w/2)-(u+s/2))/width+abs((y+h/2)-(v+t/2))/height
        return lab, distance
    costs=[]
    for a in gold:
        row=[]
        for b in pred:
            lab,dist=similarity(a,b)
            row.append(1-lab+dist if lab>=0.8 else 1000)
        costs.append(row)
    pairs=[(i,j) for i,j in hungarian(costs) if costs[i][j]<1000] if gold and pred else []
    typed=[(i,j) for i,j in pairs if gold[i]['type']==pred[j]['type'] and
           (gold[i]['type']!='checkbox' or set(gold[i]['options'])==set(pred[j]['options']))]
    located=[(i,j) for i,j in typed if similarity(gold[i],pred[j])[1]<=0.04 and pred[j]['visible']]
    f1=lambda n:round(2*n/(len(gold)+len(pred)),4) if gold or pred else 1
    hit={i for i,j in typed}
    return {'typed_field_f1':f1(len(typed)), 'located_typed_field_f1':f1(len(located)),
            'typed_field_recall':round(len(typed)/len(gold),4) if gold else None,
            'missing_or_wrong_type':[a['label'] for i,a in enumerate(gold) if i not in hit],
            'position_tolerance_normalized_l1':0.04}


def evaluate(ref, pred, out, browser=None, source_image=None, width=794, height=1123):
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    g=Path(ref).read_text(encoding='utf-8-sig'); p=Path(pred).read_text(encoding='utf-8-sig')
    legacy=score_html(g,p)
    if browser is None:
        from .htmldoc import parse
        def fields(html):
            return [{**f,'bbox':[0,0,0,0],'visible':False} for f in parse(html)['fields']]
        scores=semantic_fields(fields(g),fields(p),width,height)
        scores.pop('position_tolerance_normalized_l1')
        scores['located_typed_field_f1']=None
        result={'version':'diagnostic-v2.1','mode':'offline_standard_library',
                'legacy':{**legacy,'pass':passed(legacy)},'fields':scores,
                'reference_render':None,'prediction_render':None,'fill_stress':None,
                'visual':None,'final_pass':None,
                'status':'partial_evaluation_render_not_measured',
                'limitations':['No browser: visibility, geometry, clipping and visual similarity are NOT measured',
                               'Field matching uses labels only; repeated labels can be ambiguous',
                               'Current parser evaluates HTML semantics, not standalone SVG geometry']}
        (out/'evaluation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return result
    from .rendercheck import inspect, ink_similarity
    gr=inspect(g,out/'reference.png',browser,width,height)
    pr=inspect(p,out/'prediction.png',browser,width,height)
    stress=inspect(p,out/'filled_stress.png',browser,width,height,True)
    result={'version':'diagnostic-v2.0', 'legacy':{**legacy,'pass':passed(legacy)},
            'fields':semantic_fields(gr['fields'],pr['fields'],width,height),
            'reference_render':gr, 'prediction_render':pr,'fill_stress':stress,
            'final_pass':None,'status':'diagnostic_only_pending_gold_review_and_calibration',
            'limitations':['Single-page CSS-pixel viewport, not print pagination',
                           'Render checks detect common failures, not all overlaps or clipping',
                           'Generic long-value stress is diagnostic, not a valid value for every field']}
    if source_image:
        result['visual']=ink_similarity(source_image,out/'prediction.png',[f['bbox'] for f in gr['fields']])
        result['reference_visual']=ink_similarity(source_image,out/'reference.png',[f['bbox'] for f in gr['fields']])
    (out/'evaluation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    for name in ['ref','pred','out']:ap.add_argument('--'+name,required=True)
    ap.add_argument('--browser', help='Optional Chromium executable; omitted = standard-library-only evaluation')
    ap.add_argument('--source-image');ap.add_argument('--width',type=int,default=794);ap.add_argument('--height',type=int,default=1123)
    args=ap.parse_args()
    if args.source_image and not args.browser:
        ap.error('--source-image requires --browser; offline mode does not measure image similarity')
    r=evaluate(args.ref,args.pred,args.out,args.browser,args.source_image,args.width,args.height)
    print(json.dumps({'version':r['version'],'fields':r['fields'],'final_pass':r['final_pass']},ensure_ascii=True))
