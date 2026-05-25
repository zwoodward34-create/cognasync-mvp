# CognaSync — Regulatory and Framework Alignment

**Purpose:** This document maps CognaSync's existing architecture to the published frameworks for safe AI use in digital mental health and clinical software. It is intended for clinical advisors, regulatory reviewers, and investor due diligence — anyone evaluating whether CognaSync's safety posture aligns with established standards.

**Status:** All architecture described here is currently implemented unless explicitly noted as a forward-looking commitment. This is documentation of the existing system, not a roadmap.

---

## 1. The Frameworks We Align Against

CognaSync's clinical-safety architecture was designed around principles that map directly onto three published frameworks:

- **FDA Cures Act Section 3060** — the Clinical Decision Support Software exemption defining when AI-enabled tools sit outside SaMD classification.
- **FDA Total Product Life Cycle (TPLC) approach** — the framework for managing iterative AI-enabled medical software across pre-market, deployment, and post-market phases.
- **The "Calibrated Prompt" framework** — the professional standard for LLM use in clinical contexts, comprising Clarity, Context, Goal Alignment, Output Format, and Safety Guardrails.

The following sections show how CognaSync's existing architecture maps to each.

---

## 2. Cures Act Section 3060 — Clinical Decision Support Exemption

The Section 3060 exemption requires four conditions. CognaSync's architecture satisfies each one structurally.

### Condition 1 — The software displays patient information.

**Implementation.** CognaSync displays structured patient-reported data: mood, sleep duration and quality, stress, energy, dissociation, anxiety, irritability, motivation, perceived stress, wake-up timing, sleep latency, overnight awakenings, alcohol units, hydration, exercise minutes, sunlight exposure, screen time, social quality, workload friction, coping activity use, notable symptoms, medication events, and journal entries. All values are entered by the patient. All displayed information is patient-sourced.

### Condition 2 — The software supports clinical recommendations.

**Implementation.** Mode C (provider clinical summary) surfaces patterns intended to support clinical recommendations — quantitative trends, symptom co-occurrences, medication signals, qualitative themes, threshold-crossing flags. Suggested discussion topics are anchored to specific data points and are framed as topics for the clinician to consider, not as recommendations themselves.

### Condition 3 — A licensed clinician can independently evaluate the basis of any surfaced pattern.

**Implementation.** Every Mode C output includes a methodology footer disclosing: the number of check-ins in the analysis window, the days the window covers, the statistical thresholds for any trend claims (N ≥ 21, p ≤ 0.05, R² ≥ 0.25), and the disclosure that all scores are computed deterministically in code prior to any AI language generation. The provider sees the analytical basis explicitly.

### Condition 4 — The clinician sees the basis of the information.

**Implementation.** All composite scores cite their inputs and computation. All symptom patterns cite their co-occurrence statistics, delta, and N. All flags cite the specific threshold crossed. All trend statements cite the regression statistic supporting them. The provider can audit any surfaced claim against its data anchors.

### Practical Result

CognaSync's current scope sits intentionally within the CDS exemption. The product describes patterns; it does not make diagnostic or therapeutic recommendations. The product can be deployed without SaMD clearance at its current scope.

---

## 3. Total Product Life Cycle (TPLC) Alignment

The FDA's TPLC framework treats AI-enabled medical software as iterative throughout its lifecycle. CognaSync's architecture maps to the three TPLC phases:

### Premarket Phase

Baseline guardrails are established before any output is generated:

- The four non-negotiable safety rules (never diagnose, never advise medication changes, describe data not clinical meaning, route crisis not engage) are embedded in every system prompt.
- The deterministic scoring engine computes all clinically sensitive numeric values in Python before the AI is invoked.
- The forbidden-language list is hard-coded and version-controlled.
- Crisis interception triggers before any AI call.

### Deployment Phase

Model behavior is observable and constrained:

- System prompts are explicit and version-controlled in the codebase. Every change is visible in git history.
- Every AI call logs the exact model version used at the time of generation.
- Output is post-processed against the forbidden-language list at the string level, regardless of the model's intent.
- Crisis routing is deterministic, not AI-mediated. The model never sees crisis content.

### Postmarket Phase (forward-looking framework, partial implementation today)

Structured monitoring becomes operationally meaningful at deployment scale. The architecture supports:

- **Output sampling.** Periodic human review of randomly sampled outputs across modes to verify the three-layer verification is performing as designed. This is a roadmap item that becomes meaningful at clinical scale.
- **Regression testing across model versions.** A fixed set of synthetic patient inputs can be run against any model version to detect drift in output behavior. This is a roadmap item that becomes critical at clinical deployment scale.
- **Adverse event capture.** Provider-side reporting of any surfaced pattern that the clinician judges to be incorrect or unsafe. The architecture supports this; the workflow is a roadmap item.

---

## 4. Predetermined Change Control Plan (PCCP) Readiness

The PCCP framework allows AI-enabled medical device manufacturers to pre-specify the kinds of algorithm changes that may be made post-market without a new regulatory submission, provided the changes stay within established guardrails. CognaSync's architecture is PCCP-ready in three structural ways:

### 1. Safety rules are immutable across model updates.

The four non-negotiable safety rules are enforced at the prompt layer and the post-processing layer, not in the model itself. Model upgrades cannot relax these rules. A PCCP could pre-specify that the underlying LLM is allowed to change provided the four rules continue to be enforced at the system-prompt and sanitization layers.

### 2. The scoring engine is independent of the LLM.

All composite scores (Stability Score, Stim Load, Crash Risk, Dopamine Efficiency, Nervous System Load, Sleep Disruption Score, Mood Distortion, Nutrition Stability Score) are computed in deterministic Python code. Model changes do not affect score computation. A PCCP could pre-specify that score formulas may be refined without triggering re-submission, provided the refinement is documented and regression-tested against prior outputs.

### 3. The forbidden-language sanitization is independent of the model.

The forbidden-language list can be extended defensively (new patterns added to catch language not previously seen) without affecting the model itself. A PCCP could pre-specify that the sanitization list may be expanded — but not contracted — without re-submission.

### Practical Result

When CognaSync's roadmap features (Decompensation Risk Forecasting in particular) cross into SaMD-classified territory, the existing architecture is already structured to support drafting a PCCP that pre-specifies allowable changes within the existing safety guardrails. The regulatory friction of iteration is reduced before it begins.

---

## 5. Calibrated Prompt Framework Compliance

The professional standard for LLM use in clinical contexts is the "Calibrated Prompt" framework. CognaSync's system prompts implement all five elements.

| Element | How CognaSync's prompts comply |
|---|---|
| **Clarity** | Each output mode (A, B, C, D) has a distinct, named system prompt with specific, non-ambiguous language. "Mode A: 2–3 sentences, warm, references at least one specific number from the current check-in" — not "give the patient an insight." |
| **Context** | Structured patient data is passed to the model as JSON-shaped context. Scores, trends, journal themes, symptom patterns, medication events, substance flags, and safety signals are all pre-computed and supplied. The model never retrieves or infers data; it references what it was given. |
| **Goal Alignment** | Each mode has a single, defined audience and purpose. Mode A is the post-check-in patient insight. Mode B is the patient pre-appointment summary. Mode C is the provider clinical summary. Mode D is the dashboard threshold alert. Output is never mode-mixed. |
| **Output Format** | Each mode has an explicitly defined output structure. Mode A: 2–3 sentences. Mode B: five labeled paragraphs in conversational prose. Mode C: structured brief with named sections and methodology footer. Mode D: terse `[Level] [Subject] — [Data]` format. |
| **Safety Guardrails** | The four non-negotiable rules are embedded in every system prompt. The forbidden-language list is enforced after generation. Crisis interception runs before the model is invoked. Privacy guardrails prevent personally identifying information from being sent to the model where structured data is sufficient. |

The architectural commitment is that future prompt iteration must continue to satisfy all five elements. Prompt changes that violate any of the five are flagged in code review and reconsidered.

---

## 6. Risk Mitigation Matrix

The published frameworks identify six categories of risk in clinical AI deployment. CognaSync's architecture addresses each, mapped here to the standard micro / macro / technical mitigation hierarchy.

### Hallucinations (Confabulations)

- **Technical mitigation.** Deterministic scoring computes all numeric values in code before the model is invoked. The model is instructed to reference scores, not recompute them. Forbidden-language sanitization catches diagnostic phrasing and certainty overclaims after generation.
- **Micro mitigation.** System prompts explicitly instruct the model against inventing numbers, dates, or events not present in the structured data context.
- **Macro mitigation.** The methodology footer on every Mode C output discloses the analytical basis, allowing clinicians to identify any output that diverges from its claimed basis.

### Black Box Opacity

- **Technical mitigation.** Scores are computed in transparent, version-controlled code rather than inferred by the model. The methodology footer discloses N, statistical thresholds, and the deterministic-computation discipline.
- **Micro mitigation.** Suggested discussion topics in Mode C are required to be anchored to specific surfaced data points, making the basis of each suggestion auditable.
- **Macro mitigation.** System prompts are public to the team and version-controlled. The forbidden-language list is reviewable. Clinical advisors can audit the prompt-engineering layer directly.

### Data Drift

- **Technical mitigation.** Model version is logged with every AI call. System prompts are version-controlled. The deterministic scoring engine is invariant to model changes — drift in computed scores would indicate input-distribution drift, not model drift.
- **Macro mitigation (forward-looking).** Periodic regression testing of model behavior against a fixed set of synthetic patient inputs is a roadmap commitment that becomes critical at clinical deployment scale.

### Bias and Inequity

- **Technical mitigation.** The deterministic scoring engine is demographic-blind: it takes only the patient's logged values and conditions on no demographic variable. Output language is restrained by the forbidden-language sanitization regardless of patient context.
- **Macro mitigation.** The Interpersonal Safety Signal detector is provider-only by design, because the bias risk of misinterpreting language patterns in a patient-facing context is too high.
- **Macro mitigation (forward-looking).** Formal bias audits as the user base grows — comparing surfaced-pattern frequencies across demographic groups — are a roadmap commitment.

### Privacy

- **Technical mitigation.** Patient identifying data is never sent to the LLM. Only structured scores and de-identified content are passed as context. All patient data is stored in Supabase with Postgres-level encryption at rest and row-level security policies enforcing per-user access.
- **Technical mitigation (forward-looking).** A formal Business Associate Agreement (BAA) with the LLM provider is a Q1 commitment in the post-raise plan.
- **Macro mitigation.** Patients can export their full data at any time, supporting both portability rights and the patient-agency principle of HIPAA.

### Crisis and Adverse Event

- **Technical mitigation.** Crisis-language interception runs before any AI call. The model never processes triggering language; the patient receives static crisis resources and nothing else.
- **Technical mitigation.** The Interpersonal Safety Signal detector is provider-only, never patient-facing, because patient-side disclosure carries safety risks (e.g., device shared with an abusive partner).
- **Macro mitigation (forward-looking).** Adverse event capture workflow for providers is a roadmap commitment.

---

## 7. What This Document Is Not

This document is descriptive, not prescriptive. It describes the regulatory and safety alignment that CognaSync's existing architecture demonstrates. It does not constitute regulatory advice, legal advice, or a guarantee of regulatory acceptance. Formal regulatory review by qualified counsel is a Q1 commitment in the post-raise plan.

The frameworks cited are public. The architectural mappings described here are the product's design choices. The intent of this document is to make the alignment legible to clinical advisors, regulatory reviewers, and investors, not to assert regulatory status.

---

## 8. Forward-Looking Commitments

The following are roadmap items that strengthen the framework alignment described above and that are scoped in the post-raise plan:

- Formal Business Associate Agreement (BAA) with the LLM provider — Q1 post-raise.
- HIPAA compliance formalization across all sub-processors — Q1 post-raise.
- Initial security audit and TOS / Privacy Policy aligned with the described alignment — Q1 post-raise.
- Structured output sampling and human review workflow — operational at first clinical deployment.
- Regression testing of model behavior across model versions — operational at first clinical deployment.
- Formal bias audit framework — operational once user base supports demographic analysis.
- Adverse event capture and reporting workflow — operational at first clinical deployment.

None of these items reflect gaps in the architecture itself. They reflect the operational and procedural infrastructure that becomes necessary when the product moves from MVP to clinical deployment at scale.
