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

- Current output direction: standalone SVG. Top-level commands are SVG: `python -m formgen make|bench|report|score|validate|stats|render|selftest`
  `python -m formgen harness ...` = multi-endpoint P1/P2 generation; `python -m formgen svg ...` = experimental v2/v3 diagnostic CLI (formgen/svg_cli.py).
- Layout: formgen/svg.py (contract, v1 score, render), make.py (THE generation function; bench, svg_cli and harness import it), bench.py (runs, aggregation, PASS_RULE), selftest.py, llm.py, match.py (shared matching/text),
  svg_eval_v2.py / svg_eval_v3.py / svg_cli.py (diagnostic scorers), harness.py / harness_refine.py.
- There are two bench paths (bench.py pass-rate table; svg_cli bench diagnostics). Do not add a third; extend bench.py for anything that must appear in the pass-rate table.
- Several agents push to main. `git pull --rebase` (or merge) before pushing; never force-push; do not rename public functions other modules import (e.g. svg.tag, svg.parse, svg.score, svg.render, make.make) without grepping the repo.
- HTML is legacy under formgen/html/ and `python -m formgen html ...`; docs in docs/legacy/. Do not silently change its score meaning.
- Pass/fail exists only in bench aggregation as a provisional, versioned PASS_RULE; scores keep `final_pass:null`. Change the rule in one place and re-aggregate with `report`.
- After any scorer change run `python -m formgen selftest`; it must stay all-expected.
- Target runtime is an internet-disconnected internal network with limited pip installation.
  Never make Playwright/Chromium, an online font fetch, or a browser download a default runtime dependency.
- Core SVG generation/validation/scoring must work with `python -S`; rendering may lazily import `resvg_py`.
- Record contract or metric changes in `docs/DECISIONS.md` and update `docs/STATE.json` in the same change.
- Preserve official source PDF/image hashes and provenance. Never replace an input image with a render of the candidate answer.
- `gold_approved:false` means candidate; self-score 1.0 does NOT establish gold quality.
- `final_pass:null` means no calibrated overall decision. Do not report it as pass or fail.
- Tests: `python -m unittest discover -s tests -v`. Stdlib-only: `python -S -m unittest tests.test_svg tests.test_bench -v` (render test may skip).
- Never compare old HTML scores numerically with SVG scores as if they measured the same target.
- User-facing docs (README.md, bench/README.md, docs/DIFFICULTY_GUIDE.md) are Korean; keep them in sync with behavior changes.
