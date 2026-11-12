import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from formgen import svg
from formgen.svg_cli import make

SAMPLE='<svg xmlns="http://www.w3.org/2000/svg" width="794" height="1123" viewBox="0 0 794 1123"><text x="10" y="20">Name</text><rect data-field="name" data-label="Name" data-type="text" x="100" y="30" width="100" height="20" fill="none" stroke="none"/></svg>'


class SvgTests(unittest.TestCase):
    def test_identity(self):
        r=svg.score(SAMPLE,SAMPLE)
        self.assertTrue(r['valid']);self.assertEqual(r['located_field_f1'],1)
        self.assertEqual(r['text_f1'],1);self.assertIsNone(r['final_pass'])

    def test_wrong_type_and_position(self):
        self.assertEqual(svg.score(SAMPLE,SAMPLE.replace('data-type="text"','data-type="amount"'))['typed_field_f1'],0)
        shifted=SAMPLE.replace('x="100"','x="500"')
        self.assertEqual(svg.score(SAMPLE,shifted)['typed_field_f1'],1)
        self.assertEqual(svg.score(SAMPLE,shifted)['located_field_f1'],0)

    def test_invalid_contract(self):
        variants=[SAMPLE.replace('x="100"','x="900"'), SAMPLE.replace('</svg>','<script/></svg>'),
                  SAMPLE.replace('</svg>','<image href="file:///secret"/></svg>'),
                  SAMPLE.replace('<text ','<text style="display:none" '),
                  SAMPLE.replace('viewBox="0 0 794 1123"','viewBox="0 0 nan 1123"'),
                  '<!DOCTYPE svg>'+SAMPLE,SAMPLE[:-10]]
        for value in variants:self.assertFalse(svg.parse(value)['valid'],value)
        self.assertFalse(svg.score(SAMPLE,'bad xml')['valid'])

    def test_duplicate_and_check_options(self):
        extra=SAMPLE[SAMPLE.index('<rect'):SAMPLE.index('</svg>')]
        self.assertFalse(svg.parse(SAMPLE.replace('</svg>',extra+'</svg>'))['valid'])
        check=SAMPLE.replace('data-type="text"','data-type="checkbox" data-options="yes|no"')
        self.assertEqual(svg.score(check,check.replace('yes|no','yes'))['typed_field_f1'],0)

    def test_local_model_transport(self):
        received=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                body=json.dumps({'choices':[{'message':{'content':SAMPLE},'finish_reason':'stop'}]}).encode()
                self.send_response(200);self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            with tempfile.TemporaryDirectory() as d:
                image=Path(d)/'image.png';image.write_bytes(b'fake transport image')
                log=make(image,Path(d)/'out',f'http://127.0.0.1:{server.server_port}/v1','fake')
                self.assertTrue(log['valid']);self.assertEqual(log['prompt'],'svg_v1')
                self.assertEqual(received[0]['messages'][1]['content'][0]['type'],'image_url')
                self.assertEqual((Path(d)/'out/out.svg').read_text(),SAMPLE)
        finally:server.shutdown();server.server_close();worker.join()

    def test_renderer(self):
        try:import resvg_py
        except ImportError:self.skipTest('optional resvg_py not installed')
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'out.png';log=svg.render(SAMPLE,out)
            self.assertEqual(out.read_bytes()[:8],b'\x89PNG\r\n\x1a\n')
            self.assertEqual(log['renderer'],'resvg_py')


if __name__=='__main__':unittest.main()
