# SVG v1 — current preferred generation contract

Status: implemented pilot; not calibrated production benchmark. The legacy HTML contract is docs/legacy/HTML_SPEC.md.
Korean overview and usage: README.md. Code: formgen/svg.py (contract, scoring, rendering), formgen/make.py, formgen/bench.py.

## Data model

One page per SVG; root namespace `http://www.w3.org/2000/svg`, `viewBox="0 0 W H"`.
Use A4 794×1123 by default, or the original aspect ratio. Positive finite dimensions ≤5000.
Root and field rectangles must not use transforms. Field coordinates are root user units.

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="794" height="1123" viewBox="0 0 794 1123">
  <text x="30" y="60" font-size="16" font-family="Malgun Gothic">성명</text>
  <rect data-field="applicant.name" data-label="성명" data-type="text"
        x="100" y="40" width="200" height="30" fill="none" stroke="none"/>
</svg>
```

The transparent rectangle declares a fillable region, not a visible form border. Draw visible borders separately.
Every field must be a direct root child rect with unique lower-case dotted key, label, exact type and x/y/width/height.
Types: text, number, amount, date, checkbox, seal, signature. Checkboxes require pipe-delimited data-options.
Phone/account/identity numbers use text. Quantity uses number. Monetary amount uses amount.
Fixed institution names/logos/statutory text stay fixed; document-specific values are fields.

Allowed: svg,g,rect,line,polyline,polygon,path,circle,ellipse,text,tspan,title,desc.
No script/style/foreignObject/image/use, href, event handlers, CSS style/class, url(), DTD or entities.
Use presentation attributes. Text must remain editable text; model outputs should not outline glyphs.
Imported references have some inherited PDF glyph paths: a recorded exception, not permission for generated text to disappear from the text metric.
The validator cannot determine whether an arbitrary path is a letter; visual/manual review remains necessary.

## Commands

`python -m formgen svg <command>` remains an alias of `python -m formgen <command>`.

```bash
# Generate using an INTERNAL image-capable OpenAI-compatible endpoint. No external pip dependency.
python -m formgen make --image input.png --endpoint http://host:8000/v1 --model NAME --out runs/svg_one
python -m formgen validate runs/svg_one/out.svg
python -m formgen score ref.svg runs/svg_one/out.svg --out score.json
python -m formgen stats ref.svg          # countable difficulty features for the manual guide

# Render: only resvg-py and a usable Korean font are needed, no browser.
python -m pip install -r requirements-svg.txt
python -m formgen render ref.svg --out preview.png --font-file /path/to/korean-font.ttf

# Benchmark. Candidates require an explicit diagnostic flag. Same --out resumes; different settings need a fresh --out.
python -m formgen bench --items bench/official_pilot_v1 --endpoint http://host:8000/v1 --model NAME --out runs/NAME --repeat 3 --allow-candidates
python -m formgen report runs/NAME       # rebuild summary/report from results.jsonl, no model calls

# Scorer self-test and path check without a model
python -m formgen selftest
python -m formgen bench --items bench/official_pilot_v1 --out runs/mock --mock ref --allow-candidates
```

PNG sidecars record renderer version and SHA-256 of explicit font files. Without --font-file, system fonts are used and marked `system_unpinned`.
Do not redistribute OS fonts without confirming rights. For repeatable Linux/Windows runs, supply the same permitted Korean font file and record its hash.
Internal installation can use an approved package mirror or matching wheels:
`python -m pip install --no-index --find-links wheels -r requirements-svg.txt`.
Prepare wheels for the target OS, architecture and Python version on a compatible connected machine; the tested Windows wheel does not prove availability on the unknown internal target.

## Metrics

- Label similarity ≥0.8 + normalized region IoU chooses one-to-one field matches.
- typed_field_f1 requires exact type and checkbox options.
- located_field_f1 additionally requires IoU ≥0.5 (provisional).
- field_iou_mean sums typed matches' IoU over ALL reference fields; missing fields contribute zero.
- text_f1 uses text bigrams, not OCR of the render.
- valid checks the restricted XML contract, NOT visual usability.
- final_pass in a score is null pending annotation review and human calibration. No v1 table_f1 is synthesized from SVG paths.

## Benchmark aggregation (formgen/bench.py)

- results.jsonl stores raw scores per (item, repeat). Pass/fail is computed only at aggregation time from `PASS_RULE`.
- `PASS_RULE` = pass-provisional-0: valid ∧ typed_field_f1 ≥ 0.8 ∧ located_field_f1 ≥ 0.8 ∧ text_r ≥ 0.8. A hypothesis, not calibrated.
  text_r (recall) is used instead of text_f1 because candidate references keep some glyphs as outlines, so correct model text lowers precision.
- Failure type, first match: request_error, truncated, invalid:<issues>, low_fields, low_position, low_text.
- Per tier: unique images, attempts, attempt pass count, image pass count (an image passes when more than half of its attempts pass)
  with a Wilson 95% interval, images whose repeats disagree, mean scores, seconds and output tokens.
- A run containing unapproved candidates is labelled diagnostic in report.md.

Not yet implemented: renderer-based whole-page overlap/overflow evaluation, constrained field-value filling,
per-option checkbox placement, table topology, multi-page model input, retries/P2, calibrated pass/fail, multi-model comparison table.
