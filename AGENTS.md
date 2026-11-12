# Agent entry point (Codex / Claude / other LLMs)

Read `docs/STATE.json`, `docs/DECISIONS.md`, and `SVG_SPEC.md` before changing generation or evaluation.
These describe current implementation, NOT a claim that the benchmark is complete.
Read `목적.md` for product objectives and `docs/PURPOSE_AUDIT.md` for the current gap assessment.
Current scope: benchmark selected models' SVG generation and report trustworthy model-by-difficulty pass rates.
Document manual difficulty criteria and examples so the USER can compare new images and choose models.
Automatic routing and automatic difficulty prediction are explicitly NOT required.
Value filling, training-image generation and label export are deferred, not blockers for this milestone.
Keep SVG field annotations for evaluation and the SAME generator for make and bench.
Internal real documents must only be sent to internal model endpoints; external experiments use public blank forms or synthetic images.

- Current output direction: standalone SVG. Use `python -m formgen svg ...`.
- HTML commands remain explicitly legacy; do not silently change their score meaning.
- Target runtime is an internet-disconnected internal network with limited pip installation.
  Never make Playwright/Chromium, an online font fetch, or a browser download a default runtime dependency.
- Core SVG generation/validation/scoring must work with `python -S`; rendering may lazily import `resvg_py`.
- Record contract or metric changes in `docs/DECISIONS.md` and update `docs/STATE.json` in the same change.
- Preserve official source PDF/image hashes and provenance. Never replace an input image with a render of the candidate answer.
- `gold_approved:false` means candidate; self-score 1.0 does NOT establish gold quality.
- `final_pass:null` means no calibrated overall decision. Do not report it as pass or fail.
- Tests: `python -m unittest discover -s tests -v`. Stdlib-only SVG: `python -S -m unittest discover -s tests -p test_svg.py -v` (render test may skip).
- Never compare old HTML scores numerically with SVG scores as if they measured the same target.
- The repository contains local uncommitted work. Do not reset unrelated files.
