"""Standalone SVG v1 contract, validation, scoring and browser-free rendering.

Core parser/scorer use only the Python standard library. Rendering lazily imports resvg_py.
"""
import hashlib
import math
import re
from pathlib import Path
import xml.etree.ElementTree as ET

from .match import hungarian, label_sim
from .score import text_score

NS='http://www.w3.org/2000/svg'
ET.register_namespace('',NS)
VERSION='svg-v1'
TYPES={'text','number','amount','date','checkbox','seal','signature'}
ALLOWED={'svg','g','rect','line','polyline','polygon','path','circle','ellipse','text','tspan','title','desc'}
KEY=re.compile(r'^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$')


def tag(e):return e.tag.split('}')[-1]


def parse(value):
    result={'valid':False,'issues':[],'fields':[],'texts':[],'width':0,'height':0}
    issues=result['issues']
    if re.search(r'<!DOCTYPE|<!ENTITY',value,re.I):
        issues.append('doctype_or_entity');return result
    try:root=ET.fromstring(value)
    except ET.ParseError:
        issues.append('invalid_xml');return result
    if root.tag!='{'+NS+'}svg':issues.append('root_namespace')
    if 'transform' in root.attrib:issues.append('root_transform')
    try:
        box=[float(x) for x in root.get('viewBox','').replace(',',' ').split()]
        if len(box)!=4 or not all(math.isfinite(x) for x in box) or box[:2]!=[0,0] or min(box[2:])<=0 or max(box[2:])>5000:raise ValueError()
        result['width'],result['height']=box[2:]
    except ValueError:issues.append('viewbox')
    seen=set()
    def walk(e, in_field=False):
        name=tag(e)
        if name not in ALLOWED:issues.append('unsupported_element:'+name)
        for k,v in e.attrib.items():
            key=k.split('}')[-1]
            if key.lower().startswith('on') or key in {'href','style','class'} or re.search(r'url\s*\(',v,re.I):issues.append('forbidden_attribute:'+key)
        isfield='data-field' in e.attrib
        if isfield:
            key=e.get('data-field','');typ=e.get('data-type','');label=e.get('data-label','')
            if e not in list(root) or name!='rect' or 'transform' in e.attrib:issues.append('field_must_be_root_rect')
            if not KEY.fullmatch(key) or key in seen:issues.append('field_key')
            seen.add(key)
            if typ not in TYPES:issues.append('field_type')
            if not label.strip():issues.append('field_label')
            options=e.get('data-options','').split('|') if e.get('data-options') else []
            if typ=='checkbox' and (not options or len(set(options))!=len(options)):issues.append('field_options')
            try:
                x,y,w,h=[float(e.get(k,'')) for k in ['x','y','width','height']]
                if not all(math.isfinite(v) for v in [x,y,w,h]) or min(w,h)<=0:raise ValueError()
                if x<0 or y<0 or x+w>result['width']+0.01 or y+h>result['height']+0.01:issues.append('field_outside_page')
                result['fields'].append({'key':key,'label':label,'type':typ,'options':options,'bbox':[x,y,w,h]})
            except ValueError:issues.append('field_bbox')
        if name=='text' and not in_field:result['texts'].append(''.join(e.itertext()))
        for child in e:walk(child,in_field or isfield)
    walk(root)
    if not result['fields']:issues.append('no_fields')
    if not result['texts']:issues.append('no_editable_text')
    result['issues']=sorted(set(issues));result['valid']=not issues
    return result


def score(reference, prediction):
    a,b=parse(reference),parse(prediction)
    if not a['valid']:raise ValueError('Invalid reference: '+','.join(a['issues']))
    def box(f,doc):
        x,y,w,h=f['bbox'];return [x/doc['width'],y/doc['height'],w/doc['width'],h/doc['height']]
    def iou(g,p):
        x,y,w,h=box(g,a);u,v,s,t=box(p,b)
        overlap=max(0,min(x+w,u+s)-max(x,u))*max(0,min(y+h,v+t)-max(y,v))
        return overlap/(w*h+s*t-overlap)
    costs=[[1-label_sim(g['label'],p['label'])+1-iou(g,p) if label_sim(g['label'],p['label'])>=0.8 else 1000 for p in b['fields']] for g in a['fields']] if b['width'] and b['height'] else []
    pairs=[(i,j) for i,j in hungarian(costs) if costs[i][j]<1000] if b['width'] and b['height'] and a['fields'] and b['fields'] else []
    typed=[(i,j) for i,j in pairs if a['fields'][i]['type']==b['fields'][j]['type'] and set(a['fields'][i]['options'])==set(b['fields'][j]['options'])]
    located=[(i,j) for i,j in typed if iou(a['fields'][i],b['fields'][j])>=0.5]
    denom=len(a['fields'])+len(b['fields'])
    return {'version':VERSION,'valid':b['valid'],'issues':b['issues'],
            'fields_gt':len(a['fields']),'fields_pred':len(b['fields']),
            'typed_field_f1':round(2*len(typed)/denom,4),
            'located_field_f1':round(2*len(located)/denom,4),
            'field_iou_mean':round(sum(iou(a['fields'][i],b['fields'][j]) for i,j in typed)/len(a['fields']),4),
            **text_score(a,b),'final_pass':None,
            'status':'diagnostic_uncalibrated','geometry_threshold':0.5,
            'limitations':['Declared field rectangles are checked; actual text/line geometry is not fully checked',
                           'No browser layout, table topology or downstream OCR/KIE score',
                           'Field aliases and alternative date splitting are not implemented']}


def render(value, output, font_files=None):
    parsed=parse(value)
    if not parsed['valid']:raise ValueError('Invalid SVG: '+','.join(parsed['issues']))
    import resvg_py
    fonts=[str(Path(p).resolve()) for p in (font_files or [])]
    for p in fonts:
        if not Path(p).is_file():raise ValueError('Font missing: '+p)
    png=resvg_py.svg_to_bytes(svg_string=value,background='white',width=round(parsed['width']),height=round(parsed['height']),font_files=fonts or None,skip_system_fonts=bool(fonts))
    Path(output).parent.mkdir(parents=True,exist_ok=True);Path(output).write_bytes(png)
    return {'renderer':'resvg_py','version':resvg_py.__version__,
            'font_mode':'explicit' if fonts else 'system_unpinned',
            'fonts':[{'file':Path(p).name,'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest()} for p in fonts]}
