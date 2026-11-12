# Purpose-to-implementation audit — 2026-11-12

## CURRENT SCOPE OVERRIDE — latest user clarification

Required: reliable model × difficulty pass-rate tables; a manual difficulty guide with representative/boundary cases;
SVG generation using a user-selected model through the same generator as the benchmark.
Automatic routing and image-only difficulty prediction are NOT required.
Value filling, training images, label export and downstream OCR/KIE production are deferred, not milestone blockers.
The earlier audit below is retained as history; its routing/production requirements and steps 4–5 are superseded.

Current remaining sequence:
1. Complete/review balanced SVG gold and manually record difficulty features and reasons.
2. Verify generated SVG render/field quality; calibrate and freeze a pass rule on development outputs.
3. Run selected internal models on held-out cases with fixed settings and repeated trials.
4. Report model × tier pass counts/rates, unique-image counts, attempt counts, uncertainty, failures, time and tokens.
5. Use docs/DIFFICULTY_GUIDE.md to help the USER compare new images and select models manually.

Repeated outputs of one image are correlated; do not report them as independent images.

## Earlier scope audit — superseded where noted above

Authoritative objective: `목적.md`, clarified by the user in conversation.
The product has three connected uses: model capability measurement; model selection for an unseen document;
and real template generation using exactly the generation function used by the benchmark.
The template ultimately produces OCR/classification/KIE training data with correct field labels.
Switching HTML to SVG changes the output contract; it does not complete these objectives.

| Requirement | Current SVG implementation | Remaining gap |
|---|---|---|
| Image + selected model → template | svg_cli.make calls internal-compatible llm.chat and writes out.svg/raw.txt/make.json | Real internal model validation; robust output quality and operational error handling |
| Same generation in make and bench | Both call svg_cli.make | Preserve this invariant when adding routing, retries and validation |
| Fixed set × model evaluation | svg bench runs one model over item folders, saves item scores and summary JSON | Multiple model orchestration, repeats, uncertainty, tier aggregation and report |
| Approved gold | 3 official PDF-backed candidates; 0 approved | Complete annotations, development/test separation and coverage |
| L0 usability | Restricted SVG XML contract | Actual render success and overlap/overflow not integrated into make/bench |
| L1/L3 content and fields | Text bigrams, label/type/options, declared region IoU | Compare original-image/render quality, aliases/date equivalences, annotation completeness |
| L2/L4 structure and appearance | Separate SVG rendering works | SVG table topology and visual evaluation are not implemented |
| Fixed pass threshold | final_pass is null | Human calibration and frozen rule/version; no valid pass-rate table yet |
| Unseen image → smallest adequate model | No implementation | No image-only difficulty estimator, policy/model catalog, or validated reference-free quality gate |
| Cost/reproducibility | seconds, usage, prompt version, P1, temperature, token cap saved | Full model config, hashes/input resolution, repeats, confidence intervals, cost ranking |
| Training data production | Empty field rectangles + render command | Fill values/checks/seals, validate placement, export corresponding labels and dataset |

## Important interpretation rules

- `score` requires a reference; it cannot be used to decide quality for a new unannotated image.
- A syntactically valid SVG can omit fields or reproduce the wrong form. Do not automatically escalate/accept using XML validity alone.
- Existing difficulty.py uses reference HTML; it is not an image-only difficulty estimator and not the SVG router.
- The previous Sol/Luna/Terra run is a one-image HTML agent smoke test, not the fixed-protocol SVG model benchmark described in 목적.md.
- The old 60-item HTML roundtrip set is not a completed 60-item SVG gold set.
- SVG conversion does not provide compatibility with docgen template.html.j2/form.json consumers; an adapter or dedicated SVG filling pipeline is needed.
- Runtime human intervention may be zero only after construction-time gold review/calibration is complete. Do not introduce per-image approval as the intended routing workflow.

## Recommended implementation sequence

1. Complete and review a small balanced SVG gold pilot; fix declared-field and actual-render usability checks.
2. Run internal small/large models with frozen prompts, repeat settings and metadata through the same make function.
3. Calibrate and version pass criteria; aggregate model × tier × protocol results with uncertainty and cost.
4. Validate reference-free quality signals on held-out gold. Implement model catalog + escalation/selection policy only after these signals are measured.
5. Add real value filling and label export so templates become usable training-data generators.

Routing fallback without a trusted quality signal must be explicit (e.g. configured default model / uncertain result),
not a fabricated guarantee that the chosen model will pass.
