# Handoff: Linguistic Biomarkers Bug Fix

**Date:** 2026-06-07  
**Branch:** main  
**Commit:** c0f4fe3

---

## Issue

Linguistic biomarkers (lexical diversity / readability) were never appearing in patient briefings or provider summaries, despite the feature being fully implemented.

## Root Cause

`compute_lexical_diversity()` and `compute_readability()` in `database.py` both require **≥10 journal entries** to compute a trend. All three call sites in `app.py` passed the briefing's `days` window (default: 14 days) directly to these functions. A typical patient does not have 10 journal entries in 14 days, so every call returned `trend: 'insufficient_data'` and the section was silently dropped from all outputs.

## Fix

All three call sites in `app.py` updated to use `max(days, 30)`:

| Route | Line | Before | After |
|---|---|---|---|
| Patient briefing (`/api/patient/summary`) | ~1862 | `days=days` | `days=max(days, 30)` |
| Provider summary (Mode C) | ~1114 | `days=days` | `days=max(days, 30)` |
| Fallback provider brief | ~2796 | `days=summary_days` | `days=max(summary_days, 30)` |

This is consistent with how `get_what_worked_patterns()` already handled the same problem: `days=max(days, 60)`.

## Behavior After Fix

- Patients with ≥10 journal entries in the past 30 days will now see a one-sentence linguistic observation woven into the "What stood out" section of their briefing — **only** when TTR delta ≥ 0.10 or FK grade delta ≥ 2.0 (i.e., trend is `improving` or `declining`, not `stable`).
- Providers will see a **Linguistic Patterns** subsection under Qualitative Themes in Mode C summaries when the same thresholds are met.
- Stable trends continue to be omitted (correct per CLAUDE.md §25).

## What Was NOT Changed

- The 10-entry minimum in `compute_lexical_diversity` / `compute_readability` — intentional per CLAUDE.md §25.
- The TTR delta threshold (0.10) and FK grade threshold (2.0) — intentional.
- Session/audio speech features remain provider-only (Mode C/D) per CLAUDE.md §24. The patient briefing correctly suppresses clinical speech observations and shows at most one phrase acknowledging the provider has session notes.

## Files Changed

- `app.py` — 3 lines changed (6 insertions, 6 deletions net)

## Still Needs Push

The commit was created locally but the sandbox couldn't push due to a proxy restriction. Run from your machine:

```bash
cd ~/cognasync-mvp && git push
```
