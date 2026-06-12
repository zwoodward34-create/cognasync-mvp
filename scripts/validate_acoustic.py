#!/usr/bin/env python3
"""Acoustic feature validation harness.

Accepts a CSV of (audio_path, ground_truth_label) pairs, runs each file through
the full acoustic extraction + vocabulary-mapping pipeline, and reports per-feature
accuracy and a confusion matrix. Designed to be run once labelled reference audio
exists — the harness itself is pure infrastructure.

CSV format (header required):
    audio_path,speech_rate,prosody,pauses,arousal,vocal_affect,clinical_pattern_type

Any column after audio_path can be left blank to skip that feature.

Usage:
    python scripts/validate_acoustic.py labels.csv [--baseline-dir DIR] [--json out.json]

Output:
    Per-feature: accuracy, precision, recall, F1 (macro), and a full confusion matrix.
    Summary line showing overall accuracy across all non-blank ground-truth fields.
    Optionally saves structured JSON for trend comparisons across model versions.

This harness is the missing piece that converts every future threshold or model
change from "sounds plausible" to "moved accuracy from X to Y."
"""

import argparse
import csv
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# --- feature columns we validate -------------------------------------------
FEATURE_COLS = [
    "speech_rate",
    "prosody",
    "pauses",
    "arousal",
    "vocal_affect",
    "clinical_pattern_type",
]


# --- thin imports at load time (heavy deps only when actually processing) ---

def _load_extractor():
    """Import acoustic pipeline; print a clear error if deps are missing."""
    try:
        from acoustic_engine import extract_acoustic_features, map_features_to_vocabulary
        return extract_acoustic_features, map_features_to_vocabulary
    except ImportError as e:
        print(f"ERROR: could not import acoustic_engine — {e}")
        print("Install dependencies: pip install librosa parselmouth scipy numpy")
        sys.exit(1)


def _load_baseline(baseline_dir: Optional[str], patient_id: str) -> Optional[dict]:
    """Load a stored patient baseline JSON if available."""
    if not baseline_dir:
        return None
    p = Path(baseline_dir) / f"{patient_id}.json"
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)


# --- metrics -----------------------------------------------------------------

def _confusion(true_labels: list, pred_labels: list) -> dict:
    """Build a {true → {pred → count}} confusion matrix."""
    classes = sorted(set(true_labels) | set(pred_labels))
    matrix: dict[str, dict[str, int]] = {c: {d: 0 for d in classes} for c in classes}
    for t, p in zip(true_labels, pred_labels):
        matrix[t][p] += 1
    return matrix


def _f1_macro(true_labels: list, pred_labels: list) -> float:
    """Compute macro-averaged F1 across all classes."""
    classes = sorted(set(true_labels))
    f1s = []
    for cls in classes:
        tp = sum(t == cls and p == cls for t, p in zip(true_labels, pred_labels))
        fp = sum(t != cls and p == cls for t, p in zip(true_labels, pred_labels))
        fn = sum(t == cls and p != cls for t, p in zip(true_labels, pred_labels))
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0)
    return round(sum(f1s) / len(f1s), 4) if f1s else 0.0


def _report_feature(feature: str, true_labels: list, pred_labels: list) -> dict:
    n       = len(true_labels)
    correct = sum(t == p for t, p in zip(true_labels, pred_labels))
    acc     = round(correct / n, 4) if n > 0 else None
    f1      = _f1_macro(true_labels, pred_labels)
    cm      = _confusion(true_labels, pred_labels)
    return {
        "feature":        feature,
        "n":              n,
        "accuracy":       acc,
        "f1_macro":       f1,
        "confusion":      cm,
        "errors": [
            {"audio": audio, "true": t, "pred": p}
            for audio, t, p in zip(
                [r["audio_path"] for r in _rows_cache],
                true_labels, pred_labels
            )
            if t != p
        ],
    }


_rows_cache: list[dict] = []


# --- main pipeline -----------------------------------------------------------

def run(csv_path: str, baseline_dir: Optional[str], json_out: Optional[str]) -> int:
    extract_acoustic_features, map_features_to_vocabulary = _load_extractor()

    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("ERROR: CSV is empty or has no data rows.")
        return 1

    missing_cols = [c for c in ["audio_path"] + FEATURE_COLS if c not in rows[0]]
    unknown = [c for c in missing_cols if c not in FEATURE_COLS]
    if unknown:
        print(f"ERROR: required column 'audio_path' missing from CSV.")
        return 1
    # Feature columns are optional; just warn if absent.
    absent_feats = [c for c in FEATURE_COLS if c not in rows[0]]
    if absent_feats:
        print(f"NOTE: feature columns not in CSV (will be skipped): {absent_feats}")

    global _rows_cache
    _rows_cache = rows

    # Accumulate (true, pred) pairs per feature.
    trues: dict[str, list] = {f: [] for f in FEATURE_COLS}
    preds: dict[str, list] = {f: [] for f in FEATURE_COLS}

    errors: list[dict] = []
    skipped = 0

    for i, row in enumerate(rows):
        audio_path = row["audio_path"].strip()
        patient_id = row.get("patient_id", "unknown").strip()

        if not os.path.exists(audio_path):
            print(f"[{i+1}/{len(rows)}] SKIP (not found): {audio_path}")
            skipped += 1
            continue

        print(f"[{i+1}/{len(rows)}] Processing: {audio_path}", end=" ... ", flush=True)

        try:
            # Run extraction (subprocess isolated inside acoustic_engine)
            raw = extract_acoustic_features(audio_path)
            baseline = _load_baseline(baseline_dir, patient_id)
            vocab = map_features_to_vocabulary(raw, baseline=baseline)

            for feat in FEATURE_COLS:
                gt = row.get(feat, "").strip()
                if not gt:
                    continue
                predicted = vocab.get(feat) or ""
                trues[feat].append(gt)
                preds[feat].append(predicted)

            print("OK")

        except Exception as exc:
            print(f"ERROR: {exc}")
            errors.append({"audio_path": audio_path, "error": str(exc)})

    print()

    # --- report ---------------------------------------------------------------
    results = {}
    overall_correct = 0
    overall_total   = 0

    for feat in FEATURE_COLS:
        if not trues[feat]:
            continue
        rep = _report_feature(feat, trues[feat], preds[feat])
        results[feat] = rep
        n_correct = sum(t == p for t, p in zip(trues[feat], preds[feat]))
        overall_correct += n_correct
        overall_total   += rep["n"]

        print(f"── {feat} ──")
        print(f"   n={rep['n']}  accuracy={rep['accuracy']:.1%}  F1_macro={rep['f1_macro']:.3f}")
        # Show confusion only when there are errors
        if rep["errors"]:
            cm = rep["confusion"]
            classes = sorted(cm)
            header = "       " + "  ".join(f"{c:>10}" for c in classes)
            print("   Confusion (rows=true, cols=pred):")
            print("   " + header)
            for c in classes:
                row_str = "  ".join(f"{cm[c].get(d,0):>10}" for d in classes)
                print(f"   {c:>10}  {row_str}")
        print()

    if overall_total > 0:
        overall_acc = round(overall_correct / overall_total, 4)
        print(f"Overall accuracy across all features: {overall_acc:.1%}  "
              f"({overall_correct}/{overall_total} correct)")

    if skipped:
        print(f"\nSkipped {skipped} rows (audio files not found).")
    if errors:
        print(f"Extraction errors on {len(errors)} files:")
        for e in errors:
            print(f"  {e['audio_path']}: {e['error']}")

    # Structured JSON output for trend comparison across model versions
    if json_out:
        import acoustic_engine
        output = {
            "harness_version": "1.0",
            "extractor_version": getattr(acoustic_engine, "EXTRACTOR_VERSION", "unknown"),
            "csv": csv_path,
            "n_files": len(rows),
            "skipped": skipped,
            "extraction_errors": len(errors),
            "overall_accuracy": overall_correct / overall_total if overall_total else None,
            "features": results,
        }
        # Strip non-serialisable numpy types
        def _jsonify(obj):
            if isinstance(obj, dict):
                return {k: _jsonify(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_jsonify(v) for v in obj]
            if hasattr(obj, "item"):          # numpy scalar
                return obj.item()
            return obj

        with open(json_out, "w") as f:
            json.dump(_jsonify(output), f, indent=2)
        print(f"\nJSON results written to {json_out}")

    return 0 if not errors else 2


def _make_sample_csv(out_path: str) -> None:
    """Write a sample CSV template to out_path."""
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["audio_path", "patient_id"] + FEATURE_COLS)
        w.writerow([
            "/path/to/recording.wav", "P001",
            "normal", "normal", "normal", "normal", "normal", "none_detected",
        ])
        w.writerow([
            "/path/to/another.wav", "P002",
            "slowed", "flat", "increased", "low", "flat", "depressive",
        ])
    print(f"Sample CSV written to {out_path}")
    print("Columns: audio_path, patient_id, " + ", ".join(FEATURE_COLS))
    print("Leave any feature column blank to skip it for that row.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Validate acoustic extractor against labelled reference audio.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("csv", nargs="?", help="Path to labels CSV")
    parser.add_argument(
        "--baseline-dir",
        metavar="DIR",
        help="Directory of per-patient baseline JSON files (optional)",
    )
    parser.add_argument(
        "--json",
        metavar="FILE",
        help="Save structured JSON results to this path",
    )
    parser.add_argument(
        "--sample-csv",
        metavar="FILE",
        help="Write a sample CSV template and exit",
    )
    args = parser.parse_args()

    if args.sample_csv:
        _make_sample_csv(args.sample_csv)
        sys.exit(0)

    if not args.csv:
        parser.print_help()
        sys.exit(1)

    sys.exit(run(args.csv, args.baseline_dir, args.json))
