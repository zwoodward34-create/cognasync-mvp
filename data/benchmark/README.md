# Transcription Benchmark — How to Run It

This folder is a one-time quality check. It measures how accurately CognaSync
transcribes voice recordings — especially **medication names**, the words that
matter most for the clinical signals. You run it occasionally, not every day,
and it does **not** touch your live app.

There are 15 ready-made scripts in this folder (`note01.txt` … `note15.txt`).
Each one is written to be read aloud. The trick: **the script you read IS the
answer key.** If you read `note01.txt` aloud word-for-word and save the
recording as `note01.m4a`, the tool can compare what the system heard against
exactly what you said.

---

## Step-by-step

**1. Record yourself reading the scripts.**
Open `note01.txt`, read it aloud naturally, and record it on your phone or
computer. Save the recording with the **same name** as the script but an audio
extension — so `note01.txt` becomes `note01.m4a`. Repeat for as many of the 15
as you like (all 15 is best; even 5 gives a useful first read).

Tips that make the test more realistic:
- Read at a normal, conversational pace — not robotically.
- Record in a normal room, the way a patient actually would.
- If you can, have **two or three different people** record the same scripts on
  **different phones**. Different voices, accents, and microphones are exactly
  what stresses a transcription system, and it's where medication names get
  mangled. More variety = a more honest number.

**2. Put the audio files in this folder, next to the scripts.**
You should end up with pairs that share a name:
```
note01.txt   note01.m4a
note02.txt   note02.m4a
...
```
Accepted audio types: .m4a, .mp3, .wav, .mp4, .webm, .flac, .ogg, .aac.

**3. Make sure your transcription key is available** (one-time setup).
See `SETUP_api_key.md` in this folder. It's a 2-minute, copy-paste setup.

**4. Run the tool.** Open Terminal, go to the project folder, and run:
```
python scripts/benchmark_transcription.py --audio-dir data/benchmark
```
It will transcribe each recording and print a scorecard. It also saves each
transcription as `note01.hyp.txt`, `note02.hyp.txt`, etc., so you can re-score
later for free with:
```
python scripts/benchmark_transcription.py --audio-dir data/benchmark --score-only
```

**5. Read the scorecard.** Two numbers per recording and an overall total:
- **WER** (word error rate) — roughly what fraction of words came out wrong.
  **Lower is better.** Under ~10% is good for clean speech.
- **Clinical recall** — what percentage of medication/clinical terms the system
  captured correctly. **Higher is better.** This is the number to watch; it
  tells you whether drug names are surviving transcription.
The tool also lists exactly which medication names it missed, per recording.
Full detail is written to `benchmark_results.json`.

---

## One honest caveat

Reading a script aloud produces cleaner, more fluent speech than a real patient
talking off the cuff (no "um"s, restarts, or mumbling). So these numbers are a
**best-case floor**, and they're strongest as a test of medication-name accuracy
and of how the system handles different voices and devices. Once this loop is
working, the natural next step is to also score a few **real, spontaneous**
recordings (with hand-corrected transcripts) to see the everyday number.

---

## What each script covers

The 15 scripts are written as realistic between-appointment patient voice notes,
deliberately seeded with a wide range of psychiatric medications (generic +
brand names) and a few clinical terms, so the medication-recall number is
meaningful. Examples include Escitalopram/Lexapro, Lamotrigine, Lithium,
Bupropion/Wellbutrin, Quetiapine/Seroquel, Sertraline/Zoloft,
Aripiprazole/Abilify, Vyvanse, Adderall, Trazodone, Clonazepam/Klonopin,
Lurasidone/Latuda, Methylphenidate/Concerta/Ritalin, Mirtazapine/Remeron,
Buspirone, Hydroxyzine, and Venlafaxine.
