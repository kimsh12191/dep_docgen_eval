"""SVG scorer v2: geometry-first field matching and optional raster diagnostics.

All results are uncalibrated diagnostics. No pass/fail decision is inferred.
Core scoring uses stdlib; raster diagnostics require resvg-py and Pillow.
"""
from __future__ import annotations

import math
from pathlib import Path
from xml.etree import ElementTree as ET

from . import svg
from .match import hungarian, label_sim, norm_label

VERSION = "svg-eval-v2"
MATCH_IOU = 0.10
MATCH_CENTER_DISTANCE = 0.035
LOCATED_IOU = 0.50
LABEL_THRESHOLD = 0.80
TEXT_POSITION_DISTANCE = 0.025


def _f1(hits, n_ref, n_pred):
    return round(2 * hits / (n_ref + n_pred), 4) if n_ref + n_pred else 1.0


def _norm_box(field, document):
    x, y, w, h = field["bbox"]
    return (x / document["width"], y / document["height"],
            w / document["width"], h / document["height"])


def _iou(a, b):
    x, y, w, h = a
    u, v, s, t = b
    overlap = max(0, min(x + w, u + s) - max(x, u)) * max(0, min(y + h, v + t) - max(y, v))
    union = w * h + s * t - overlap
    return overlap / union if union > 0 else 0.0


def _distance(a, b):
    return math.hypot(a[0] + a[2] / 2 - b[0] - b[2] / 2,
                      a[1] + a[3] / 2 - b[1] - b[3] / 2)


def score_fields(reference, prediction):
    """Match geometrically, then score detection, labels, types and location separately."""
    refs, preds = reference["fields"], prediction["fields"]
    a = [_norm_box(f, reference) for f in refs]
    b = [_norm_box(f, prediction) for f in preds] if prediction["width"] and prediction["height"] else []
    costs = []
    for i, r in enumerate(a):
        row = []
        for j, p in enumerate(b):
            overlap, distance = _iou(r, p), _distance(r, p)
            if overlap < MATCH_IOU and distance > MATCH_CENTER_DISTANCE:
                row.append(1e6)
            else:
                row.append(1 - overlap + 2 * distance + 0.15 * (1 - label_sim(refs[i]["label"], preds[j]["label"])))
        costs.append(row)
    pairs = [(i, j) for i, j in hungarian(costs) if costs[i][j] < 1e6] if costs and b else []
    matched_ref, matched_pred = {i for i, _ in pairs}, {j for _, j in pairs}
    labels = {(i, j) for i, j in pairs if label_sim(refs[i]["label"], preds[j]["label"]) >= LABEL_THRESHOLD}
    types = {(i, j) for i, j in pairs if refs[i]["type"] == preds[j]["type"]}
    check_pairs = {(i, j) for i, j in pairs if refs[i]["type"] == preds[j]["type"] == "checkbox"}
    options = {(i, j) for i, j in check_pairs if set(refs[i]["options"]) == set(preds[j]["options"])}
    semantic = {p for p in labels if p in types and (refs[p[0]]["type"] != "checkbox" or p in options)}
    located = {(i, j) for i, j in pairs if _iou(a[i], b[j]) >= LOCATED_IOU}
    return {
        "fields_gt": len(refs), "fields_pred": len(preds), "matched": len(pairs),
        "field_detection_f1": _f1(len(pairs), len(refs), len(preds)),
        "field_label_f1": _f1(len(labels), len(refs), len(preds)),
        "field_type_f1": _f1(len(types), len(refs), len(preds)),
        "field_semantic_f1": _f1(len(semantic), len(refs), len(preds)),
        "field_located_f1": _f1(len(located), len(refs), len(preds)),
        "field_located_semantic_f1": _f1(len(located & semantic), len(refs), len(preds)),
        "field_label_accuracy_matched": round(len(labels) / len(pairs), 4) if pairs else None,
        "field_type_accuracy_matched": round(len(types) / len(pairs), 4) if pairs else None,
        "checkbox_options_accuracy_matched": round(len(options) / len(check_pairs), 4) if check_pairs else None,
        "field_iou_over_gt": round(sum(_iou(a[i], b[j]) for i, j in pairs) / len(refs), 4) if refs else None,
        "missing_fields": [refs[i]["key"] for i in range(len(refs)) if i not in matched_ref],
        "extra_fields": [preds[j]["key"] for j in range(len(preds)) if j not in matched_pred],
        "matches": [{"reference": refs[i]["key"], "prediction": preds[j]["key"],
                     "iou": round(_iou(a[i], b[j]), 4),
                     "label_similarity": round(label_sim(refs[i]["label"], preds[j]["label"]), 4),
                     "type_equal": refs[i]["type"] == preds[j]["type"]} for i, j in pairs],
        "matching_rule": {"min_iou": MATCH_IOU, "max_center_distance": MATCH_CENTER_DISTANCE,
                          "located_iou": LOCATED_IOU, "label_threshold": LABEL_THRESHOLD},
    }


def _anchors(source, dimensions):
    """Parse explicit SVG text anchors, omitting transformed/implicit positions."""
    if not dimensions["width"] or not dimensions["height"]:
        return []
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return []
    found = []
    def walk(node, transformed=False):
        transformed = transformed or "transform" in node.attrib
        if svg.tag(node) == "text" and not transformed:
            try:
                x = float(node.get("x", "").replace(",", " ").split()[0])
                y = float(node.get("y", "").replace(",", " ").split()[0])
                label = norm_label("".join(node.itertext()))
                if label and math.isfinite(x) and math.isfinite(y):
                    found.append((label, x / dimensions["width"], y / dimensions["height"]))
            except (IndexError, ValueError):
                pass
        for child in node:
            walk(child, transformed)
    walk(root)
    return found


def score_text_positions(reference, prediction, a, b):
    refs, preds = _anchors(reference, a), _anchors(prediction, b)
    costs = []
    for label, x, y in refs:
        costs.append([(1 - label_sim(label, other)) + math.hypot(x - u, y - v)
                      if label_sim(label, other) >= LABEL_THRESHOLD else 1e6
                      for other, u, v in preds])
    pairs = [(i, j) for i, j in hungarian(costs) if costs[i][j] < 1e6] if refs and preds else []
    located = [(i, j) for i, j in pairs
               if math.hypot(refs[i][1] - preds[j][1], refs[i][2] - preds[j][2]) <= TEXT_POSITION_DISTANCE]
    return {"reference_anchors": len(refs), "prediction_anchors": len(preds),
            "text_anchor_f1": _f1(len(pairs), len(refs), len(preds)) if refs else None,
            "text_located_f1": _f1(len(located), len(refs), len(preds)) if refs else None,
            "position_tolerance": TEXT_POSITION_DISTANCE,
            "limitations": "Glyph paths, nested transforms, tspan-only coordinates and implicit positions are not evaluated"}


def _foreground(image):
    from PIL import ImageOps
    return ImageOps.grayscale(image).point(lambda p: 255 if p < 230 else 0).convert("L")


def _edge(mask):
    from PIL import ImageChops, ImageFilter
    return ImageChops.difference(mask, mask.filter(ImageFilter.MinFilter(3)))


def _compare_masks(gold, predicted, tolerance):
    from PIL import ImageChops, ImageFilter
    kernel = 2 * tolerance + 1
    dilated_gold = gold.filter(ImageFilter.MaxFilter(kernel)) if tolerance else gold
    dilated_pred = predicted.filter(ImageFilter.MaxFilter(kernel)) if tolerance else predicted
    n_gold, n_pred = gold.histogram()[255], predicted.histogram()[255]
    tp_pred = ImageChops.multiply(predicted, dilated_gold).histogram()[255]
    tp_gold = ImageChops.multiply(gold, dilated_pred).histogram()[255]
    precision = tp_pred / n_pred if n_pred else (1.0 if not n_gold else 0.0)
    recall = tp_gold / n_gold if n_gold else (1.0 if not n_pred else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4), "gold_ink_pixels": n_gold, "pred_ink_pixels": n_pred}


def compare_rasters(reference_image, prediction_image, tolerance=2):
    """Compare foreground and edges (not the mostly white backgrounds)."""
    if not 0 <= tolerance <= 8:
        raise ValueError("tolerance out of range 0..8")
    a, b = reference_image, prediction_image
    if a.size != b.size:
        ratio_a, ratio_b = a.width / a.height, b.width / b.height
        if abs(ratio_a / ratio_b - 1) > 0.02:
            return {"status": "aspect_mismatch", "gold_size": a.size, "pred_size": b.size}
        from PIL import Image
        b = b.resize(a.size, Image.Resampling.LANCZOS)
    x, y = _foreground(a), _foreground(b)
    return {"status": "ok", "ink": _compare_masks(x, y, tolerance),
            "edge": _compare_masks(_edge(x), _edge(y), tolerance),
            "tolerance_px": tolerance, "gold_size": a.size, "pred_size": prediction_image.size,
            "normalized_to_gold_size": a.size != prediction_image.size,
            "note": "Diagnostic only; font, registration and fixed-value differences affect the score"}


def evaluate(reference, prediction, *, source_image=None, output_dir=None,
             font_files=None, visual=False):
    """Preserve v1 diagnostics while separating recognition, geometry and rendering."""
    legacy = svg.score(reference, prediction)
    a, b = svg.parse(reference), svg.parse(prediction)
    result = {"version": VERSION, "valid": legacy["valid"], "issues": legacy["issues"],
              "recognition": {k: legacy[k] for k in ("text_f1", "text_p", "text_r")},
              "fields": score_fields(a, b),
              "text_geometry": score_text_positions(reference, prediction, a, b),
              "legacy_svg_v1": legacy, "visual": {"status": "not_requested"},
              "final_pass": None, "status": "diagnostic_uncalibrated"}
    if not visual:
        return result
    if not output_dir:
        result["visual"] = {"status": "missing_output_dir"}
        return result
    if not source_image:
        result["visual"] = {"status": "missing_source_image"}
        return result
    if not b["valid"]:
        result["visual"] = {"status": "invalid_prediction"}
        return result
    try:
        from PIL import Image
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        ref_png, pred_png = output / "reference.svg.png", output / "prediction.svg.png"
        fonts = font_files or []
        svg.render(reference, ref_png, fonts)
        svg.render(prediction, pred_png, fonts)
        with Image.open(source_image) as img, Image.open(ref_png) as ref, Image.open(pred_png) as pred:
            result["visual"] = {
                "status": "ok",
                "prediction_vs_source": compare_rasters(img, pred),
                "reference_vs_source": compare_rasters(img, ref),
                "prediction_vs_reference": compare_rasters(ref, pred),
                "font_mode": "explicit" if fonts else "system_unpinned",
                "reference_png": str(ref_png), "prediction_png": str(pred_png)}
    except (ImportError, OSError, ValueError, RuntimeError) as e:
        result["visual"] = {"status": "unavailable", "reason": (type(e).__name__ + ": " + str(e))[:300]}
    return result
