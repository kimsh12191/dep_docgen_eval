"""Closed-loop SVG refinement: render -> compare -> feedback -> repair -> select.

The visual proxy used without a reviewed ROI manifest is NOT the official V3 score.
P1 is always preserved; failed/worse P2 proposals are retained for inspection.
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

from . import llm, svg, svg_eval_v3 as v3

REFINER_PROMPT = """You refine SVG form reconstructions, not arbitrary images.
You receive the original document image, the rendered current SVG, the current SVG source,
and deterministic discrepancy measurements and optionally paired crops.
Correct the most important missing/misaligned printed text, table boundaries, split/merged
cells, and input fields. Do not add private filled-in values, stamps, handwriting or
content absent from the original. Preserve already-correct areas. Return ONE complete
standalone valid SVG, not an explanation or a patch. Keep SVG dimensions and viewBox
aspect ratio unchanged. Preserve root-level data-field annotations for fillable regions.
"""


def _save_json(path, data):
    target=Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_name(target.name+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(target)


def _extract_svg(response, target, *, metadata):
    target=Path(target)
    target.mkdir(parents=True,exist_ok=True)
    raw=response.get('text') or ''
    (target/'raw.txt').write_text(raw,encoding='utf-8')
    m=re.search(r'<svg\b.*?</svg\s*>',raw,re.S)
    code=m.group() if m else raw
    (target/'out.svg').write_text(code,encoding='utf-8')
    parse=svg.parse(code)
    result={**{k:v for k,v in response.items() if k!='text'},
            'valid':bool(parse['valid'] and not response.get('error') and response.get('finish_reason')!='length'),
            'issues':parse['issues'],**metadata}
    _save_json(target/'make.json',result)
    return result


def _open_png(raw):
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as picture:
        image=picture.convert('RGBA')
    background=Image.new('RGBA',image.size,'white')
    background.alpha_composite(image)
    return background.convert('RGB')


def _region_metrics(source, predicted, bbox, *, name):
    a,b=source.crop(bbox),predicted.crop(bbox)
    stats=v3._visual_metrics(a,b,2)
    if stats['score'] is None:
        return None
    return {'id':name,'bbox':list(bbox),'score':stats['score'],
            'foreground':stats['ink']['f1'],'edge':stats['edge']['f1']}


def _load_regions(source_image, source_size, regions_path):
    if regions_path is None:
        return {'tables':[],'ignore_regions':[]},None
    config=v3._load_manifest(regions_path,source_size)
    return config,regions_path


def assess(source_path, svg_path, out_dir, *, regions_path=None, font_files=None,
           grid=(3,3), crop_pairs=0):
    """Analyze candidate and produce visual evidence without touching the source SVG.

    If annotations are absent, only a non-benchmark page score is returned.
    When annotated tables exist, V3 is computed as an independent read-only evaluation.
    """
    from PIL import Image, ImageChops, ImageEnhance
    out_dir=Path(out_dir)
    out_dir.mkdir(parents=True,exist_ok=True)
    code=Path(svg_path).read_text(encoding='utf-8-sig')
    validation=svg.parse(code)
    if not validation['valid']:
        return {'status':'invalid_svg','score':None,'issues':validation['issues']}
    with Image.open(source_path) as image:
        original=image.convert('RGB')
    config,_=_load_regions(source_path,original.size,regions_path)
    if abs((validation['width']/validation['height'])/(original.width/original.height)-1)>0.02:
        return {'status':'aspect_mismatch','score':None}
    raw,renderer=v3._render(code,original.size,font_files or [])
    predicted=_open_png(raw)
    original,predicted=v3._masked_pair(original,predicted,config['ignore_regions'])
    original.save(out_dir/'original_masked.png')
    predicted.save(out_dir/'rendered.png')
    difference=ImageChops.difference(original,predicted)
    # Red discrepancy map and 50% alpha overlaid document, for human review.
    red=Image.new('RGB',original.size,(255,255,255))
    red.paste((245,55,45),mask=ImageEnhance.Contrast(difference.convert('L')).enhance(4))
    red.save(out_dir/'difference.png')
    Image.blend(original,predicted,0.5).save(out_dir/'overlay.png')
    whole=v3._visual_metrics(original,predicted,2)
    if whole['score'] is None:
        return {'status':'unscorable','score':None}
    regions=[]
    for table in config.get('tables',[]):
        bbox=v3._bbox(table['bbox'])
        result=_region_metrics(original,predicted,bbox,name='table:'+table['id'])
        if result:regions.append(result)
    nx,ny=grid
    for y in range(ny):
        for x in range(nx):
            box=(original.width*x//nx,original.height*y//ny,
                 original.width*(x+1)//nx,original.height*(y+1)//ny)
            r=_region_metrics(original,predicted,box,name=f'tile:{x}:{y}')
            if r:regions.append(r)
    regions.sort(key=lambda r:(r['score'],r['id']))
    selected=[]
    # Prefer hard table regions when available, otherwise worst spatial tiles.
    ranked=sorted(regions,key=lambda r:(not r['id'].startswith('table:'),r['score'],r['id']))
    for rank,region in enumerate(ranked[:crop_pairs]):
        bb=tuple(region['bbox'])
        prefix=f'crop_{rank+1:02d}'
        a,b=out_dir/(prefix+'_original.png'),out_dir/(prefix+'_rendered.png')
        original.crop(bb).save(a);predicted.crop(bb).save(b)
        selected.append({'id':region['id'],'bbox':region['bbox'],
                         'original':str(a),'rendered':str(b),'score':region['score']})
    v3_score=None
    if regions_path is not None:
        v3_result=v3.evaluate(source_path,svg_path,regions_path,
                               font_files=font_files)
        _save_json(out_dir/'score_v3.json',v3_result)
        if v3_result.get('status')!='diagnostic_uncalibrated':
            return {'status':'v3_unscorable','score':None,'score_v3':v3_result,
                    'regions':regions,'renderer':renderer}
        v3_score=v3_result['score_0_100']
    # Never advertise an unannotated visual-only score as a V3 document score.
    objective=(v3_score if v3_score is not None else round(whole['score']*100,2))
    result={'status':'ok','score':objective,
            'score_type':'v3_70_30' if regions_path is not None else 'visual_proxy_unannotated',
            'page_score':round(whole['score']*100,2),
            'renderer':renderer,'regions':regions,'selected_crops':selected,
            'annotated_score_v3':v3_score}
    _save_json(out_dir/'assessment.json',result)
    return result


def propose(image, previous_svg, assessment, out, *, endpoint, model, api_key,
            max_tokens, timeout, crop_pairs=0, include_difference=False):
    """One P2 request using the previous SVG and deterministic visual evidence."""
    out=Path(out)
    prior=Path(previous_svg).read_text(encoding='utf-8-sig')
    summary=assessment.get('regions',[])[:5]
    body=("Current SVG source follows. Return the COMPLETE revised SVG.\n"
          "The provided score is only a diagnostic; infer specific causes from images.\n"
          "Scores and discrepancy regions:\n"+json.dumps({
              'objective':assessment.get('score'),
              'objective_type':assessment.get('score_type'),
              'worst_regions':summary},ensure_ascii=False)+"\n\n"
          "Current SVG:\n"+prior)
    content=[{'type':'text','text':body},
             llm.image_part(image),llm.image_part(Path(previous_svg).parent/'visual'/'rendered.png')]
    if include_difference:
        content.append(llm.image_part(Path(previous_svg).parent/'visual'/'difference.png'))
    for crop in assessment.get('selected_crops',[])[:crop_pairs]:
        content.extend([llm.image_part(crop['original']),llm.image_part(crop['rendered'])])
    response=llm.chat(endpoint,model,
                      [{'role':'system','content':REFINER_PROMPT},
                       {'role':'user','content':content}],
                      max_tokens=max_tokens,temperature=0,timeout=timeout,api_key=api_key)
    return _extract_svg(response,out,metadata={'protocol':'P2','prompt':'svg_refine_v1',
                       'max_tokens':max_tokens,'temperature':0.0,
                       'feedback_score':assessment.get('score'),
                       'feedback_score_type':assessment.get('score_type')})


def repair_invalid(image, previous_svg, issues, out, *, endpoint, model, api_key,
                   max_tokens, timeout):
    """Validation-only P2 fallback when P1 has XML/contract defects and cannot render."""
    prior=Path(previous_svg).read_text(encoding='utf-8-sig')
    request=("The previously generated SVG failed validation and cannot be rendered. "
             "Correct the validation issues and return a COMPLETE standalone SVG. "
             "Do not introduce new information.\nIssues: "
             +json.dumps(issues,ensure_ascii=False)+"\nCurrent invalid SVG:\n"+prior)
    response=llm.chat(endpoint,model,
                      [{'role':'system','content':REFINER_PROMPT},
                       {'role':'user','content':[llm.image_part(image),
                           {'type':'text','text':request}]}],
                      max_tokens=max_tokens,temperature=0,timeout=timeout,api_key=api_key)
    return _extract_svg(response,out,metadata={'protocol':'P2-validation',
                        'prompt':'svg_repair_invalid_v1','max_tokens':max_tokens,
                        'temperature':0.0,'validation_issues':issues})
