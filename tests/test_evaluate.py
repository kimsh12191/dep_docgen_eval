import tempfile
import unittest
from pathlib import Path
from formgen.evaluate import semantic_fields


class EvaluationTests(unittest.TestCase):
    def test_exact_types_and_options(self):
        f={'label':'Amount','type':'amount','options':[], 'bbox':[10,10,100,20], 'visible':True}
        self.assertEqual(semantic_fields([f],[f],794,1123)['typed_field_f1'],1)
        self.assertEqual(semantic_fields([f],[{**f,'type':'text'}],794,1123)['typed_field_f1'],0)
        c={**f,'type':'checkbox','options':['yes','no']}
        self.assertEqual(semantic_fields([c],[{**c,'options':['yes']}],794,1123)['typed_field_f1'],0)

    def test_wrong_position(self):
        f={'label':'Name','type':'text','options':[], 'bbox':[10,10,100,20], 'visible':True}
        result=semantic_fields([f],[{**f,'bbox':[600,900,100,20]}],794,1123)
        self.assertEqual(result['typed_field_f1'],1)
        self.assertEqual(result['located_typed_field_f1'],0)

    def test_hidden_and_overflow(self):
        try:
            from formgen.rendercheck import inspect
        except ImportError:
            self.skipTest('optional legacy browser dependencies unavailable')
        chrome='C:/Program Files/Google/Chrome/Application/chrome.exe'
        if not Path(chrome).exists(): self.skipTest('system Chrome unavailable')
        html='<html><body><p>Name</p><span data-field="name" data-label="Name" data-type="text" style="display:inline-block;width:100px;height:20px"></span></body></html>'
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'screen.png'
            self.assertTrue(inspect(html,target,chrome)['render_ok'])
            hidden=html.replace('<body>','<body style="display:none">')
            self.assertFalse(inspect(hidden,target,chrome)['render_ok'])
            overflow=html.replace('<body>','<body style="padding-top:1200px">')
            self.assertFalse(inspect(overflow,target,chrome)['render_ok'])


if __name__=='__main__':unittest.main()
