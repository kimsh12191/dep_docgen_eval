"""Regression tests for review integrity, independent inputs, and browser workflow."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path

from tplgen import evaluate, package as P, review, viewer
from tplgen.render import Renderer

SCHEMA = {'title': 'Invoice', 'language': 'en', 'fields': [{'name': 'customer', 'label': 'Customer', 'type': 'name'},
          {'name': 'account', 'label': 'Account', 'type': 'text'}],
          'tables': [{'name': 'items', 'label': 'Items', 'min_rows': 0, 'max_rows': 3,
                      'columns': [{'name': 'description', 'label': 'Description', 'type': 'text'}]}]}
SAMPLE = {'customer': 'Alice', 'account': 'AB123', 'items': [{'description': 'Paper'}]}
HTML = '''<!doctype html><html><head><style>
body {margin:0;font-family:sans-serif} .page {width:500px;min-height:450px;padding:20px;box-sizing:border-box}
table {width:100%;border-collapse:collapse} td,th {border:1px solid;padding:8px} p {margin:20px 0}
</style></head><body><div class="page"><h1>Invoice</h1><p>Customer: <span data-field="customer">{{ customer }}</span></p>
<p>Account: <span data-field="account">{{ account }}</span></p><table><tr><th>Description</th></tr>
{% for row in items %}<tr><td data-field="items.{{ loop.index0 }}.description">{{ row.description }}</td></tr>{% endfor %}
</table><p>Terms apply.</p></div></body></html>'''


def fixture(root, renderer):
    item = Path(root) / 'document'
    ref = item / 'reference'
    P.save({'template.html': HTML, 'schema.json': json.dumps(SCHEMA), 'sample.json': json.dumps(SAMPLE)}, ref)
    renderer.render(P.html(P.load(ref), SAMPLE), item / 'image.png')
    review.write_json(item / 'contract.json', review.draft(item))
    return item


def approve(item):
    return review.decide(item, 'approved', 'test reviewer', dict.fromkeys(review.CHECKS, True), 'test only', review.fingerprint(item))


class ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.renderer = Renderer().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.renderer.__exit__()

    def test_approval_invalidated_by_any_source_change(self):
        with tempfile.TemporaryDirectory() as root:
            item = fixture(root, self.renderer)
            self.assertEqual(review.status(item)['status'], 'pending')
            with self.assertRaises(ValueError):
                evaluate.preflight(root)
            with self.assertRaises(ValueError):
                review.decide(item, 'approved', 'someone', {}, '', review.fingerprint(item))
            approve(item)
            self.assertEqual(review.status(item)['status'], 'approved')
            for path in [item / 'contract.json', item / 'reference' / 'template.html', item / 'image.png']:
                original = path.read_bytes()
                path.write_bytes(original + b' ')
                self.assertEqual(review.status(item)['status'], 'stale')
                with self.assertRaises(ValueError):
                    evaluate.preflight(root)
                path.write_bytes(original)
            self.assertEqual(evaluate.preflight(root), [item])

    def test_reference_and_equivalent_renamed_template_pass(self):
        with tempfile.TemporaryDirectory() as root:
            item = fixture(root, self.renderer)
            approve(item)
            good = evaluate.evaluate(item, item / 'reference', self.renderer)
            self.assertTrue(good['pass'], good)
            pkg = P.load(item / 'reference')
            schema = copy.deepcopy(SCHEMA)
            schema['fields'][0]['name'] = 'client'
            sample = {**SAMPLE, 'client': SAMPLE['customer']}
            del sample['customer']
            candidate = Path(root) / 'candidate'
            P.save({'template.html': HTML.replace('customer', 'client'), 'schema.json': json.dumps(schema), 'sample.json': json.dumps(sample)}, candidate)
            result = evaluate.evaluate(item, candidate, self.renderer)
            self.assertTrue(result['pass'], result)
            self.assertEqual(result['mapping']['customer'], 'client')

    def test_frozen_missing_hidden_and_truncated_rows_fail(self):
        with tempfile.TemporaryDirectory() as root:
            item = fixture(root, self.renderer)
            approve(item)
            for name, html in {
                'frozen': HTML.replace('{{ customer }}', 'Alice'),
                'hidden': HTML.replace('data-field="customer"', 'style="opacity:0" data-field="customer"'),
                'rows': HTML.replace('for row in items', 'for row in items[:1]'),
                'swap': HTML.replace('{{ customer }}', '{{ account }}').replace('{{ account }}</span></p><table>', '{{ customer }}</span></p><table>'),
            }.items():
                candidate = Path(root) / name
                P.save({'template.html': html, 'schema.json': json.dumps(SCHEMA), 'sample.json': json.dumps(SAMPLE)}, candidate)
                result = evaluate.evaluate(item, candidate, self.renderer)
                self.assertFalse(result['pass'], (name, result))
                self.assertLess(result['change_pass_rate'], 1, (name, result))
            schema = copy.deepcopy(SCHEMA)
            schema['fields'] = schema['fields'][1:]
            candidate = Path(root) / 'missing'
            P.save({'template.html': HTML.replace('<span data-field="customer">{{ customer }}</span>', 'Alice'),
                    'schema.json': json.dumps(schema), 'sample.json': json.dumps(SAMPLE)}, candidate)
            result = evaluate.evaluate(item, candidate, self.renderer)
            self.assertLess(result['field_recall'], 1)
            self.assertFalse(result['pass'])

    def test_mapping_is_one_to_one(self):
        required = {'a': {'label': 'Name', 'type': 'name'}, 'b': {'label': 'Name', 'type': 'name'}}
        actual = {'large_box': {'label': 'Name', 'type': 'name'}}
        self.assertEqual(len(evaluate.match_groups(required, actual)), 1)
        with self.assertRaises(ValueError):
            evaluate.match_groups(required, actual, {'a': 'large_box', 'b': 'large_box'})
        self.assertEqual(evaluate.match_groups(required, {'x': required['a'], 'y': required['b']}), {})

    def test_report_includes_missing_outputs_and_full_cost(self):
        with tempfile.TemporaryDirectory() as root:
            dataset = Path(root) / 'data'
            item = fixture(dataset, self.renderer)
            approve(item)
            runs = Path(root) / 'runs'
            for stage in ('round0', 'final'):
                P.save({n: (item / 'reference' / n).read_text() for n in P.FILES}, runs / 'good' / item.name / stage)
            for k in range(3):
                d = runs / 'good' / item.name / f'round{k}'
                d.mkdir(parents=True, exist_ok=True)
                review.write_json(d / 'make.json', {'seconds': 2, 'usage': {'total_tokens': 10}})
            (runs / 'missing' / item.name).mkdir(parents=True)
            # report owns a Renderer; avoid nesting sync Playwright contexts on this thread.
            result = []
            def run():
                result.append(evaluate.report(dataset, runs, Path(root) / 'report'))
            thread = threading.Thread(target=run)
            thread.start(); thread.join()
            self.assertTrue(result)
            rows = [json.loads(s) for s in (Path(root) / 'report' / 'results.jsonl').read_text().splitlines()]
            final = next(r for r in rows if r['model'] == 'good' and r['stage'] == 'final')
            self.assertEqual((final['seconds_total'], final['tokens_total'], final['calls']), (6, 30, 3))
            self.assertTrue(all(not r['pass'] for r in rows if r['model'] == 'missing'))


class ViewerBrowserTests(unittest.TestCase):
    def test_review_workflow_in_browser(self):
        from playwright.sync_api import sync_playwright
        import os
        with tempfile.TemporaryDirectory() as root:
            with Renderer() as r:
                item = fixture(root, r)
            server = viewer.make_server(root, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=os.environ.get('TPLGEN_CHROMIUM') or None)
                    page = browser.new_page(viewport={'width': 1440, 'height': 1100})
                    errors = []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_port}')
                    page.wait_for_function("() => document.getElementById('title').textContent === 'document'")
                    page.click('#preview')
                    page.wait_for_function("() => document.querySelectorAll('#cases option').length > 1")
                    page.wait_for_function("() => !document.getElementById('preview').disabled")
                    page.click('#approve')
                    page.wait_for_function("() => document.getElementById('notice').textContent.includes('모든 시험')")
                    for option in page.locator('#cases option').evaluate_all('(els) => els.map(e=>e.value)'):
                        page.select_option('#cases', option)
                        page.wait_for_function("() => document.getElementById('reference').complete && document.getElementById('reference').naturalWidth > 0")
                    page.fill('#reviewer', 'Browser Test')
                    for check in review.CHECKS:
                        page.check(f'[data-check="{check}"]')
                    page.click('#approve')
                    page.wait_for_function("() => document.getElementById('status').textContent === '승인'")
                    self.assertEqual(review.status(item)['status'], 'approved')
                    page.screenshot(path='/tmp/docgen-review-viewer.png', full_page=True)
                    self.assertEqual(errors, [])
                    # Cross-origin writes lack the session token and must fail.
                    response = page.request.post(f'http://127.0.0.1:{server.server_port}/api/decision', data={'id': 'document'})
                    self.assertEqual(response.status, 403)
                    browser.close()
            finally:
                server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
