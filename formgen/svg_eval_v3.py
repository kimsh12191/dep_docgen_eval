"""V3 document visual fidelity scorer.

Primary goal: compare the original document image to the generated SVG raster.
The fixed provisional profile is 70% whole-page and 30% table ROIs.
GriTS Top/Loc is available only with explicit cell annotations.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
from xml.etree import ElementTree as ET

VERSION = 'document-similarity-v3'


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_manifest(manifest, image_size):
    if isinstance(manifest, (str, Path)):
        manifest = json.loads(Path(manifest).read_text(encoding='utf-8'))
    if not isinstance(manifest, dict):
        raise ValueError('manifest must be an object')
    w, h = image_size
    if manifest.get('image_size') != [w, h]:
        raise ValueError('manifest.image_size must equal original input pixels [width,height]')
    tables = manifest.get('tables')
    if not isinstance(tables, list) or (not tables and manifest.get('no_tables') is not True):
        raise ValueError('provide table ROIs or set no_tables=true explicitly')
    ids = [t.get('id') for t in tables]
    if any(not isinstance(i, str) or not i.strip() for i in ids) or len(ids) != len(set(ids)):
        raise ValueError('table ids must be unique nonempty strings')
    def check_rect(rect):
        if not isinstance(rect, list) or len(rect) != 4:
            raise ValueError('bbox must be [x,y,width,height]')
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in rect):
            raise ValueError('bbox coordinates must be finite numbers')
        x, y, rw, rh = rect
        if x < 0 or y < 0 or min(rw, rh) <= 0 or x + rw > w or y + rh > h:
            raise ValueError('bbox outside source image')
    for item in tables:check_rect(item.get('bbox'))
    for item in manifest.get('ignore_regions', []):check_rect(item)
    return manifest


def _bbox(rect):
    x, y, w, h = rect
    return (int(round(x)), int(round(y)), int(round(x+w)), int(round(y+h)))


def _render(value, size, fonts):
    w, h = size
    try:
        import resvg_py
    except ImportError:
        try:
            import cairosvg
        except ImportError as error:
            raise RuntimeError('install resvg-py or cairosvg to render SVG') from error
        png = cairosvg.svg2png(bytestring=value.encode('utf-8'), output_width=w, output_height=h)
        return png, {'backend': 'cairosvg', 'version': getattr(cairosvg, '__version__', 'unknown'),
                     'font_mode': 'system_unpinned'}
    from . import svg
    parsed = svg.parse(value)
    if not parsed['width'] or not parsed['height']:
        raise ValueError('SVG requires valid viewBox for renderer')
    for font in fonts:
        if not Path(font).is_file():raise FileNotFoundError(font)
    png = resvg_py.svg_to_bytes(svg_string=value, width=w, height=h, background='white',
                                 font_files=[str(Path(p).resolve()) for p in fonts] or None,
                                 skip_system_fonts=bool(fonts))
    return png, {'backend': 'resvg_py', 'version': resvg_py.__version__,
                 'font_mode': 'explicit' if fonts else 'system_unpinned'}


def _masked_pair(source, generated, masks):
    from PIL import ImageDraw
    a, b = source.convert('RGB').copy(), generated.convert('RGB').copy()
    for rect in masks:
        for image in (a, b):
            ImageDraw.Draw(image).rectangle(_bbox(rect), fill='white')
    return a, b


def _mask(image):
    from PIL import ImageOps
    return ImageOps.grayscale(image).point(lambda p: 255 if p < 230 else 0, 'L')


def _edge(mask):
    from PIL import ImageChops, ImageFilter
    return ImageChops.difference(mask, mask.filter(ImageFilter.MinFilter(3)))


def _f1(gold, pred, tolerance=2):
    from PIL import ImageChops, ImageFilter
    if not isinstance(tolerance, int) or not 0 <= tolerance <= 8:
        raise ValueError('tolerance must be an integer in 0..8')
    dilate = lambda image: image.filter(ImageFilter.MaxFilter(2*tolerance+1)) if tolerance else image
    n_gold = gold.histogram()[255]
    n_pred = pred.histogram()[255]
    if not n_gold and not n_pred:
        return {'status': 'no_reference_content', 'f1': None, 'p': None, 'r': None,
                'reference_pixels': 0, 'prediction_pixels': 0}
    a = ImageChops.multiply(gold, dilate(pred)).histogram()[255]
    b = ImageChops.multiply(pred, dilate(gold)).histogram()[255]
    recall = a / n_gold if n_gold else 1.0
    precision = b / n_pred if n_pred else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {'status':'ok', 'f1':round(f1,6), 'p':round(precision,6), 'r':round(recall,6),
            'reference_pixels':n_gold,'prediction_pixels':n_pred}


def _visual_metrics(source, generated, tolerance):
    g, p = _mask(source), _mask(generated)
    ink = _f1(g, p, tolerance)
    edge = _f1(_edge(g), _edge(p), tolerance)
    score = None if ink['f1'] is None or edge['f1'] is None else round((ink['f1']+edge['f1'])/2,6)
    return {'ink':ink,'edge':edge,'score':score}


def _as_cells(cells, *, table, svg_dimensions=None, source_dimensions=None):
    """Convert explicit cell annotations to official GriTS TableCell objects.

    Input bboxes are xywh in source-image units; SVG cell geometry is scaled first.
    """
    from grits import TableCell
    result = []
    for c in cells:
        row, col = int(c['row']), int(c['col'])
        rowspan, colspan = int(c.get('rowspan',1)), int(c.get('colspan',1))
        if min(rowspan,colspan)<=0 or min(row,col)<0:raise ValueError('invalid row/col span')
        x,y,w,h = c['bbox']
        if svg_dimensions is not None:
            sw,sh=svg_dimensions; iw,ih=source_dimensions
            x,y,w,h = x*iw/sw,y*ih/sh,w*iw/sw,h*ih/sh
        result.append(TableCell(row_nums=list(range(row,row+rowspan)),
                                column_nums=list(range(col,col+colspan)),
                                cell_text=str(c.get('text','')),
                                bbox=[x,y,x+w,y+h]))
    return result


def _svg_cells(value, table_id):
    from . import svg
    parsed=svg.parse(value)
    if not parsed['width'] or not parsed['height']:
        return [],None
    root=ET.fromstring(value)
    rows=[]
    for e in root.iter():
        if e.get('data-table') != table_id or e.get('data-cell') is None:
            continue
        if svg.tag(e) != 'rect' or e.get('transform') is not None:
            raise ValueError('data-cell must be on untransformed rect')
        row={'row': int(e.get('data-row')), 'col': int(e.get('data-col')),
             'rowspan':int(e.get('data-rowspan','1')),'colspan':int(e.get('data-colspan','1')),
             'text':e.get('data-text',''),
             'bbox':[float(e.get(k)) for k in ('x','y','width','height')]}
        rows.append(row)
    return rows,(parsed['width'],parsed['height'])


def _grits(table, svg_source, dimensions):
    cells=table.get('reference_cells')
    if cells is None:
        return {'status':'missing_reference_cells'}
    predicted, size=_svg_cells(svg_source,table['id'])
    if not predicted:
        return {'status':'missing_prediction_cells'}
    try:
        from grits import (cell_list_to_grid_top,cell_list_to_grid_loc,grits_top,grits_loc)
    except ImportError:
        return {'status':'missing_dependency','package':'grits-metric'}
    try:
        gold=_as_cells(cells,table=table)
        pred=_as_cells(predicted,table=table,svg_dimensions=size,source_dimensions=dimensions)
        a_top,b_top=cell_list_to_grid_top(gold),cell_list_to_grid_top(pred)
        a_loc,b_loc=cell_list_to_grid_loc(gold),cell_list_to_grid_loc(pred)
        top=float(grits_top(a_top,b_top)[0]); loc=float(grits_loc(a_loc,b_loc)[0])
        return {'status':'ok','grits_top':round(top,6),'grits_loc':round(loc,6),
                'n_reference_cells':len(gold),'n_prediction_cells':len(pred)}
    except (TypeError,ValueError,KeyError,IndexError) as error:
        return {'status':'invalid_cell_annotations','reason':str(error)[:240]}


def evaluate(source_image, predicted_svg, manifest, *, output_dir=None,
             font_files=None, tolerance=2, require_grits=False):
    """Score original image vs generated SVG at original pixel resolution.

    The manifest must declare source-image pixel dimensions and every table ROI.
    GriTS is only computed with explicit reference and predicted cell metadata.
    """
    from PIL import Image
    from . import svg
    original=Path(source_image)
    content=(predicted_svg if isinstance(predicted_svg,str) and predicted_svg.lstrip().startswith('<')
             else Path(predicted_svg).read_text(encoding='utf-8-sig'))
    if not isinstance(content,str):raise TypeError('predicted_svg must be SVG text or path')
    with Image.open(original) as raw:
        source=raw.convert('RGB')
    data=_load_manifest(manifest,source.size)
    valid=svg.parse(content)
    if not valid['valid']:
        return {'version':VERSION,'status':'invalid_svg_contract','score_0_100':0.0,
                'final_pass':None,'svg_contract_issues':valid['issues'],
                'reason':'Refuse rendering untrusted SVG that violates the restricted contract'}
    if valid['width'] and valid['height']:
        input_ratio=source.width/source.height
        svg_ratio=valid['width']/valid['height']
        if abs(svg_ratio/input_ratio-1)>0.02:
            return {'version':VERSION,'status':'aspect_mismatch','score_0_100':None,
                    'final_pass':None,'input_size':list(source.size),
                    'svg_viewbox_size':[valid['width'],valid['height']],
                    'reason':'SVG viewBox differs from original input aspect ratio by more than 2%'}
    result={'version':VERSION,'scoring_profile':'visual70_table30_roi' + ('_grits_required' if require_grits else ''),
            'svg_contract_valid':valid['valid'],'svg_contract_issues':valid['issues'],
            'visual':None,'tables':[],'score_0_100':None,'final_pass':None,
            'status':'not_scored','unvalidated_weights':{'visual':0.7,'tables':0.3},
            'input_sha256':_hash(original),'manifest_sha256':hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
            'renderer':None,'notes':['This score is not calibrated against independent human judgments.',
                     'No automatic image registration, table detection or handwritten-value removal.']}
    try:
        rendered,renderer=_render(content,source.size,font_files or [])
        from PIL import Image as PILImage
        with PILImage.open(io.BytesIO(rendered)) as im:
            rgba=im.convert('RGBA')
            background=PILImage.new('RGBA',rgba.size,'white')
            background.alpha_composite(rgba)
            prediction=background.convert('RGB')
        result['renderer']=renderer
    except (ValueError,OSError,RuntimeError,ET.ParseError) as error:
        result['status']='render_failed';result['error']=str(error)[:300]
        return result
    if output_dir:
        out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
        (out/'predicted.png').write_bytes(rendered)
    source, prediction=_masked_pair(source,prediction,data.get('ignore_regions',[]))
    if output_dir:
        source.save(Path(output_dir)/'source_masked.png')
        prediction.save(Path(output_dir)/'prediction_masked.png')
    page=_visual_metrics(source,prediction,tolerance)
    result['visual']={**page,'weights':{'foreground_f1':0.5,'edge_f1':0.5}}
    for table in data['tables']:
        bb=_bbox(table['bbox'])
        a,b=source.crop(bb),prediction.crop(bb)
        roi=_visual_metrics(a,b,tolerance)
        rscore=None if roi['score'] is None else round(0.3*roi['ink']['f1']+0.7*roi['edge']['f1'],6)
        grid=_grits(table,content,source.size)
        result['tables'].append({'id':table['id'],'bbox':table['bbox'], 'roi':roi,
                                 'roi_score':rscore,'grits':grid})
    if page['score'] is None:
        result['status']='unscorable_page';return result
    if any(t['roi_score'] is None for t in result['tables']):
        result['status']='unscorable_table_roi';return result
    table_score=sum(t['roi_score'] for t in result['tables'])/len(result['tables']) if result['tables'] else None
    if require_grits and any(t['grits']['status']!='ok' for t in result['tables']):
        result['status']='grits_required_but_unavailable';return result
    if table_score is None:
        result['score_0_100']=round(page['score']*100,2)
        result['aggregation']={'mode':'visual_only_explicit_no_tables','visual':page['score'],'tables':None}
    else:
        result['score_0_100']=round(100*(0.7*page['score']+0.3*table_score),2)
        result['aggregation']={'mode':'visual70_table30_roi','visual':page['score'],
                                'table_roi_mean':round(table_score,6), 'n_tables':len(result['tables'])}
    result['status']='diagnostic_uncalibrated'
    return result
