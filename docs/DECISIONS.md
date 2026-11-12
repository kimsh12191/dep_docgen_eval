# Decisions and migration ledger

## 2026-11-12 / D007 / diagnostic SVG scorer v2

Added geometry-first field pairing with separate detection, semantic, type and localization scores, explicit text-anchor localization, optional resvg/Pillow foreground and edge F1, and repeated diagnostic attempts with unique-image counts. Preserved SVG v1 scores in `legacy_svg_v1`, did not calibrate `final_pass`, and retained unapproved gold gating. Added counterfactual regression tests and `docs/SCORER_V2.md`. No real-model quality claim. Core scoring remains stdlib-only; visual path needs optional offline wheels/fonts.


## 2026-11-12 / D006 / user scope correction — supersedes routing requirements in D005

Required: reliable model-by-difficulty pass rates, manual difficulty criteria/examples, user-selected SVG generation.
NOT required: automatic model routing, image-only difficulty prediction or reference-free routing acceptance signals.
Deferred: filling values, training-image generation and label export. These are not blockers for this milestone.
Updated purpose, agent instructions, state, audit and manual difficulty guide. No runtime metrics or thresholds changed.

## 2026-11-12 / D001 / preferred output: standalone SVG

User decision: SVG is acceptable; internal execution has no Internet and browser installation is difficult; some pip installation is possible.
Prior HTML + Playwright direction is superseded for NEW generation. Existing HTML tools remain for regression/history.
Reason: fixed form coordinates can be explicit SVG primitives and field rectangles, and rendering can use resvg rather than a browser.
Tradeoff: text wrapping/value overflow must be implemented explicitly. SVG is not automatically higher quality.

Implemented: formgen/svg.py, svg_cli.py, prompts/svg_v1.md; `python -m formgen svg {make,validate,score,render,bench}`.
Runtime: core uses stdlib; rendering lazy-loads resvg-py 0.5.0. No Playwright/Chromium needed for this path.
Authoring converter: tools/convert_official_svg.py, restricted to our absolute-positioned official candidates; not a general converter.

## 2026-11-12 / D002 / gold candidates remain candidates

Three official PDFs were downloaded and matched to previously recorded SHA-256 values. Inputs are the PDF rasters, not renders of ref.html/ref.svg.
SVG conversion adds ref.svg and ref_svg.png without deleting source.pdf/image.png/ref.html.
Inherited omissions (e.g. pension issue number/date/seal), missing QR, and approximate text baselines remain.
Do not promote candidates because a self-score is 1.0. gold_approved remains false.

## 2026-11-12 / D003 / metrics are format-versioned diagnostics

SVG matching uses declared regions + label + exact type/options, not DOM adjacency.
This changes the measured quantity; old model smoke scores are HTML only and cannot be relabeled SVG results.
Explicit provisional thresholds: label similarity 0.8, normalized region IoU 0.5.
Final pass remains null. No visual/scan robustness claim is justified by successful XML parsing or self-comparison.

## 2026-11-12 / D004 / reproducibility and font control

resvg_py 0.5.0 installed via binary wheel and used locally on Windows/Python 3.12.
Source: https://resvg-py.readthedocs.io/en/latest/api.html
Renderer writes version and explicit font hashes; default system-font mode is deliberately marked unpinned.
Visual review found stretched whitespace in first conversion. Fixed by xml:space="preserve" in text conversion and re-rendered.
Do not normalize away whitespace before applying textLength.

## Update protocol for subsequent agents

### 2026-11-12 / D005 / objective alignment

User supplied 목적.md as project purpose. Audit recorded in docs/PURPOSE_AUDIT.md.
Confirmed: manually selected model generation and benchmark share svg_cli.make.
Missing: unseen-image routing, calibrated model×tier pass-rate reporting, and SVG-to-filled-training-data integration.
Do not describe format migration as completion of the product. Preserve the requirement that real internal documents
are sent only to internal models; public/synthetic data may be used for external development experiments.

Validation at migration: 9 tests passed (including local fake model HTTP transport and resvg PNG output).
With site-packages disabled, SVG tests: 5 passed, optional renderer test skipped.
Real SVG model inference was not performed; no endpoint was supplied. The three earlier model trials remain HTML-only evidence.

Append dated decisions with: user constraint, concrete implementation paths, behavior change, validation evidence,
known limitations and migration consequences. Update STATE.json and contract version when behavior changes.
Do not write aspirations into the implemented/verified sections.

## 2026-11-12 / Scorer V3: original-image visual fidelity + table regions

Implemented fixed provisional 70% whole-page Foreground/Edge F1 plus 30% independently scored table ROIs, preventing small complex-table omissions being diluted by white page area. Optional canonical GriTS Top/Loc is available ONLY with explicit cell annotations. Invalid SVG contract is a zero-score failure; missing/invalid ROI or aspect mismatch is unscorable. Human calibration, model evaluation and final pass thresholds remain outstanding. Source images and manual scores have not been committed.
