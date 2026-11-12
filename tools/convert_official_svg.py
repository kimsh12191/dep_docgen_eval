"""One-time conversion of this repository's absolute-positioned official HTML candidates.

NOT a general HTML-to-SVG converter. Requires bs4, resvg_py; no browser.
Preserves source PDFs, PNGs, HTML and gold_approved:false.
"""
from pathlib import Path
import json
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from formgen import svg


def styles(e):
    return dict(p.strip().split(':',1) for p in e.get('style','').split(';') if ':' in p)


def number(s):return float(s.strip().removesuffix('px'))


def convert(folder):
    soup=BeautifulSoup((folder/'ref.html').read_text(encoding='utf-8'),'html.parser')
    page=soup.select_one('.page');ps=styles(page);w,h=number(ps['width']),number(ps['height'])
    root=ET.Element('{'+svg.NS+'}svg',{'width':str(w),'height':str(h),'viewBox':f'0 0 {w} {h}'})
    q=lambda n:'{'+svg.NS+'}'+n
    # Existing line/path layer uses PDF points, rather than CSS pixels.
    for layer in soup.select('svg.printed-lines'):
        original=ET.fromstring(str(layer))
        vb=original.get('viewBox',original.get('viewbox','')).split();sw,sh=float(vb[2]),float(vb[3])
        group=ET.SubElement(root,q('g'),{'transform':f'scale({w/sw} {h/sh})'})
        for e in original:
            for node in e.iter():
                node.tag=q(svg.tag(node))
                for k,v in list(node.attrib.items()):
                    if v=='None':del node.attrib[k]
            group.append(e)
    for el in soup.select('.printed'):
        s=styles(el);size=number(s['font-size']);x,y=number(s['left']),number(s['top'])
        attrs={'x':str(x),'y':str(y+size*.82),'font-size':str(size),'font-family':'Malgun Gothic',
               'font-weight':s.get('font-weight','400').strip(),'fill':s.get('color','black').strip(),
               '{http://www.w3.org/XML/1998/namespace}space':'preserve'}
        if el.get('data-width'):
            attrs['textLength']=el['data-width'];attrs['lengthAdjust']='spacingAndGlyphs'
        ET.SubElement(root,q('text'),attrs).text=el.get_text()
    fields=json.loads((folder/'fields.json').read_text(encoding='utf-8'))['rendered_fields']
    for f in fields:
        x,y,bw,bh=f['bbox']
        attrs={'data-field':f['key'],'data-label':f['label'],'data-type':f['type'],
               'x':str(x),'y':str(y),'width':str(bw),'height':str(bh),'fill':'none','stroke':'none'}
        ET.SubElement(root,q('rect'),attrs)
    value=ET.tostring(root,encoding='unicode')
    validation=svg.parse(value)
    if not validation['valid']:raise ValueError((folder.name,validation['issues']))
    (folder/'ref.svg').write_text(value,encoding='utf-8')
    rendered=svg.render(value,folder/'ref_svg.png')
    meta=json.loads((folder/'meta.json').read_text(encoding='utf-8'))
    meta.update(preferred_format='svg',svg_contract=svg.VERSION)
    meta['svg_migration']={'date':'2026-11-12','method':'absolute_html_text_to_svg_plus_existing_paths',
        'render':rendered,'review_status':'candidate','limitations':['Text baselines approximated at 0.82 em; review against PDF',
        'Existing PDF glyph outlines retained in imported line layer; model output should retain editable text',
        'Inherited field omissions remain; not approved gold']}
    (folder/'meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    return meta


if __name__=='__main__':
    root=Path('bench/official_pilot_v1')
    metas=[convert(p) for p in sorted(root.iterdir()) if p.is_dir() and (p/'ref.html').exists()]
    (root/'manifest.json').write_text(json.dumps(metas,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Converted',len(metas),'candidates; none promoted to gold')
