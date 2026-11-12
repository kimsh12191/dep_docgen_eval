import json
import os
import tempfile
import unittest
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tools import prepare_form_candidates as C

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'evalset' / 'forms_candidates_v1'


class CandidateDataTests(unittest.TestCase):
    def test_inputs_provenance_and_families(self):
        manifest = C.read(DATA / 'manifest.json')
        rows = manifest['items']
        self.assertEqual(manifest['inventory_counts'], {'gov': 25, 'hana': 44, 'hf': 433})
        self.assertEqual(manifest['selected_counts'], {'gov': 12, 'hana': 12, 'hf': 12})
        self.assertEqual(len(rows), 36)
        self.assertEqual(len({r['family'] for r in rows}), 36)
        self.assertFalse({'hf138', 'hf153'}.intersection(alias for r in rows for alias in r['family_members']))
        from PIL import Image
        for r in rows:
            self.assertEqual(C.sha(DATA / r['id'] / 'image.png'), r['image_sha256'])
            with Image.open(DATA / r['id'] / 'image.png') as im:
                self.assertGreater(min(im.size), 900)
                im.verify()
            self.assertEqual(r['human_review'], 'pending')
            self.assertEqual(r['split'], 'unassigned')
            self.assertEqual(len(r['source_pages_zero_based']), 1)
            self.assertFalse((DATA / r['id'] / 'review.json').exists())
            self.assertFalse((DATA / r['id'] / 'reference').exists())

    def test_promote_requires_human_and_checks(self):
        manifest = C.read(DATA / 'manifest.json')
        r = manifest['items'][0]
        d = {'name': manifest['name'], 'source_commit': manifest['source_commit'], 'reviewer': '',
             'items': {r['id']: {'decision': 'keep', 'image_sha256': r['image_sha256'], 'checks': {}}}}
        with tempfile.TemporaryDirectory() as tmp:
            path, out = Path(tmp) / 'decisions.json', Path(tmp) / 'selected'
            for reviewer in ['', 'Test']:
                d['reviewer'] = reviewer
                C.write(path, d)
                with self.assertRaises(ValueError):
                    C.promote(DATA, path, out)
                self.assertFalse(out.exists())
            d['items'][r['id']]['checks'] = dict.fromkeys(('legible', 'representative', 'duplicates', 'fields'), True)
            C.write(path, d)
            self.assertEqual(C.promote(DATA, path, out), 1)
            self.assertTrue((out / r['id'] / 'image.png').exists())
            self.assertFalse((out / r['id'] / 'review.json').exists())
            self.assertFalse((out / r['id'] / 'reference').exists())
            with self.assertRaises(ValueError):
                C.promote(DATA, path, out)
            d['items'][r['id']]['image_sha256'] = 'wrong'
            C.write(path, d)
            with self.assertRaises(ValueError):
                C.promote(DATA, path, Path(tmp) / 'changed')

    def test_gallery_selection_and_export(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw, tempfile.TemporaryDirectory() as tmp:
            browser = pw.chromium.launch(executable_path=os.environ.get('TPLGEN_CHROMIUM') or None)
            page = browser.new_page(viewport={'width': 1440, 'height': 1100}, accept_downloads=True)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(DATA)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
            page.wait_for_function('() => document.getElementById("image").complete && document.getElementById("image").naturalWidth > 0')
            self.assertEqual(page.locator('#list button').count(), 36)
            page.click('[data-value="keep"]')
            self.assertIn('검수자', page.locator('#message').inner_text())
            page.fill('#reviewer', 'Browser test')
            for key in ('legible', 'representative', 'duplicates', 'fields'):
                page.check(f'[data-check="{key}"]')
            page.click('[data-value="keep"]')
            self.assertIn('현재 상태: 채택', page.locator('#message').inner_text())
            with page.expect_download() as download:
                page.click('#export')
            downloaded = Path(tmp) / 'decisions.json'
            download.value.save_as(str(downloaded))
            self.assertEqual(C.promote(DATA, downloaded, Path(tmp) / 'selected'), 1)
            page.select_option('#filter', 'hana')
            self.assertEqual(page.locator('#list button').count(), 12)
            page.locator('#list button').first.click()
            page.screenshot(path='/tmp/docgen-candidate-gallery.png', full_page=True)
            self.assertEqual(errors, [])
            browser.close()


if __name__ == '__main__':
    unittest.main()
