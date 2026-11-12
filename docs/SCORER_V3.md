# SVG Document Similarity V3 (provisional)

## Goal and score

Measure **original input document image vs rendered SVG** fidelity. Fixed provisional profile:

- Page visual = 0.5 × Foreground F1 + 0.5 × Edge F1.
- Each table ROI = 0.3 × Foreground F1 + 0.7 × Edge F1.
- Table score = equal-weight mean of all reviewed table ROIs, regardless of page area.
- Document score (0–100) = 100 × (0.7 × Page + 0.3 × Tables).
- For explicitly table-free documents, use a separate 100%-Visual profile.
- Threshold: grayscale below 230; spatial tolerance 2 px. >2% aspect-ratio mismatch prevents scoring.
- No deskew/registration/automatic table detection. **No human calibration; final_pass is null.**

The original image is the scoring reference, not an incomplete handmade SVG. Critical small tables are independently penalized instead of disappearing into page averages.

## ROI manifest

All bounding boxes are `[x,y,width,height]` in original-image pixels:

```json
{
  "image_size": [1000, 1414],
  "tables": [
    {"id":"upper_right_table","bbox":[640,91,258,152]},
    {"id":"main_grid","bbox":[76,371,830,742]}
  ],
  "ignore_regions": []
}
```

In documents containing filled values, stamps, handwriting, or watermarks excluded from the *blank form generation* task, mark those specific areas as `ignore_regions` and review masks. Do not mask fixed labels or cell edges. Missing/invalid table ROIs do not silently turn into a passing score. An actual table-free page requires `tables: []` plus `no_tables: true`.

## Run

```bash
pip install -r requirements-svg-visual.txt
python -m formgen svg score-v3 --source-image input.png --pred output.svg --regions table_regions.json --out score.json

# In benchmark, each official item needs a reviewed table_regions.json
python -m formgen svg bench --items bench/official_pilot_v1 --endpoint http://internal:8000/v1 --model MODEL --allow-candidates --repeat 3 --v3 --out runs/model_v3
```

V2 is retained for diagnostics. Rendered comparison prefers resvg-py, with CairoSVG fallback; backend/version are recorded. Pin Korean fonts for cross-machine consistency.

## Optional official GriTS Top / Loc

```bash
pip install -r requirements-svg-grits.txt
python -m formgen svg score-v3 --source-image input.png --pred output.svg --regions table_regions.json --require-grits --out score.json
```

For each table add a `reference_cells` array with row/col, optional rowspan/colspan and bbox. Predicted SVG needs an untransformed transparent root-level rect per cell with `data-cell="1"`, `data-table="upper_right_table"`, `data-row`, `data-col`, optional data-rowspan/data-colspan, and x/y/width/height. The canonical grits-metric library computes true GriTS Top and Loc, separately from the fixed 70:30 ROI score.

**Arbitrary SVG strokes are not automatically interpreted as merged cells.** Missing cell annotations or library are explicit status values; `--require-grits` prevents numerical scoring when GriTS cannot run. No silent substitution.

## Next stage

Review table ROIs and variable-value masks for the three images; collect actual VLM-generated SVGs; blind-score human fidelity; compare Visual-only vs fixed V3 vs GriTS-enhanced candidates using Spearman, MAE, and catastrophic false accepts. Freeze weights only after held-out review. Repeated generations from a single document are correlated.

Initial synthetic error-injection and handmade-SVG ablations show metric responsiveness, not calibrated absolute reconstruction quality.

Reference: https://github.com/kensho-technologies/grits
