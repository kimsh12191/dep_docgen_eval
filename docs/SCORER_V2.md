# SVG scorer v2 — diagnostic evaluation (2026-11-12)

The new code keeps the **legacy_svg_v1** score block unchanged and adds separate
diagnostics. This is *not* a calibrated model pass/fail benchmark.

## Metrics

- \`recognition.text_f1\`: original edit-text bigram content score, without geometry.
- \`text_geometry.text_located_f1\`: anchor-matched explicit SVG text with normalized
  anchor distance ≤0.025. Ignores glyph paths, transforms, and implicit positions.
- \`fields.field_detection_f1\`: one-to-one field pairing by normalized geometry
  (IoU ≥0.1 OR center distance ≤0.035), not hard-gated by label.
- \`field_label_f1\`, \`field_type_f1\`, \`field_located_f1\`:
  separately count labels, types, and IoU ≥0.5 among paired fields.
- \`field_semantic_f1\`, \`field_located_semantic_f1\`:
  joint metrics when needed, with checkbox options checked for semantic match.
- \`visual.prediction_vs_source\`, \`visual.reference_vs_source\`, and
  \`visual.prediction_vs_reference\`: foreground-ink F1 and edge F1 after rendering.
  White background agreement is not rewarded. Two-pixel tolerant matching is diagnostic.

## Usage

Core score uses only stdlib:

\`\`\`bash
python -S -m formgen svg score ref.svg predicted.svg --out score.json
\`\`\`

Optional visual comparison requires local compatible resvg-py/Pillow wheels and
a reproducible Korean font:

\`\`\`bash
pip install -r requirements-svg-visual.txt
python -m formgen svg score ref.svg predicted.svg \
  --source-image original.png --visual --font-file /path/to/korean-font.ttf \
  --out runs/score.json
\`\`\`

Diagnostic batch (repeat attempts are not independent images):

\`\`\`bash
python -m formgen svg bench --items bench/official_pilot_v1 \
  --endpoint http://internal:8000/v1 --model MODEL \
  --repeat 3 --visual --allow-candidates --out runs/svg_v2
\`\`\`

Use only approved internal model endpoints for real/private documents.
Candidate gold cannot be used for final benchmark claims. Inference has not
been run here. \`final_pass\` remains \`null\`.

## Verification

Run \`python -m unittest discover -s tests -v\`.
Regression tests perturb labels, types, boxes, text positions, opacity,
and raster lines. The numerical gates above are experimental; calibrate them
against independent human usable/rework/unusable labels on dev outputs,
then freeze the rule and evaluate a held-out gold set. No automatic score
is a verified document-usable decision yet.

## Known limits

Raster alignment and fonts affect visual metrics. Scanned/filled originals
may differ from the blank-form reference; report both reference_vs_source
and prediction_vs_reference. Explicit SVG text positions are approximations
for complex text/tspan. Path-based PDF reference glyphs are not captured in
recognition metrics. A syntactically valid SVG can still be visually unusable.
