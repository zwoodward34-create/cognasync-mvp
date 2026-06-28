#!/usr/bin/env python3
"""
benchmark_transcription.py — CognaSync transcription accuracy harness.

WHY THIS EXISTS
  The voice pipeline ships clinical-adjacent inferences with zero ground-truth
  measurement of transcription accuracy. This harness closes that gap: it runs
  real audio through the actual transcription path and scores the result
  against human-corrected reference transcripts, so accuracy can be *stated*
  instead of asserted. Two numbers matter most:

    1. WER (word error rate)        — overall transcription quality.
    2. Clinical-term recall         — of the medication/clinical terms that
                                      appear in the reference, what fraction did
                                      the transcript get right? This is the
                                      metric the `word_boost` work targets and
                                      the one §16 medication-context detection
                                      depends on. A high overall WER can hide a
                                      catastrophic drug-name miss; this surfaces
                                      it.

HOW TO USE
  1. Build a reference set. For each recording, place two files in --audio-dir
     sharing a base name:
        data/benchmark/session01.m4a      (the audio)
        data/benchmark/session01.txt      (human-corrected transcript)
     Speaker labels in the reference (e.g. "PATIENT: ...") are stripped before
     scoring, so either format works. 15-30 recordings is enough to be useful.

  2. Run it (needs ASSEMBLYAI_API_KEY in the environment — this calls the real
     transcription path, including the clinical word_boost vocabulary):
        python scripts/benchmark_transcription.py --audio-dir data/benchmark

     Transcripts are cached next to the audio as <base>.hyp.txt so you can
     re-score without paying for transcription again:
        python scripts/benchmark_transcription.py --audio-dir data/benchmark --score-only

  3. Read the report. Per-file and aggregate WER + clinical-term recall print to
     the console; full detail is written to <audio-dir>/benchmark_results.json.

NOTES
  - The WER and clinical-term functions are pure and dependency-free, so the
    scoring half runs anywhere. Only --live transcription needs the API key.
  - The clinical term list is imported from audio_engine.CLINICAL_VOCAB so the
    benchmark measures exactly the vocabulary the system boosts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field, asdict

# Audio extensions the harness will look for (paired with a .txt reference).
AUDIO_EXTS = ('.mp3', '.mp4', '.m4a', '.wav', '.flac', '.ogg', '.webm', '.aac')


# ── Text normalization ───────────────────────────────────────────────────────

_SPEAKER_RE = re.compile(r'^\s*[A-Z_][A-Za-z_ ]{0,20}:\s*', re.MULTILINE)
_PUNCT_RE   = re.compile(r"[^\w\s']")


def strip_speaker_labels(text: str) -> str:
    """Remove leading 'PATIENT:' / 'SPEAKER_A:' style labels from each line."""
    return _SPEAKER_RE.sub('', text or '')


def normalize_tokens(text: str) -> list[str]:
    """Lowercase, drop punctuation (keep intra-word apostrophes), split on space.

    Deliberately simple and inspectable — WER is meaningless if normalization is
    opaque. Numbers are kept as written; if a recording mixes "five" and "5"
    you'll see it as a substitution, which is honest.
    """
    text = strip_speaker_labels(text or '').lower()
    text = _PUNCT_RE.sub(' ', text)
    return text.split()


# ── WER (Levenshtein over word tokens) ───────────────────────────────────────

@dataclass
class WerResult:
    wer: float
    substitutions: int
    deletions: int
    insertions: int
    ref_words: int

    def as_dict(self) -> dict:
        return asdict(self)


def word_error_rate(ref: str, hyp: str) -> WerResult:
    """Standard WER via edit distance on word tokens.

    WER = (S + D + I) / N, where N is the reference word count. Returns the
    component counts too, because the breakdown is diagnostic: high deletions
    suggest dropped audio/segments; high substitutions suggest mishearings
    (where drug names live).
    """
    r = normalize_tokens(ref)
    h = normalize_tokens(hyp)
    n, m = len(r), len(h)

    if n == 0:
        # No reference words — define WER as 0 if hyp also empty, else all insertions.
        return WerResult(0.0 if m == 0 else 1.0, 0, 0, m, 0)

    # dp[i][j] = edits to turn r[:i] into h[:j]; backtrack for S/D/I counts.
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if r[i - 1] == h[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j - 1],   # substitution
                                   dp[i - 1][j],        # deletion
                                   dp[i][j - 1])        # insertion

    # Backtrack to count operation types.
    i, j = n, m
    s = d = ins = 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and r[i - 1] == h[j - 1] and dp[i][j] == dp[i - 1][j - 1]:
            i, j = i - 1, j - 1
        elif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            s += 1; i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            d += 1; i -= 1
        else:
            ins += 1; j -= 1

    return WerResult(round((s + d + ins) / n, 4), s, d, ins, n)


# ── Clinical-term recall ─────────────────────────────────────────────────────

@dataclass
class TermStats:
    expected: int = 0           # occurrences in the reference
    found: int = 0              # of those, how many appear in the hypothesis
    missed_terms: list = field(default_factory=list)

    @property
    def recall(self) -> float:
        return round(self.found / self.expected, 4) if self.expected else 1.0


def _count_occurrences(text: str, term: str) -> int:
    """Case-insensitive, word-boundary count of a (possibly multiword) term."""
    pat = r'\b' + r'\s+'.join(re.escape(w) for w in term.split()) + r'\b'
    return len(re.findall(pat, text, flags=re.IGNORECASE))


# Generic → brand equivalence. A drug captured under EITHER name counts as
# captured — "Wellbutrin" for "Bupropion" is the same drug, not an error. Only
# TRUE same-drug synonyms belong here; different drugs that merely sound alike
# (e.g. Aripiprazole vs Brexpiprazole) are deliberately NOT grouped, so a
# wrong-drug substitution still scores as a miss + a false positive.
SYNONYMS = {
    'fluoxetine': ['prozac'],        'sertraline': ['zoloft'],
    'paroxetine': ['paxil'],         'citalopram': ['celexa'],
    'escitalopram': ['lexapro'],     'fluvoxamine': ['luvox'],
    'venlafaxine': ['effexor'],      'desvenlafaxine': ['pristiq'],
    'duloxetine': ['cymbalta'],      'bupropion': ['wellbutrin'],
    'mirtazapine': ['remeron'],      'trazodone': ['desyrel'],
    'vortioxetine': ['trintellix'],  'vilazodone': ['viibryd'],
    'amitriptyline': ['elavil'],     'nortriptyline': ['pamelor'],
    'clomipramine': ['anafranil'],   'imipramine': ['tofranil'],
    'lithium': ['lithobid', 'eskalith'],
    'lamotrigine': ['lamictal'],     'valproate': ['divalproex', 'depakote'],
    'carbamazepine': ['tegretol'],   'oxcarbazepine': ['trileptal'],
    'topiramate': ['topamax'],       'aripiprazole': ['abilify'],
    'risperidone': ['risperdal'],    'quetiapine': ['seroquel'],
    'olanzapine': ['zyprexa'],       'ziprasidone': ['geodon'],
    'lurasidone': ['latuda'],        'paliperidone': ['invega'],
    'clozapine': ['clozaril'],       'haloperidol': ['haldol'],
    'cariprazine': ['vraylar'],      'brexpiprazole': ['rexulti'],
    'asenapine': ['saphris'],        'dexmethylphenidate': ['focalin'],
    'methylphenidate': ['ritalin', 'concerta'],
    'lisdexamfetamine': ['vyvanse'], 'amphetamine': ['adderall'],
    'atomoxetine': ['strattera'],    'guanfacine': ['intuniv', 'tenex'],
    'alprazolam': ['xanax'],         'lorazepam': ['ativan'],
    'clonazepam': ['klonopin'],      'diazepam': ['valium'],
    'buspirone': ['buspar'],         'hydroxyzine': ['vistaril', 'atarax'],
    'zolpidem': ['ambien'],          'eszopiclone': ['lunesta'],
    'ramelteon': ['rozerem'],
}


def _group_count(text: str, forms: tuple) -> int:
    """Total occurrences of ANY surface form belonging to one drug/term."""
    return sum(_count_occurrences(text, f) for f in forms)


def build_term_groups(terms: list[str]) -> list[tuple]:
    """Collapse the flat term list into one group per drug (generic + brands),
    leaving non-drug clinical terms as singletons. Returns [(label, forms), ...]
    where forms is a tuple of every surface name that counts as that drug.
    """
    groups: list[tuple] = []
    covered: set[str] = set()
    for generic, brands in SYNONYMS.items():
        forms = {generic} | {b.lower() for b in brands}
        covered |= forms
        groups.append((generic.title(), tuple(sorted(forms))))
    for term in terms:
        tl = term.lower()
        if tl in covered:
            continue
        covered.add(tl)
        groups.append((term, (tl,)))
    return groups


def clinical_term_recall(ref: str, hyp: str, groups: list[tuple]) -> TermStats:
    """For each drug/term in the reference, check it survives in the hypothesis
    under ANY of its names (generic or brand).

    Recall is occurrence-weighted: a drug named 3x in the reference and captured
    2x in the hypothesis counts 2/3. Brand/generic equivalence means "Wellbutrin"
    is credited for a reference "Bupropion" — the same drug, not an error.
    """
    ref_clean = strip_speaker_labels(ref or '')
    hyp_clean = strip_speaker_labels(hyp or '')
    stats = TermStats()
    for label, forms in groups:
        exp = _group_count(ref_clean, forms)
        if not exp:
            continue
        got = min(_group_count(hyp_clean, forms), exp)
        stats.expected += exp
        stats.found += got
        if got < exp:
            stats.missed_terms.append(label)
    return stats


def clinical_false_positives(ref: str, hyp: str, groups: list[tuple]) -> tuple[int, list[str]]:
    """Drugs/terms that appear in the HYPOTHESIS but NOT (or more than) in the
    reference — names the transcription invented. Grouping by drug means a
    brand-for-generic substitution is NOT a false positive (same drug), but a
    different drug (e.g. Brexpiprazole for Aripiprazole) still is, because they
    are separate groups. Returns (count, labels), weighted by the surplus.
    """
    ref_clean = strip_speaker_labels(ref or '')
    hyp_clean = strip_speaker_labels(hyp or '')
    count = 0
    flagged: list[str] = []
    for label, forms in groups:
        surplus = _group_count(hyp_clean, forms) - _group_count(ref_clean, forms)
        if surplus > 0:
            count += surplus
            flagged.append(label)
    return count, flagged


# ── Clinical term list ───────────────────────────────────────────────────────

def load_clinical_terms() -> list[str]:
    """Import the exact vocabulary the system boosts, so the benchmark measures
    what word_boost targets. Falls back to a minimal list if the import fails."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from audio_engine import CLINICAL_VOCAB
        return list(CLINICAL_VOCAB)
    except Exception as e:
        print(f"  (warning: could not import CLINICAL_VOCAB: {e}; using fallback list)")
        return ['Escitalopram', 'Lamotrigine', 'Lithium', 'Bupropion', 'Aripiprazole',
                'Quetiapine', 'Sertraline', 'Vyvanse', 'Adderall', 'Lexapro']


# ── Transcription (live path) ────────────────────────────────────────────────

def transcribe_live(audio_path: str) -> tuple:
    """Run a file through the REAL transcription path (incl. word_boost).

    Passes an empty patient_id so the medication-merge step short-circuits
    BEFORE importing the database layer — this measures the static clinical
    vocabulary every session gets, and means the benchmark needs ONLY
    ASSEMBLYAI_API_KEY (no Supabase / database credentials required to run it).
    """
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from audio_engine import transcribe_audio_file
    with open(audio_path, 'rb') as f:
        data = f.read()
    result = transcribe_audio_file(
        file_bytes=data,
        filename=os.path.basename(audio_path),
        patient_id='',          # empty → no DB lookup; static vocab only
        session_id='benchmark',
    )
    if result.get('status') != 'completed' or not result.get('text'):
        raise RuntimeError(f"transcription failed: {result.get('error')}")
    return result['text'], result.get('confidence')


# ── Runner ───────────────────────────────────────────────────────────────────

def find_pairs(audio_dir: str) -> list[tuple[str, str, str]]:
    """Return (base, audio_path, ref_path) for every audio file with a .txt ref."""
    pairs = []
    for name in sorted(os.listdir(audio_dir)):
        base, ext = os.path.splitext(name)
        if ext.lower() not in AUDIO_EXTS:
            continue
        ref_path = os.path.join(audio_dir, base + '.txt')
        if not os.path.exists(ref_path):
            print(f"  (skip {name}: no matching {base}.txt reference)")
            continue
        pairs.append((base, os.path.join(audio_dir, name), ref_path))
    return pairs


def run(audio_dir: str, score_only: bool) -> dict:
    terms = load_clinical_terms()
    groups = build_term_groups(terms)
    pairs = find_pairs(audio_dir)
    if not pairs:
        print(f"No (audio, .txt) pairs found in {audio_dir}.")
        return {}

    per_file = []
    agg_s = agg_d = agg_i = agg_n = 0
    agg_term_exp = agg_term_found = agg_fp = 0
    miss_counter: Counter = Counter()
    fp_counter: Counter = Counter()
    asr_confidences: list = []

    for base, audio_path, ref_path in pairs:
        with open(ref_path, encoding='utf-8') as f:
            ref = f.read()

        hyp_cache = os.path.join(audio_dir, base + '.hyp.txt')
        asr_conf = None   # only known on a live run; None in --score-only
        if score_only:
            if not os.path.exists(hyp_cache):
                print(f"  (skip {base}: --score-only but no {base}.hyp.txt)")
                continue
            with open(hyp_cache, encoding='utf-8') as f:
                hyp = f.read()
        else:
            print(f"  transcribing {base} ...")
            hyp, asr_conf = transcribe_live(audio_path)
            with open(hyp_cache, 'w', encoding='utf-8') as f:
                f.write(hyp)

        w = word_error_rate(ref, hyp)
        t = clinical_term_recall(ref, hyp, groups)
        fp_count, fp_list = clinical_false_positives(ref, hyp, groups)
        agg_s += w.substitutions; agg_d += w.deletions
        agg_i += w.insertions;    agg_n += w.ref_words
        agg_term_exp += t.expected; agg_term_found += t.found
        agg_fp += fp_count
        for term in t.missed_terms:
            miss_counter[term] += 1
        for term in fp_list:
            fp_counter[term] += 1
        if asr_conf is not None:
            asr_confidences.append(asr_conf)

        per_file.append({
            'file': base,
            'wer': w.wer,
            'ref_words': w.ref_words,
            'sub': w.substitutions, 'del': w.deletions, 'ins': w.insertions,
            'asr_confidence': round(asr_conf, 4) if asr_conf is not None else None,
            'clinical_terms_expected': t.expected,
            'clinical_terms_found': t.found,
            'clinical_recall': t.recall,
            'clinical_false_positives': fp_count,
            'missed_terms': t.missed_terms,
            'invented_terms': fp_list,
        })

    overall_wer = round((agg_s + agg_d + agg_i) / agg_n, 4) if agg_n else None
    overall_recall = round(agg_term_found / agg_term_exp, 4) if agg_term_exp else None

    report = {
        'audio_dir': audio_dir,
        'files_scored': len(per_file),
        'vocab_mode': os.environ.get('ASSEMBLYAI_VOCAB_MODE', 'word_boost'),
        'boost_param': os.environ.get('ASSEMBLYAI_BOOST_PARAM', 'default'),
        'overall_wer': overall_wer,
        'overall_clinical_term_recall': overall_recall,
        'overall_clinical_false_positives': agg_fp,
        'overall_asr_confidence': (round(sum(asr_confidences) / len(asr_confidences), 4)
                                   if asr_confidences else None),
        'aggregate_counts': {
            'substitutions': agg_s, 'deletions': agg_d,
            'insertions': agg_i, 'ref_words': agg_n,
            'clinical_terms_expected': agg_term_exp,
            'clinical_terms_found': agg_term_found,
        },
        'most_missed_terms': miss_counter.most_common(),
        'invented_terms': fp_counter.most_common(),
        'per_file': per_file,
    }

    out_path = os.path.join(audio_dir, 'benchmark_results.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)

    _print_report(report, out_path)
    return report


def _print_report(report: dict, out_path: str) -> None:
    print("\n" + "=" * 68)
    print(f"vocab_mode: {report.get('vocab_mode', 'word_boost')}   "
          f"boost_param: {report.get('boost_param', 'default')}   "
          f"files scored: {report.get('files_scored', 0)}")
    print("clinical recall credits brand≡generic (e.g. Wellbutrin = Bupropion)")
    print("-" * 68)
    print(f"{'file':<24}{'WER':>8}{'ref_w':>8}{'clin':>8}{'recall':>9}")
    print("-" * 68)
    for r in report['per_file']:
        print(f"{r['file']:<24}{r['wer']:>8.1%}{r['ref_words']:>8}"
              f"{r['clinical_terms_expected']:>8}{r['clinical_recall']:>9.1%}")
    print("-" * 68)
    ow = report['overall_wer']
    orr = report['overall_clinical_term_recall']
    print(f"{'OVERALL':<24}{(ow if ow is not None else 0):>8.1%}"
          f"{report['aggregate_counts']['ref_words']:>8}"
          f"{report['aggregate_counts']['clinical_terms_expected']:>8}"
          f"{(orr if orr is not None else 0):>9.1%}")
    print("=" * 68)
    print(f"clinical-term recall : {(orr if orr is not None else 0):.1%}  "
          f"(found {report['aggregate_counts']['clinical_terms_found']}"
          f"/{report['aggregate_counts']['clinical_terms_expected']})")
    print(f"invented med names   : {report.get('overall_clinical_false_positives', 0)}  "
          f"(false positives — want this at 0)")
    _ac = report.get('overall_asr_confidence')
    if _ac is not None:
        print(f"mean ASR confidence  : {_ac:.3f}  (transcript audio quality, 0-1; "
              f"<0.65 is low)")
    if report.get('most_missed_terms'):
        print("most-missed terms    : " +
              ", ".join(f"{t}×{n}" for t, n in report['most_missed_terms']))
    if report.get('invented_terms'):
        print("invented terms       : " +
              ", ".join(f"{t}×{n}" for t, n in report['invented_terms']))
    print("=" * 68)
    print(f"Full detail: {out_path}\n")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="CognaSync transcription accuracy benchmark.")
    p.add_argument('--audio-dir', default='data/benchmark',
                   help='Directory of <base>.<audio> + <base>.txt reference pairs.')
    p.add_argument('--score-only', action='store_true',
                   help='Score existing <base>.hyp.txt transcripts; do not call AssemblyAI.')
    args = p.parse_args(argv)

    if not os.path.isdir(args.audio_dir):
        print(f"Audio dir not found: {args.audio_dir}")
        return 2
    run(args.audio_dir, args.score_only)
    return 0


if __name__ == '__main__':
    sys.exit(main())
