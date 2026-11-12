"""V2 page selection, immutable pilot images and gallery smoke tests."""
import json
import os
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from tools import prepare_form_candidates as C

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'evalset/forms_candidates_v2'


class ComplexCandidateTests(unittest.TestCase):
    def test_v2_preserves_pilot_and_adds_complex_pages(self):
        rows = C.read(DATA / 'manifest.json')['items']
        old = {r['id']: r for r in C.read(ROOT / 'evalset/forms_candidates_v1/manifest.json')['items']}
        self.assertEqual(len(rows), 60)
        self.assertEqual(sum(bool(r['complexity_tags']) for r in rows), 24)
        self.assertEqual(len({(r['source_pdf_sha256'], r['input_page_one_based']) for r in rows}), 60)
        families = {}
        for r in rows:
            self.assertEqual(C.sha(DATA / r['id'] / 'image.png'), r['image_sha256'])
            if r['id'] in old:
                self.assertEqual(r['image_sha256'], old[r['id']]['image_sha256'])
            else:
                self.assertEqual(r['raster_dpi'], 160)
                self.assertEqual(r['proposed_tier'], '상')
            self.assertIn(r['input_page_one_based'] - 1, r['declared_source_pages_zero_based'])
            self.assertEqual(r['human_review'], 'pending')
            self.assertFalse((DATA / r['id'] / 'review.json').exists())
            families[r['family']] = families.get(r['family'], 0) + r['family_weight']
        for weight in families.values():
            self.assertAlmostEqual(weight, 1)
        by_id = {r['id']: r for r in rows}
        self.assertEqual(by_id['gov_retirement_withholding__p10']['form_page_one_based'], 1)
        self.assertEqual(by_id['gov_withholding__p02']['family'], by_id['gov_pension_withholding__p20']['family'])

    def test_explicit_page_selection_and_duplicate_guard(self):
        import fitz
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source'
            source.mkdir()
            pdf = source / 'source.pdf'
            with fitz.open() as doc:
                for i in range(3):
                    p = doc.new_page()
                    p.insert_text((30, 30), 'Source page ' + str(i + 1))
                doc.save(pdf)
            row = {'id': 'gov_test', 'group': 'gov', 'title': 'Test', 'family': 'gov_test',
                   'source_commit': 'test', 'source_pdf': 'source.pdf', 'source_pdf_sha256': C.sha(pdf),
                   'source_hash_matches': True, 'source_pages_zero_based': [1, 2],
                   'source_folder': 'docgen/forms/gov_test', 'field_hints_inherited_from': None,
                   'metadata_available': True, 'field_entries': 0}
            spec = Path(tmp) / 'spec.json'
            picks = [{'id': 'gov_test__p02', 'source_id': 'gov_test', 'page': 2, 'tier': '상', 'reason': 'Table'},
                     {'id': 'gov_test__p03', 'source_id': 'gov_test', 'page': 3, 'tier': '상', 'reason': 'Table'}]
            with patch.object(C, 'inventory', return_value=[row]):
                C.write(spec, {'name': 'test', 'items': picks})
                result = C.build(source, Path(tmp) / 'good', spec)
                self.assertEqual([r['input_page_one_based'] for r in result['items']], [2, 3])
                self.assertEqual(result['family_count'], 1)
                self.assertEqual(row['source_pages_zero_based'], [1, 2])
                for case, page in [('duplicate', 2), ('out_of_form', 1), ('no_page', None)]:
                    changed = [dict(x) for x in picks]
                    changed[1]['page'] = page
                    C.write(spec, {'name': 'test', 'items': changed})
                    with self.assertRaises(ValueError):
                        C.build(source, Path(tmp) / case, spec)
                    self.assertFalse((Path(tmp) / case).exists())

    def test_complex_gallery_filter(self):
        from playwright.sync_api import sync_playwright
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(DATA)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=os.environ.get('TPLGEN_CHROMIUM') or None)
                page = browser.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.wait_for_function('() => document.getElementById("image").naturalWidth > 0')
                self.assertEqual(page.locator('#list button').count(), 24)
                self.assertIn('gov_withholding', page.locator('#title').inner_text())
                page.select_option('#filter', 'all')
                self.assertEqual(page.locator('#list button').count(), 60)
                self.assertEqual(errors, [])
                browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
