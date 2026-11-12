"""Concurrent multi-vLLM image->SVG experiment harness with opt-in visual P2.

Entry: python -m formgen harness generate --config file.json --images dir --out runs/id
All output candidates, validation results, and feedback evidence are retained.
The scoring and feedback loop is NOT a calibrated model-pass criterion.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import statistics
import threading
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlsplit

from .svg_cli import make
from . import svg
from .harness_refine import assess, propose, repair_invalid, _save_json

VERSION = 'svg-generation-harness-v1'
EXTENSIONS = {'.png','.jpg','.jpeg','.webp'}
SAFE_ID = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$')
CSV_COLUMNS = ('model_id','served_model','image_id','image_path','tier','repeat',
               'status','valid','protocol','initial_score','best_score','score_type',
               'rounds_completed','stop_reason','seconds_total','prompt_tokens','completion_tokens',
               'finish_reason','error','best_svg','input_sha256','run_fingerprint')


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_config(path: Path) -> dict:
    cfg=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(cfg,dict) or not isinstance(cfg.get('models'),list) or not cfg['models']:
        raise ValueError('config.models must be a nonempty array')
    seen=set()
    for model in cfg['models']:
        if not isinstance(model,dict):raise ValueError('each model must be an object')
        name=model.get('id')
        if not isinstance(name,str) or not SAFE_ID.fullmatch(name) or name in {'.','..'} or name in seen:
            raise ValueError('model IDs must be unique safe nonempty strings')
        seen.add(name)
        url=model.get('endpoint')
        u=urlsplit(url) if isinstance(url,str) else None
        if not u or u.scheme not in ('http','https') or not u.netloc or u.query or u.fragment or u.username or u.password or not url.rstrip('/').endswith('/v1'):
            raise ValueError(f'{name}: endpoint must be http(s)://host:port/v1')
        if not isinstance(model.get('model'),str) or not model['model']:
            raise ValueError(f'{name}: model must be served model ID')
        concurrent=model.get('concurrency',1)
        if type(concurrent) is not int or not 1<=concurrent<=16:
            raise ValueError('model.concurrency must be an integer 1..16')
        if 'api_key' in model:raise ValueError('store credentials in api_key_env, not config')
        env=model.get('api_key_env')
        if env is not None and (not isinstance(env,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',env)):
            raise ValueError('api_key_env must name an environment variable')
    settings=cfg.setdefault('generation',{})
    if not isinstance(settings,dict):raise ValueError('generation must be an object')
    for key,default,lower,upper in (
        ('max_tokens',16000,1,250000),('repeats',1,1,100),
        ('max_refinements',0,0,5),('feedback_crop_pairs',0,0,2),
        ('timeout',1800,1,7200),('max_svg_chars',150000,1000,2000000)):
        value=settings.get(key,default)
        if type(value) is not int or not lower<=value<=upper:raise ValueError(f'generation.{key} must be integer in {lower}..{upper}')
    if type(settings.get('min_improvement',0.25)) not in (int,float) or not 0<=settings.get('min_improvement',0.25)<=20:
        raise ValueError('generation.min_improvement must be in 0..20 points')
    if type(settings.get('feedback_include_difference',False)) is not bool:
        raise ValueError('generation.feedback_include_difference must be boolean')
    if settings.get('temperature',0)!=0:
        raise ValueError('P1 make() currently fixes temperature=0; nonzero not supported')
    return cfg


def _find_images(directory: Path) -> list[dict]:
    if not Path(directory).is_dir():raise ValueError('--images must be an existing directory')
    result=[]
    for path in sorted(Path(directory).rglob('*')):
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:continue
        rel=path.relative_to(directory).as_posix()
        slug=re.sub(r'[^A-Za-z0-9_-]+','_',Path(rel).with_suffix('').as_posix()).strip('_')[:56] or 'image'
        region_candidates=[path.with_suffix('.regions.json')]
        if path.stem=='image':region_candidates.append(path.parent/'table_regions.json')
        regions=next((p for p in region_candidates if p.is_file()),None)
        meta=path.parent/'meta.json'
        try:metadata=json.loads(meta.read_text(encoding='utf-8-sig')) if meta.is_file() else {}
        except (OSError,ValueError) as exc:raise ValueError(f'invalid meta.json at {meta}: {exc}') from exc
        result.append({'id':slug+'__'+_sha(rel.encode())[:10],
                       'path':str(path.resolve()),'relative_path':rel,
                       'sha256':_sha(path.read_bytes()),'tier':metadata.get('tier'),
                       'regions':str(regions.resolve()) if regions else None,
                       'regions_sha256':_sha(regions.read_bytes()) if regions else None})
    if not result:raise ValueError('No supported images in --images')
    return result


def _model_key(model):
    env=model.get('api_key_env')
    if env and not os.environ.get(env):raise ValueError('missing api_key_env: '+env)
    return os.environ.get(env) if env else None


def _check_model(model):
    token=_model_key(model)
    req=urllib.request.Request(model['endpoint'].rstrip('/')+'/models',
                               headers={'Authorization':'Bearer '+token} if token else {})
    with urllib.request.urlopen(req,timeout=15) as response:data=json.load(response)
    offered=[row.get('id') for row in data.get('data',[]) if isinstance(row,dict)]
    if model['model'] not in offered:
        raise ValueError(f"{model['id']} served model {model['model']!r} not found at /v1/models: {offered}")


def _load_step(folder):
    log=folder/'make.json'
    code=folder/'out.svg'
    if not (log.is_file() and code.is_file()):return None
    try:return json.loads(log.read_text(encoding='utf-8-sig'))
    except (ValueError,OSError):return None


def _task_status(log):
    if log.get('error'):return 'request_error'
    if log.get('finish_reason')=='length':return 'truncated'
    return 'valid_svg' if log.get('valid') else 'invalid_svg'


def _run_task(model,image,repeat,output,fingerprint,settings,semaphore,*,resume,retry_failed):
    folder=output/model['id']/image['id']/f'r{repeat:03d}'
    final=folder/'status.json'
    if final.is_file() and resume:
        try:
            previous=json.loads(final.read_text(encoding='utf-8'))
            same=(previous.get('run_fingerprint')==fingerprint and
                  previous.get('input_sha256')==image['sha256'])
            has_output=(folder/'best.svg').is_file()
            finished=previous.get('status')!='valid_svg' or has_output
            should_retry=retry_failed and previous.get('status')=='request_error'
            if same and finished and not should_retry:
                return previous
        except (ValueError,OSError):pass
    rounds=settings.get('max_refinements',0)
    folder.mkdir(parents=True,exist_ok=True)
    first=folder/'round_0'
    token=_model_key(model)
    candidate_logs=[]
    evidence=[]
    assessments={}
    best_score=None
    best_index=None
    best_type=None
    err=None
    try:
        with semaphore:
            p1=_load_step(first) if resume and not retry_failed else None
            if p1 is None or _task_status(p1)=='request_error':
                p1=make(image=image['path'],out=first,endpoint=model['endpoint'],
                        model=model['model'],max_tokens=settings.get('max_tokens',16000),
                        api_key=token,timeout=settings.get('timeout',1800))
            candidate_logs.append(p1)
            initial_score=None
            assessments={}
            if p1.get('valid'):
                best_index=0
                if rounds:
                    initial=assess(image['path'],first/'out.svg',first/'visual',
                                   regions_path=image['regions'],
                                   crop_pairs=settings.get('feedback_crop_pairs',0))
                    assessments[0]=initial
                    evidence.append(initial)
                    if initial.get('status')=='ok':
                        best_score=initial_score=initial['score']
                        best_type=initial['score_type']
                    else:err='P1 assessment: '+initial.get('status','unknown')
            for n in range(1,rounds+1):
                if best_index is None and (p1.get('error') or n>1):break
                prev_index=best_index if best_index is not None else 0
                prev=folder/f'round_{prev_index}'
                if len((prev/'out.svg').read_text(encoding='utf-8-sig'))>settings.get('max_svg_chars',150000):
                    err='previous SVG source exceeds max_svg_chars';break
                if best_index is not None and best_score is None:break
                target=folder/f'round_{n}'
                step=_load_step(target) if resume else None
                if step is None:
                    if best_index is None:
                        step=repair_invalid(image['path'],first/'out.svg',p1.get('issues',[]),target,
                            endpoint=model['endpoint'],model=model['model'],api_key=token,
                            max_tokens=settings.get('max_tokens',16000),
                            timeout=settings.get('timeout',1800))
                    else:
                        step=propose(image['path'],prev/'out.svg',assessments[prev_index],target,
                            endpoint=model['endpoint'],model=model['model'],api_key=token,
                            max_tokens=settings.get('max_tokens',16000),
                            timeout=settings.get('timeout',1800),
                            crop_pairs=settings.get('feedback_crop_pairs',0),
                            include_difference=settings.get('feedback_include_difference',False))
                candidate_logs.append(step)
                if not step.get('valid'):
                    err='refinement_'+_task_status(step);break
                measured=assess(image['path'],target/'out.svg',target/'visual',
                                regions_path=image['regions'],
                                crop_pairs=settings.get('feedback_crop_pairs',0))
                evidence.append(measured)
                assessments[n]=measured
                if measured.get('status')!='ok':
                    err='refinement_assessment_'+measured.get('status','unknown');break
                if best_index is None:
                    best_index=n;best_score=measured['score'];best_type=measured['score_type']
                    continue
                delta=measured['score']-best_score
                if delta>0 and delta>=settings.get('min_improvement',0.25):
                    best_index=n;best_score=measured['score']
                else:
                    err='stopped_no_improvement' if delta>=0 else 'stopped_regression'
                    break
            if best_index is not None:
                shutil.copyfile(folder/f'round_{best_index}'/'out.svg',folder/'best.svg')
            elif (folder/'best.svg').exists():
                (folder/'best.svg').unlink()
    except Exception as ex:
        err=f'internal_error:{type(ex).__name__}:{str(ex)[:160]}'
        if not candidate_logs:
            candidate_logs=[{'valid':False,'error':err}]
    p1=candidate_logs[0]
    best=candidate_logs[best_index] if best_index is not None else p1
    successful=best_index is not None and (folder/'best.svg').exists()
    status=(_task_status(p1) if not successful else 'valid_svg')
    if err and err.startswith('internal_error'):
        # A crash in the scorer is not model success even if a P1 SVG was produced.
        status='harness_error'
    usage=[(entry.get('usage') or {}) for entry in candidate_logs]
    stop_reason=err if err in ('stopped_no_improvement','stopped_regression') else None
    fault=err if err not in ('stopped_no_improvement','stopped_regression') else None
    row={'model_id':model['id'],'served_model':model['model'],'image_id':image['id'],
         'image_path':image['relative_path'],'tier':image['tier'],'repeat':repeat,
         'status':status,'valid':bool(successful and status=='valid_svg'),'protocol':'P2' if rounds else 'P1',
         'initial_score':initial_score,'best_score':best_score,'score_type':best_type,
         'rounds_completed':max(0,len(candidate_logs)-1),'stop_reason':stop_reason,
         'seconds_total':round(sum(float(c.get('seconds') or 0) for c in candidate_logs),2),
         'prompt_tokens':sum(int(u.get('prompt_tokens') or 0) for u in usage),
         'completion_tokens':sum(int(u.get('completion_tokens') or 0) for u in usage),
         'finish_reason':best.get('finish_reason'),'error':fault or p1.get('error'),
         'best_svg':str(folder/'best.svg') if successful else None,
         'input_sha256':image['sha256'],'run_fingerprint':fingerprint,
         'chosen_round':best_index,
         'candidates':[{'round':i,'status':_task_status(c),'valid':bool(c.get('valid')),
                        'score':(assessments[i].get('score') if i in assessments else None)}
                       for i,c in enumerate(candidate_logs)]}
    _save_json(final,row)
    return row


def _report(out,rows,fingerprint):
    ordered=sorted(rows,key=lambda r:(r['model_id'],r['image_id'],r['repeat']))
    pending=out/'summary.csv.tmp'
    with pending.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=CSV_COLUMNS)
        writer.writeheader();writer.writerows({key:r.get(key) for key in CSV_COLUMNS} for r in ordered)
    pending.replace(out/'summary.csv')
    groups=defaultdict(list)
    for row in ordered:groups[row['model_id']].append(row)
    result={}
    for mid,items in sorted(groups.items()):
        status=Counter(row['status'] for row in items)
        times=[row['seconds_total'] for row in items if row['valid'] and isinstance(row['seconds_total'],(int,float))]
        scores=[row['best_score'] for row in items if row['best_score'] is not None]
        result[mid]={'attempts':len(items),'unique_images':len({row['image_id'] for row in items}),
                     'valid_svg':status['valid_svg'],'valid_rate':round(status['valid_svg']/len(items),4),
                     'statuses':dict(status),'mean_seconds_valid':round(statistics.mean(times),2) if times else None,
                     'mean_best_score_diagnostic':round(statistics.mean(scores),2) if scores else None,
                     'n_scored':len(scores),
                     'objective_type':sorted({row['score_type'] for row in items if row['score_type']})}
    report={'version':VERSION,'run_fingerprint':fingerprint,'attempts':len(ordered),
            'unique_images':len({row['image_id'] for row in ordered}),
            'models':result,'final_pass':None,
            'note':'Visual proxy without reviewed ROIs is not the official V3 score; uncalibrated against humans.'}
    _save_json(out/'summary.json',report)
    return report


def run(config:Path,images_dir:Path,out:Path,*,repeats=None,resume=False,
        dry_run=False,verify_models=False,selected=None,retry_failed=False):
    cfg=_load_config(Path(config))
    models=cfg['models']
    if selected:
        wanted=set(selected)
        models=[m for m in models if m['id'] in wanted]
        if wanted!={m['id'] for m in models}:
            raise ValueError('unknown model IDs: '+str(sorted(wanted-{m['id'] for m in models})))
    data=_find_images(Path(images_dir))
    settings=cfg['generation']
    n=repeats if repeats is not None else settings.get('repeats',1)
    if type(n) is not int or not 1<=n<=100:raise ValueError('repeats must be 1..100')
    p1=Path(__file__).parent/'prompts'/'svg_v1.md'
    if not p1.is_file():raise FileNotFoundError(p1)
    from .harness_refine import REFINER_PROMPT
    # Pin inputs, prompts, options and image/annotation hashes: resume cannot mix experiments.
    signature={'version':VERSION,
               'models':[{k:model.get(k) for k in ('id','endpoint','model','concurrency','api_key_env')} for model in models],
               'generation':{**settings,'repeats':n},
               'images':data,'p1_prompt_sha256':_sha(p1.read_bytes()),
               'p2_prompt_sha256':_sha(REFINER_PROMPT.encode('utf-8'))}
    fingerprint=_sha(json.dumps(signature,ensure_ascii=False,sort_keys=True).encode('utf-8'))
    plan={'fingerprint':fingerprint,'n_models':len(models),'n_images':len(data),
          'n_tasks':len(models)*len(data)*n,'repeats':n,
          'models':[m['id'] for m in models],
          'protocol':'P2' if settings.get('max_refinements',0)>0 else 'P1',
          'annotated_images':sum(bool(i['regions']) for i in data),
          'unannotated_images':sum(not i['regions'] for i in data)}
    if dry_run:return plan
    for model in models:_model_key(model)
    if verify_models:
        for model in models:_check_model(model)
    if settings.get('max_refinements',0):
        try:import PIL
        except ImportError as ex:raise RuntimeError('P2 needs Pillow and resvg_py or cairosvg') from ex
        try:import resvg_py
        except ImportError:
            try:import cairosvg
            except ImportError as ex:raise RuntimeError('P2 needs resvg_py or cairosvg renderer') from ex
    out=Path(out).resolve()
    if out.exists() and any(out.iterdir()):
        if not resume:raise ValueError('output not empty; use --resume only for same experiment')
        manifest=out/'run_manifest.json'
        if not manifest.is_file() or json.loads(manifest.read_text(encoding='utf-8'))['fingerprint']!=fingerprint:
            raise ValueError('run fingerprint mismatch: use a new --out')
    else:
        out.mkdir(parents=True,exist_ok=True)
        _save_json(out/'run_manifest.json',{'fingerprint':fingerprint,'plan':plan,'config':signature})
    # Shared endpoint aliases have a shared capacity limit (conservative minimum).
    capacities={}
    for model in models:
        ep=model['endpoint'].rstrip('/')
        capacity=min(m.get('concurrency',1) for m in models if m['endpoint'].rstrip('/')==ep)
        capacities[ep]=threading.BoundedSemaphore(capacity)
    tasks=[(m,d,r) for m in models for d in data for r in range(n)]
    workers=min(32,sum(m.get('concurrency',1) for m in models),len(tasks))
    rows=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(_run_task,m,d,r,out,fingerprint,settings,
                             capacities[m['endpoint'].rstrip('/')],
                             resume=resume,retry_failed=retry_failed) for m,d,r in tasks]
        for future in as_completed(futures):
            rows.append(future.result())
            _report(out,rows,fingerprint)
    return _report(out,rows,fingerprint)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Multi-vLLM image-to-SVG P1/P2 generation harness')
    parser.add_argument('action',nargs='?',default='generate',choices=['generate'])
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--images',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--repeats',type=int)
    parser.add_argument('--model-id',action='append',dest='selected')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--retry-failed',action='store_true',help='Redo transport errors when resuming')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--verify-models',action='store_true')
    args=parser.parse_args(argv)
    try:
        response=run(args.config,args.images,args.out,repeats=args.repeats,
                     resume=args.resume,dry_run=args.dry_run,
                     verify_models=args.verify_models,selected=args.selected,
                     retry_failed=args.retry_failed)
    except (ValueError,OSError,RuntimeError,json.JSONDecodeError,urllib.error.URLError) as ex:
        parser.exit(2,'harness error: '+str(ex)+'\n')
    print(json.dumps(response,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
