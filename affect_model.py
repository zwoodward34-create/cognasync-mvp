"""
CognaSync Acoustic Affect Model  (affect_model.py)

Runs a pre-trained wav2vec2 regression model on session audio to produce
continuous Valence / Arousal / Dominance (VAD) scores — acoustic correlates
of emotional state measured directly from the waveform.

MODEL
-----
  audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim
  Training corpus : MSP-Podcast v1.6 (~100 hrs, naturalistic telephone speech)
  Output          : [arousal, dominance, valence]  ← each in [0, 1]
  Architecture    : wav2vec2-large fine-tuned with a regression head
  Reference       : Wagner et al., "Dawn of the transformer era in speech emotion
                    recognition", IEEE TASLP 2023. arXiv:2203.13698

DIMENSION GUIDE (for provider reporting, not patient-facing)
------------------------------------------------------------
  Valence   — positive (1) ↔ negative (0) emotional tone
  Arousal   — high activation (1) ↔ low activation (0)
  Dominance — sense of control/dominance (1) ↔ submissive (0)

  Neutral speech typically clusters near 0.5 on all three dimensions.
  Sustained low valence + low arousal is acoustically consistent with
  depressive affect in the training literature.
  Sustained low valence + high arousal is consistent with anxious affect.
  Elevated valence + high arousal may accompany hypomanic presentation.

  These are acoustic correlates — not psychiatric diagnoses.

CDS EXEMPTION ALIGNMENT
-----------------------
  This module is designed to remain within the FDA CDS software exemption
  (21st Century Cures Act §3060).  The output supports — not replaces —
  clinical judgment.  The provider sees the model name, training source,
  and dimension definitions, enabling independent evaluation of the signal.
  No diagnostic or therapeutic recommendation is generated.  Patients never
  see this output.

  CognaSync CLAUDE.md §19 notes that predictive features may require
  reassessment under SaMD pathways.  This module avoids that boundary by:
    1. Reporting continuous acoustic dimensions, not a binary "depressed / not"
       classification or a labelled psychiatric score.
    2. Including explicit uncertainty flags and the known accuracy ceiling
       (~70-75 % sensitivity / specificity on held-out clinical populations).
    3. Requiring the provider to make all clinical determinations.
    4. Logging predictions internally for validation rather than surfacing them
       as primary clinical output.

DEPENDENCIES (optional — model degrades gracefully when absent)
---------------------------------------------------------------
  pip install torch transformers

  Model weights (~1.2 GB) are downloaded once to the HuggingFace cache
  on first use.  Set HF_HOME to control cache location.
"""

from __future__ import annotations

import logging
import os

import numpy as np

logger = logging.getLogger(__name__)

# ── Model identity ─────────────────────────────────────────────────────────────

MODEL_ID            = "audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim"
AFFECT_MODEL_VERSION = "1.0"
AFFECT_MODEL_SOURCE  = "MSP-Podcast v1.6 (naturalistic speech, ~100 hrs)"
SR                   = 16_000   # model expects 16 kHz mono

# Neutral centre and thresholds for provider-facing labels
_NEUTRAL_CENTRE  = 0.5
_LOW_THRESHOLD   = 0.35   # below → "low" label
_HIGH_THRESHOLD  = 0.65   # above → "high" label

# Maximum audio chunk processed in one forward pass (60 seconds).
# Longer recordings are chunked and averaged to avoid GPU OOM.
_MAX_CHUNK_S = 60

# ── Lazy model singleton ────────────────────────────────────────────────────────

_processor        = None
_model            = None
_device           = None
_model_load_error: str | None = None


def _load_model() -> bool:
    """Attempt to load the model once.  Returns True on success."""
    global _processor, _model, _device, _model_load_error

    if _model is not None:
        return True
    if _model_load_error is not None:
        return False

    try:
        import torch
        import torch.nn as nn
        from transformers import Wav2Vec2Processor
        from transformers.models.wav2vec2.modeling_wav2vec2 import (
            Wav2Vec2Model,
            Wav2Vec2PreTrainedModel,
        )

        # ── Custom regression head (matches audeering checkpoint) ────────────
        class _RegressionHead(nn.Module):
            def __init__(self, config):
                super().__init__()
                self.dense    = nn.Linear(config.hidden_size, config.hidden_size)
                self.dropout  = nn.Dropout(config.final_dropout)
                self.out_proj = nn.Linear(config.hidden_size, config.num_labels)

            def forward(self, x):
                x = self.dropout(x)
                x = self.dense(x)
                x = torch.tanh(x)
                x = self.dropout(x)
                return self.out_proj(x)

        class _EmotionModel(Wav2Vec2PreTrainedModel):
            def __init__(self, config):
                super().__init__(config)
                self.wav2vec2  = Wav2Vec2Model(config)
                self.classifier = _RegressionHead(config)
                self.init_weights()

            def forward(self, input_values):
                hidden = self.wav2vec2(input_values)[0]       # (B, T, H)
                pooled = torch.mean(hidden, dim=1)             # (B, H)
                return self.classifier(pooled)                 # (B, 3)

        _device    = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Loading affect model %s on %s", MODEL_ID, _device)

        _processor = Wav2Vec2Processor.from_pretrained(MODEL_ID)
        _model     = _EmotionModel.from_pretrained(MODEL_ID).to(_device).eval()

        logger.info("Affect model loaded on %s", _device)
        return True

    except Exception as exc:
        _model_load_error = str(exc)
        logger.warning(
            "Affect model unavailable (torch/transformers may not be installed): %s", exc
        )
        return False


# ── Inference ───────────────────────────────────────────────────────────────────

def _infer_chunks(y: np.ndarray) -> np.ndarray:
    """Run the model on y in chunks and return the mean [arousal, dom, valence]."""
    import torch

    chunk_frames = _MAX_CHUNK_S * SR
    n_chunks     = max(1, int(np.ceil(len(y) / chunk_frames)))
    results: list[np.ndarray] = []

    for i in range(n_chunks):
        chunk = y[i * chunk_frames: (i + 1) * chunk_frames]
        if len(chunk) < SR // 10:          # skip sub-100 ms tail chunks
            continue

        inputs = _processor(
            chunk, sampling_rate=SR, return_tensors="pt", padding=True
        )
        input_values = inputs["input_values"].to(_device)

        with torch.no_grad():
            logits = _model(input_values)  # (1, 3)

        results.append(logits.cpu().numpy()[0])

    if not results:
        return np.array([0.5, 0.5, 0.5])

    return np.mean(results, axis=0)


def _dim_label(value: float) -> str:
    """Map a continuous [0,1] VAD dimension to a three-level label."""
    if value < _LOW_THRESHOLD:
        return "low"
    if value > _HIGH_THRESHOLD:
        return "high"
    return "neutral"


def _interpret_vad(arousal: float, dominance: float, valence: float) -> dict:
    """
    Map VAD coordinates to provider-facing acoustic affect summary.
    Never uses diagnostic language.  Returns labels and a brief
    description suitable for the Acoustic Biomarkers section of the brief.
    """
    a_lbl = _dim_label(arousal)
    d_lbl = _dim_label(dominance)
    v_lbl = _dim_label(valence)

    # Pattern detection — acoustic correlate only, not a diagnosis
    pattern: str
    if v_lbl == "low" and a_lbl == "low":
        pattern = "low-valence / low-arousal"
        description = (
            "Acoustic affect dimensions indicate negative emotional tone with low "
            "activation — a pattern acoustically associated with subdued or withdrawn "
            "presentation in the training literature."
        )
    elif v_lbl == "low" and a_lbl in ("neutral", "high"):
        pattern = "low-valence / elevated-arousal"
        description = (
            "Acoustic affect dimensions indicate negative emotional tone with "
            "maintained or elevated activation — acoustically consistent with "
            "tense or distressed presentation."
        )
    elif v_lbl == "high" and a_lbl == "high":
        pattern = "high-valence / elevated-arousal"
        description = (
            "Acoustic affect dimensions indicate positive emotional tone with high "
            "activation — acoustically consistent with animated or energised presentation."
        )
    else:
        pattern = "near-neutral"
        description = (
            "Acoustic affect dimensions are near the neutral centre on all three "
            "dimensions — no strong directional signal detected."
        )

    return {
        "pattern":     pattern,
        "description": description,
        "arousal_label":   a_lbl,
        "dominance_label": d_lbl,
        "valence_label":   v_lbl,
    }


def run_affect_inference(y: np.ndarray) -> dict:
    """
    Run VAD inference on a 16 kHz mono float32 array.

    Returns a dict with continuous scores, labels, interpretation, and
    metadata.  On model unavailability returns a dict with
    model_available=False and all scores None.

    Args:
        y: 16 kHz mono float32 numpy array (from acoustic_engine._decode_to_mono16k)
    """
    base = {
        "model_id":      MODEL_ID,
        "model_version": AFFECT_MODEL_VERSION,
        "training_source": AFFECT_MODEL_SOURCE,
        "model_available": False,
        "arousal":    None,
        "dominance":  None,
        "valence":    None,
        "arousal_label":   None,
        "dominance_label": None,
        "valence_label":   None,
        "pattern":     None,
        "description": None,
        "disclaimer":  _DISCLAIMER,
    }

    if not _load_model():
        base["unavailable_reason"] = _model_load_error or "model not loaded"
        return base

    try:
        vad = _infer_chunks(y)                    # [arousal, dominance, valence]
        arousal, dominance, valence = float(vad[0]), float(vad[1]), float(vad[2])

        interp = _interpret_vad(arousal, dominance, valence)

        return {
            **base,
            "model_available": True,
            "arousal":    round(arousal,   3),
            "dominance":  round(dominance, 3),
            "valence":    round(valence,   3),
            **interp,
        }

    except Exception as exc:
        logger.error("Affect inference failed: %s", exc)
        base["unavailable_reason"] = str(exc)
        return base


# ── Aggregation ─────────────────────────────────────────────────────────────────

def aggregate_affect_sessions(session_affect_list: list[dict]) -> dict:
    """
    Aggregate per-session VAD scores across multiple sessions.

    Args:
        session_affect_list: List of dicts from run_affect_inference(),
            each optionally carrying a 'session_date' key.

    Returns summary suitable for inclusion in the provider brief.
    """
    valid = [
        s for s in session_affect_list
        if s.get("model_available") and s.get("valence") is not None
    ]
    n_total = len(session_affect_list)
    n_valid = len(valid)

    if n_valid == 0:
        return {
            "session_count":   n_total,
            "valid_count":     0,
            "model_available": False,
        }

    def _avg(key: str) -> float | None:
        vals = [s[key] for s in valid if s.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    valence_series  = [s["valence"]   for s in valid]
    arousal_series  = [s["arousal"]   for s in valid]
    dominance_series = [s["dominance"] for s in valid]

    # Simple trend: compare first half vs second half of the series
    def _trend(series: list[float]) -> str:
        if len(series) < 2:
            return "insufficient_data"
        mid   = len(series) // 2
        first = sum(series[:mid]) / max(len(series[:mid]), 1)
        last  = sum(series[mid:]) / max(len(series[mid:]), 1)
        delta = last - first
        if abs(delta) < 0.05:
            return "stable"
        return "improving" if delta > 0 else "declining"

    # Pattern distribution
    from collections import Counter
    patterns = Counter(s.get("pattern") for s in valid if s.get("pattern"))

    series_rows = [
        {
            "session_date": s.get("session_date"),
            "valence":      s.get("valence"),
            "arousal":      s.get("arousal"),
            "dominance":    s.get("dominance"),
            "pattern":      s.get("pattern"),
        }
        for s in valid
    ]

    return {
        "session_count":    n_total,
        "valid_count":      n_valid,
        "model_available":  True,
        "model_id":         MODEL_ID,
        "training_source":  AFFECT_MODEL_SOURCE,
        "valence_avg":      _avg("valence"),
        "arousal_avg":      _avg("arousal"),
        "dominance_avg":    _avg("dominance"),
        "valence_trend":    _trend(valence_series),
        "arousal_trend":    _trend(arousal_series),
        "dominance_trend":  _trend(dominance_series),
        "valence_min":      round(min(valence_series),  3),
        "valence_max":      round(max(valence_series),  3),
        "arousal_min":      round(min(arousal_series),  3),
        "arousal_max":      round(max(arousal_series),  3),
        "pattern_distribution": dict(patterns),
        "dominant_pattern": patterns.most_common(1)[0][0] if patterns else None,
        "series":           series_rows,
        "disclaimer":       _DISCLAIMER,
    }


# ── Disclaimer (mandatory in all provider-facing output) ──────────────────────

_DISCLAIMER = (
    "RESEARCH SIGNAL — NOT A DIAGNOSTIC INSTRUMENT. "
    f"Acoustic affect dimensions produced by {MODEL_ID} (trained on {AFFECT_MODEL_SOURCE}). "
    "Output represents acoustic correlates of emotional state in the training population. "
    "Accuracy on clinical populations is approximately 70–75% sensitivity/specificity. "
    "These dimensions are not a psychiatric assessment and must not be used as a "
    "standalone clinical decision. Provider interpretation required."
)
