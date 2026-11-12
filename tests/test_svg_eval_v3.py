"""Counterfactual tests for visual V3; skips if no SVG renderer installed."""
import json
import tempfile
import unittest
from pathlib import Path

from formgen import svg_cli, svg_eval_v3 as v3


def sample(table=True, minor=False, title=True):
    elements=['<rect x="0" y="0" width="350" height="180" fill="white"/>']
    if title:elements.append('<text x="15" y="28" font-size="15">Sample Document</text>')
    if table:
        elements.append('<rect x="250" y="48" width="88" height="52" fill="none" stroke="black"/>')
        elements.append('<line x1="250" y1="74" x2="338" y2="74" stroke="black"/>')
        x=297 if minor else 294
        elements.append(f'<line x1="{x}" y1="48" x2="{x}" y2="100" stroke="black"/>')
    elements.append('<rect x="10" y="48" width="120" height="80" fill="none" stroke="black"/>')
    elements.append('<rect data-field="name" data-label="Name" data-type="text" x="12" y="50" width="40" height="14" fill="none" stroke="none"/>')
    return '<svg xmlns="http://www.w3.org/2000/svg" width="350" height="180" viewBox="0 0 350 180">'+''.join(elements)+'</svg>'


class VisualV3(unittest.TestCase):
    def setUp(self):
        try:png,_=v3._render(sample(),(350,180),[])
        except RuntimeError:self.skipTest("No SVG renderer installed")
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.source=self.root/'source.png';self.source.write_bytes(png)
        self.manifest={'image_size':[350,180], 'tables':[{'id':'small','bbox':[247,45,94,58]}]}

    def evaluate(self,svg,manifest=None,**kwargs):
        return v3.evaluate(self.source,svg,self.manifest if manifest is None else manifest,**kwargs)

    def test_identity(self):
        score=self.evaluate(sample())
        self.assertEqual(score['score_0_100'],100.0)
        self.assertEqual(score['tables'][0]['grits']['status'],'missing_reference_cells')
        self.assertIsNone(score['final_pass'])

    def test_missing_tiny_table_has_strong_penalty(self):
        no_table=self.evaluate(sample(table=False))
        self.assertLess(no_table['tables'][0]['roi_score'],0.10)
        self.assertLess(no_table['score_0_100'],no_table['visual']['score']*100-15)

    def test_small_shift_better_than_missing(self):
        self.assertGreater(self.evaluate(sample(minor=True))['score_0_100'],
                           self.evaluate(sample(table=False))['score_0_100'])

    def test_table_annotations_are_required(self):
        with self.assertRaises(ValueError):
            self.evaluate(sample(),{'image_size':[350,180],'tables':[]})
        self.assertEqual(self.evaluate(sample(),require_grits=True)['status'],
                         'grits_required_but_unavailable')

    def test_aspect_mismatch(self):
        other=sample().replace('viewBox="0 0 350 180"','viewBox="0 0 350 350"')
        r=self.evaluate(other)
        self.assertEqual(r['status'],'aspect_mismatch')
        self.assertIsNone(r['score_0_100'])

    def test_explicit_no_tables(self):
        m={'image_size':[350,180],'tables':[],'no_tables':True}
        self.assertEqual(self.evaluate(sample(),m)['score_0_100'],100.0)

    def test_cli_v3(self):
        pred=self.root/'output.svg';pred.write_text(sample(),encoding='utf-8')
        cfg=self.root/'regions.json';cfg.write_text(json.dumps(self.manifest))
        out=self.root/'report.json'
        svg_cli.main(['score-v3','--source-image',str(self.source),'--pred',str(pred),
                      '--regions',str(cfg),'--out',str(out)])
        self.assertEqual(json.loads(out.read_text())['score_0_100'],100.0)
        self.assertTrue((self.root/'v3_visual_assets'/'predicted.png').is_file())


if __name__=='__main__':unittest.main()
