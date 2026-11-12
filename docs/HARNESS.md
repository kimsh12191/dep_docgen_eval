# SVG Generation Harness P1/P2 (experimental)

The harness runs many already-served **vLLM OpenAI-compatible** endpoints through a common image -> SVG path. No other OCR/agent services or training steps are needed.

## Flow

```
images/ + model config
       -> [each model x image x repeat]
       -> P1: same svg_v1 prompt -> /v1/chat/completions -> round_0/out.svg
       -> XML + restricted-SVG validation
       -> (P2 enabled) render -> masked source comparison -> regional discrepancy report
       -> P2: original image + current render + complete SVG + targeted feedback
       -> rerender/score -> accept only a measured improvement
       -> best.svg + all candidate files + summary.csv
```

If the initial SVG fails validation and P2 is enabled, send the validation issues and the original image for one repair attempt without rendering the invalid SVG. Keep original generation and all failed proposals. At most `max_refinements` P2 calls. Stop on no improvement, regression, invalid revision, or unavailable visual scoring.

## Minimal setup

1. Start independent vLLM servers with image-capable models. Example: `vllm serve /models/MODEL --served-model-name served-a --port 8000` (server options vary by model).
2. Copy `examples/harness_models.json` and set the reachable `/v1` addresses and exact served model names. API keys can only be configured with `api_key_env`.
3. Put documents in a dedicated directory. Supported: PNG/JPEG/WEBP, nested or flat. A `doc_001/image.png` may have adjacent `meta.json` and `table_regions.json`. For a flat `doc_001.png`, use `doc_001.regions.json`.
4. First use `--dry-run` to verify task count. Then `--verify-models` to check `/v1/models`.

```bash
python -m formgen harness generate --config examples/harness_models.json --images bench/official_pilot_v1 --out runs/pilot --dry-run
python -m formgen harness generate --config examples/harness_models.json --images bench/official_pilot_v1 --out runs/pilot --verify-models
python -m formgen harness generate --config examples/harness_models.json --images bench/official_pilot_v1 --out runs/pilot --resume
# Deliberately rerun transport failures only, preserve completed model failures.
python -m formgen harness generate --config examples/harness_models.json --images bench/official_pilot_v1 --out runs/pilot --resume --retry-failed
```

**Generation-only P1:** set `generation.max_refinements: 0`. This requires no renderer dependency. **Self-evaluation P2:** set `max_refinements: 1` or `2` and install the V3 optional requirements (`Pillow` and `resvg_py` or `cairosvg`). Three images are sent when `feedback_include_difference: true`; with one crop pair, 2 more images are sent. Configure the vLLM model's multi-image limit accordingly. The default sends original + rendered image (2 images) to the refiner.

### Configuration

- `models[].id`: local stable alias, not necessarily the model ID
- `models[].model`: exact `served-model-name` appearing at `/v1/models`
- `models[].endpoint`: `http(s)://hostname:port/v1`
- `models[].concurrency`: cap per shared endpoint (conservative minimum across aliases)
- `models[].api_key_env`: optional **environment-variable name**, never the secret itself
- `generation.repeats`: independent runs per model and image
- `generation.max_tokens`: max requested output tokens (P1 and P2)
- `generation.timeout`: vLLM HTTP deadline seconds
- `generation.temperature`: only `0` is currently supported, to preserve the existing `svg_cli.make()` protocol
- `generation.max_refinements`: 0=P1, 1=P2 one attempt, 2=P2 up to two attempts
- `generation.min_improvement`: minimum accepted gain in score points (default 0.25)
- `generation.feedback_crop_pairs`: 0 (2 images), 1 (4 images), 2 (6 images); optionally +1 difference map
- `generation.feedback_include_difference`: include discrepancy image in P2 input (default false)
- `generation.max_svg_chars`: safety limit on embedding prior code in P2 prompt

The experiment fingerprint covers source image bytes, reviewed table manifest bytes, prompt hashes, model/endpoint choice and generation settings. `--resume` rejects a changed fingerprint. Incomplete rounds can be resumed without resending completed requests. Completed, semantically broken SVGs remain *failed samples*, not silently retried; HTTP transport errors can be rerun explicitly with `--retry-failed`.

## Scoring during refinement

**With `table_regions.json`**: use existing V3 exactly: `70% global visual + 30% equally averaged table ROIs`. Invalid/missing ROIs make the score unavailable, not high-scoring.

**Without table annotations**: use global Foreground/Edge F1 as an **uncalibrated `visual_proxy_unannotated`** only for P2 acceptance. It MUST NOT be pooled with calibrated V3 scores; treat this as an engineering heuristic. Original images with filled personal values or stamps require reviewed `ignore_regions` masks to compare fairly to blank forms. Arbitrary images without masks can produce misleading scores.

The scoring is a **diagnostic policy**; neither visual metric nor the 0.25-point margin has been calibrated to human ratings. A model can exploit scores or become worse perceptually even if its metric increases. Inspect candidates before using them in production.

## Output tree

```
runs/pilot/
  run_manifest.json            # no API key values
  summary.json                 # valid SVG rates; mean conditional score
  summary.csv                  # model x document x repeat
  <model-id>/<doc-id>/r000/
    round_0/out.svg            # original P1 preserved
    round_0/raw.txt
    round_0/make.json
    round_0/visual/{rendered,overlay,difference}.png      # P2 only
    round_0/visual/{assessment,score_v3}.json              # if available
    round_1/out.svg            # optional P2 candidate
    round_1/raw.txt
    round_1/make.json
    round_1/visual/*           # reevaluation diagnostics
    best.svg                   # highest measured valid candidate
    status.json                # selected round, scores, stop reason, tokens
```

`valid_svg` is syntax/contract success, **not a trustworthy document reconstruction pass**. V3 remains separate and uncalibrated. **Do not interpret generation P2 results as independent ablation evidence** until they are compared against P1 and equal-budget resampling on held-out documents, including human visual ratings.

## Testing

`python -m unittest discover -s tests -p 'test_harness_closed_loop.py' -v`

The fake HTTP server tests completion, shared-endpoint concurrency, multi-model runs, repeat, invalid SVG repair, P2 improvement, regression rollback, crop feedback, resume, fingerprint protection, and missing ROI failure. **Real vLLM image support has not been verified yet**; server chat templates / image-count limits can vary.
