"""Fake-HTTP integration checks for multi-vLLM SVG P1/P2, no GPU required."""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

from formgen import harness
from formgen.harness_refine import assess
from formgen import svg_eval_v3


def svg_case(*,table=True,title=True):
    content=['<rect x="0" y="0" width="350" height="180" fill="white"/>']
    if title:content.append('<text x="15" y="28" font-size="15">Sample Document</text>')
    content.append('<rect x="10" y="48" width="120" height="80" fill="none" stroke="black"/>')
    if table:
        content.extend(['<rect x="250" y="48" width="88" height="52" fill="none" stroke="black"/>',
                        '<line x1="250" y1="74" x2="338" y2="74" stroke="black"/>',
                        '<line x1="294" y1="48" x2="294" y2="100" stroke="black"/>'])
    content.append('<rect data-field="name" data-label="Name" data-type="text" '
                   'x="12" y="50" width="40" height="14" fill="none" stroke="none"/>')
    return '<svg xmlns="http://www.w3.org/2000/svg" width="350" height="180" viewBox="0 0 350 180">'+''.join(content)+'</svg>'

GOOD=svg_case()
BAD=svg_case(table=False)
WORSE=svg_case(table=False).replace('Sample Document','Incorrect')


class Fake:
    def __init__(self,refined=GOOD,first=BAD):
        self.count=0
        self.posts=[]
        ref=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                body=json.dumps({'data':[{'id':'test-model'}]}).encode()
                self.send_response(200);self.end_headers();self.wfile.write(body)
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                ref.count+=1;ref.posts.append(payload)
                is_refiner='refine' in payload['messages'][0]['content'].lower()
                text=refined if is_refiner else first
                data=json.dumps({'choices':[{'message':{'content':text},'finish_reason':'stop'}],
                                 'usage':{'prompt_tokens':100,'completion_tokens':45}}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.end_headers();self.wfile.write(data)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.endpoint=f'http://127.0.0.1:{self.server.server_port}/v1'

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join()


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.data=self.root/'images'
        self.data.mkdir()
        self.server=Fake();self.addCleanup(self.server.close)
        self.config=self.root/'config.json'
        self.default={'models':[{'id':'v9','endpoint':self.server.endpoint,
                                 'model':'test-model','concurrency':2}],
                      'generation':{'max_tokens':5000,'repeats':1,'max_refinements':1,
                                    'feedback_crop_pairs':0,'min_improvement':0.25}}
        self.store=self.root/'runs'
        self.image=self.data/'doc1'/'image.png'
        self.image.parent.mkdir()
        png,_=svg_eval_v3._render(GOOD,(350,180),[])
        self.image.write_bytes(png)
        self.rois=self.image.parent/'table_regions.json'
        self.rois.write_text(json.dumps({'image_size':[350,180],
            'tables':[{'id':'small','bbox':[247,45,94,58]}],'ignore_regions':[]}))
        (self.image.parent/'meta.json').write_text('{"tier":"hard"}')
        self._config()

    def _config(self):self.config.write_text(json.dumps(self.default))
    def test_p2_improvement_and_provenance(self):
        report=harness.run(self.config,self.data,self.store,verify_models=True)
        self.assertEqual(report['attempts'],1)
        row=json.loads(next(self.store.glob('v9/**/status.json')).read_text())
        self.assertEqual(row['protocol'],'P2')
        self.assertEqual(row['status'],'valid_svg')
        self.assertEqual(row['chosen_round'],1)
        self.assertLess(row['initial_score'],row['best_score'])
        self.assertEqual(row['score_type'],'v3_70_30')
        folder=next(self.store.glob('v9/**/status.json')).parent
        self.assertEqual((folder/'round_0/out.svg').read_text(),BAD)
        self.assertEqual((folder/'round_1/out.svg').read_text(),GOOD)
        self.assertEqual((folder/'best.svg').read_text(),GOOD)
        self.assertTrue((folder/'round_0/visual/difference.png').is_file())
        self.assertTrue((folder/'round_0/visual/score_v3.json').is_file())
        self.assertEqual(len(self.server.posts),2)
        content=self.server.posts[1]['messages'][1]['content']
        self.assertEqual(len([part for part in content if part['type']=='image_url']),2)

    def test_regression_reverts_to_initial(self):
        self.server.close()
        self.server=Fake(refined=WORSE)
        self.addCleanup(self.server.close)
        self.default['models'][0]['endpoint']=self.server.endpoint;self._config()
        report=harness.run(self.config,self.data,self.store)
        self.assertEqual(report['models']['v9']['valid_svg'],1)
        row=json.loads(next(self.store.glob('v9/**/status.json')).read_text())
        self.assertEqual(row['chosen_round'],0)
        self.assertEqual(row['best_score'],row['initial_score'])
        self.assertEqual(row['stop_reason'],'stopped_regression')
        self.assertIsNone(row['error'])
        self.assertEqual(Path(row['best_svg']).read_text(),BAD)
        self.assertTrue((Path(row['best_svg']).parent/'round_1/out.svg').is_file())

    def test_resume_and_config_guard(self):
        harness.run(self.config,self.data,self.store)
        before=self.server.count
        harness.run(self.config,self.data,self.store,resume=True)
        self.assertEqual(self.server.count,before)
        self.default['generation']['max_tokens']=7777;self._config()
        with self.assertRaisesRegex(ValueError,'fingerprint'):
            harness.run(self.config,self.data,self.store,resume=True)
        self.assertEqual(self.server.count,before)

    def test_unannotated_has_explicit_proxy(self):
        self.rois.unlink()
        harness.run(self.config,self.data,self.store)
        row=json.loads(next(self.store.glob('v9/**/status.json')).read_text())
        self.assertEqual(row['score_type'],'visual_proxy_unannotated')
        self.assertLess(row['initial_score'],row['best_score'])

    def test_multiple_models_and_repeats(self):
        self.default['generation']['max_refinements']=0
        self.default['generation']['repeats']=2
        self.default['models'].append({'id':'v27','endpoint':self.server.endpoint,
                                      'model':'test-model','concurrency':1})
        self._config()
        report=harness.run(self.config,self.data,self.store)
        self.assertEqual(report['attempts'],4)
        self.assertEqual(report['models']['v9']['valid_svg'],2)
        self.assertEqual(report['models']['v27']['valid_svg'],2)
        self.assertEqual(self.server.count,4)
        self.assertEqual(len(list(self.store.glob('*/**/best.svg'))),4)

    def test_optional_difference_image_feedback(self):
        self.default['generation']['feedback_include_difference']=True
        self._config()
        harness.run(self.config,self.data,self.store)
        imgs=[p for p in self.server.posts[1]['messages'][1]['content']
              if p['type']=='image_url']
        self.assertEqual(len(imgs),3)

    def test_p1_invalid_is_repaired_without_renderer(self):
        self.server.close()
        damaged=BAD.replace('</svg>','<script/></svg>')
        self.server=Fake(first=damaged,refined=GOOD)
        self.addCleanup(self.server.close)
        self.default['models'][0]['endpoint']=self.server.endpoint;self._config()
        harness.run(self.config,self.data,self.store)
        row=json.loads(next(self.store.glob('v9/**/status.json')).read_text())
        self.assertEqual(row['chosen_round'],1)
        self.assertIsNone(row['initial_score'])
        self.assertIsNotNone(row['best_score'])
        self.assertEqual(row['rounds_completed'],1)
        self.assertEqual(row['status'],'valid_svg')
        self.assertEqual(len(self.server.posts),2)
        self.assertEqual(len(self.server.posts[1]['messages'][1]['content']),2)

    def test_bad_refinement_is_retained_but_not_selected(self):
        self.server.close()
        damaged=GOOD.replace('</svg>','<script/></svg>')
        self.server=Fake(refined=damaged)
        self.addCleanup(self.server.close)
        self.default['models'][0]['endpoint']=self.server.endpoint;self._config()
        harness.run(self.config,self.data,self.store)
        row=json.loads(next(self.store.glob('v9/**/status.json')).read_text())
        self.assertEqual(row['status'],'valid_svg')
        self.assertEqual(row['chosen_round'],0)
        self.assertEqual(row['error'],'refinement_invalid_svg')
        self.assertEqual(Path(row['best_svg']).read_text(),BAD)

    def test_feedback_crops_and_resume_partial(self):
        self.default['generation']['feedback_crop_pairs']=1;self._config()
        harness.run(self.config,self.data,self.store)
        self.assertEqual(len([p for p in self.server.posts[1]['messages'][1]['content']
                              if p['type']=='image_url']),4)
        status_file=next(self.store.glob('v9/**/status.json'))
        status_file.unlink()
        before=self.server.count
        harness.run(self.config,self.data,self.store,resume=True)
        self.assertEqual(self.server.count,before)

    def test_wrong_model_id_and_key_config(self):
        with self.assertRaisesRegex(ValueError,'unknown model'):
            harness.run(self.config,self.data,self.store,selected=['not-registered'],dry_run=True)
        self.default['models'][0]['api_key']='secret'
        self._config()
        with self.assertRaisesRegex(ValueError,'api_key_env'):
            harness.run(self.config,self.data,self.store,dry_run=True)

    def test_dry_run_has_no_side_effect(self):
        plan=harness.run(self.config,self.data,self.store,dry_run=True)
        self.assertEqual(plan['n_tasks'],1)
        self.assertEqual(plan['annotated_images'],1)
        self.assertFalse(self.store.exists())
        self.assertEqual(self.server.count,0)

    def test_roi_omission_is_error_not_fake_score(self):
        self.rois.write_text(json.dumps({'image_size':[300,180], 'tables':[]}))
        r=harness.run(self.config,self.data,self.store)
        row=json.loads(next(self.store.glob('v9/**/status.json')).read_text())
        self.assertEqual(row['status'],'harness_error')
        self.assertIsNone(row['best_score'])
        self.assertEqual(r['models']['v9']['valid_svg'],0)


if __name__=='__main__':unittest.main()
