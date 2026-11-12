"""Opt-in browser checks. Results are diagnostics, not calibrated visual similarity.

Runs with JS disabled and all network requests blocked; never executes document scripts.
Requires playwright, Pillow, and a local Chromium executable.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image, ImageChops, ImageFilter


INSPECT = r'''() => {
 const rect=e=>{const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height]};
 const visible=(e,requireSize=true)=>{
   for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);
     if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}
   const r=e.getBoundingClientRect();return !requireSize||(r.width>0&&r.height>0);
 };
 const fields=[...document.querySelectorAll('[data-field]')].map(e=>{
   const r=e.getBoundingClientRect(); const anchor=r.width>0&&r.height>0?e:e.parentElement;
   return {
   key:e.dataset.field,label:e.dataset.label||'',type:e.dataset.type||'',
   options:(e.dataset.options||'').split('|').filter(Boolean),
   bbox:rect(anchor),geometry:anchor===e?'element':'parent_fallback',
   visible:visible(e,false)&&visible(anchor),overflow:e.scrollWidth>e.clientWidth+2&&e.clientWidth>0
 }});
 const textRects=[]; const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
 while(w.nextNode()){const n=w.currentNode;if(!n.textContent.trim()||!visible(n.parentElement)||n.parentElement.closest('style,script'))continue;
   const r=document.createRange();r.selectNodeContents(n);
   for(const b of r.getClientRects())textRects.push([b.x,b.y,b.width,b.height]);}
 return {fields,textRects,body:rect(document.body)};
}'''


def inspect(html, out, executable, width=794, height=1123, fill=False):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={'width':width,'height':height}, java_script_enabled=False)
        page.route('**/*', lambda route: route.abort())
        page.set_content(html, wait_until='load')
        if fill:
            page.locator('[data-field]').evaluate_all('''els=>els.forEach(e=>{
                const t=e.dataset.type;
                e.textContent=t==='checkbox'?'☑':t==='amount'?'123,456,789':t==='date'?'2026-11-12':
                t==='number'?'1234567890':t==='seal'?'인':t==='signature'?'서명':
                '홍길동 서울특별시 종로구 테스트로 123';
            })''')
        state=page.evaluate(INSPECT)
        page.screenshot(path=str(out))
        browser.close()
    boxes=state['textRects']+[f['bbox'] for f in state['fields'] if f['visible']]
    state['outside_page']=sum(x < -2 or y < -2 or x+w > width+2 or y+h > height+2 for x,y,w,h in boxes)
    state['hidden_fields']=sum(not f['visible'] for f in state['fields'])
    state['overflow_fields']=sum(f['overflow'] for f in state['fields'])
    # Flags obvious invisible documents, including display:none and white-on-white text.
    im=Image.open(out).convert('L')
    state['ink_fraction']=sum(v for i,v in enumerate(im.histogram()) if i<220)/(im.width*im.height)
    state['render_ok']=bool(state['fields']) and not state['hidden_fields'] and not state['outside_page'] and state['ink_fraction']>0.00001
    return state


def ink_similarity(reference, prediction, masks=()):
    """Tolerance-aware foreground F1, excluding declared field boxes on BOTH images.

    Resizes source to the prediction canvas. For blank official originals only;
    do not use unmasked filled scans or infer a pass threshold from this score.
    """
    from PIL import ImageDraw
    b=Image.open(prediction).convert('L')
    a=Image.open(reference).convert('L').resize(b.size)
    a=a.point(lambda p:255 if p<180 else 0)
    b=b.point(lambda p:255 if p<180 else 0)
    for im in (a,b):
        draw=ImageDraw.Draw(im)
        for x,y,w,h in masks:
            draw.rectangle((x-2,y-2,x+w+2,y+h+2),fill=0)
    count=lambda im:sum(im.histogram()[1:])
    na,nb=count(a),count(b)
    p=count(ImageChops.multiply(b,a.filter(ImageFilter.MaxFilter(5))))/nb if nb else 0
    r=count(ImageChops.multiply(a,b.filter(ImageFilter.MaxFilter(5))))/na if na else 0
    return {'ink_precision':round(p,4),'ink_recall':round(r,4),
            'ink_f1':round(2*p*r/(p+r),4) if p+r else 0,
            'status':'diagnostic_uncalibrated','tolerance_px':2}
