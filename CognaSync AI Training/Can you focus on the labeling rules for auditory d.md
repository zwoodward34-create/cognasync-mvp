<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Can you focus on the labeling rules for auditory data specifically

Yes — here is a focused set of **labeling rules for auditory data** you can use in an AI training document.

## Labeling goal

Auditory labels should capture **observable speech and voice patterns** that may correlate with distress, not diagnose a condition. The labeler should only mark what is present in the audio and what is supported by context, and should separate vocal features from any inferred mental state.

## Core labeling principles

- Label **what is heard**, not what is assumed.
- Prefer **multi-label** annotations over a single diagnosis-style label.
- Use a **baseline-aware** approach when prior samples from the same speaker exist.
- Distinguish **temporary situational changes** from sustained patterns.
- Mark uncertainty explicitly when the signal is ambiguous.
- Never infer intent, diagnosis, or risk from voice alone.


## Primary auditory features to label

### Speech production

- Speech rate.
- Pause frequency and pause length.
- Response latency.
- Interruptions or trailing off.
- Reduced spontaneity or minimal verbal output.


### Prosody and tone

- Pitch elevation or flattening.
- Reduced pitch variation.
- Monotone or “flat” affect.
- Vocal strain.
- Tremor-like quality.
- Harshness, shakiness, or breathiness.


### Fluency and coherence

- Word-finding difficulty.
- Repetition.
- Slowed articulation.
- Slurred speech.
- Disorganized or hard-to-follow speech.
- Sudden topic shifts.


### Arousal-related markers

- Agitated or pressured speech.
- Loudness changes.
- Rapid, difficult-to-interrupt speech.
- Overly subdued or low-energy speech.


## Suggested label set

Use labels like these:

- **normal_variation**: No notable concern beyond expected variation.
- **low_energy_voice**: Soft, slowed, reduced speech activity.
- **flat_prosody**: Limited pitch and affect variation.
- **pressured_speech**: Rapid, difficult to interrupt, increased verbal output.
- **agitated_tone**: Elevated intensity, tension, or irritability in voice.
- **speech_disorganization**: Loose, incoherent, or hard-to-follow speech.
- **speech_slowing**: Noticeably slower rate than baseline.
- **pause_increase**: More frequent or longer pauses than baseline.
- **vocal_strain**: Strained, shaky, or effortful voice quality.
- **uncertain**: Audio quality or context is insufficient for confident labeling.


## Severity guidance

Use a graded scale such as:

- **0 = absent**
- **1 = mild**
- **2 = moderate**
- **3 = marked**

Severity should reflect how clearly and consistently the feature appears, not how serious the downstream mental health implication might be.

## Context rules

Labelers should consider:

- Background noise.
- Microphone quality.
- Language proficiency or accent.
- Emotional context of the conversation.
- Whether the person is answering a difficult question.
- Whether the audio sample is too short to judge reliably.

If poor audio quality could explain the feature, use **uncertain** or **not assessable** rather than a confident label.

## Baseline comparison rules

If prior audio exists for the same person, label deviations from their own norm:

- “slower than usual.”
- “more monotone than baseline.”
- “more pressured than baseline.”
- “more pauses than baseline.”

This is more reliable than comparing against a generic population average.

## Exclusion rules

Do **not** label these from auditory data alone:

- Depression.
- Anxiety.
- Bipolar disorder.
- Psychosis.
- Suicidal intent.
- Personality disorder.
- Substance use.

Those require broader clinical context and human review.

## Example annotation schema

```json
{
  "audio_id": "sample_0142",
  "speaker_id": "speaker_09",
  "labels": {
    "speech_rate": "slowed",
    "prosody": "flat",
    "pauses": "increased",
    "speech_coherence": "intact",
    "arousal": "low",
    "confidence": "medium"
  },
  "notes": "Compared with baseline, the speaker sounds quieter and slower. Audio quality is acceptable."
}
```


## Recommended annotator instructions

Annotators should be told to:

- Listen once for overall impression, then again for specific features.
- Use consistent definitions across samples.
- Record uncertainty when features may be caused by noise or context.
- Avoid medical language unless the label set explicitly requires it.
- Escalate any sample with direct self-harm content to a human safety workflow rather than only annotating it.


## Practical cautions

Auditory signals can be informative, but they are noisy and context-sensitive. The safest training setup uses them as one input among several, with **human review** for any high-stakes mental health inference.

If you want, I can turn this into a formal annotation guide with label definitions, decision examples, and edge-case rules.

