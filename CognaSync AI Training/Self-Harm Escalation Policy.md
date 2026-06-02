<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

## Self-Harm Escalation Policy

This section defines a conservative, human-centered policy for handling potential self-harm risk. The system should treat self-harm signals as safety-critical and escalate based on severity, recency, specificity, and confidence, with human review required for any elevated concern.

### Policy objectives

- Detect possible self-harm risk early.
- Minimize missed high-risk cases.
- Avoid overclaiming certainty.
- Route all moderate, high, or imminent-risk cases to humans.
- Never let the model manage a crisis autonomously.


### Risk levels

- **Level 0 — No apparent risk:** No self-harm content and no concerning pattern.
- **Level 1 — Passive concern:** Hopelessness, self-deprecation, or mild warning signs without intent.
- **Level 2 — Elevated concern:** Recurrent ideation, worsening distress, reduced coping, or vague preparatory behavior.
- **Level 3 — High risk:** Clear intent, specific plan, access to means, recent escalation, or inability to commit to safety.
- **Level 4 — Imminent danger:** Credible immediate intent or behavior indicating harm may occur soon.


### Escalation triggers

Escalate when one or more of the following are present:

- Direct suicidal or self-harm intent.
- Specific plan.
- Preparatory behavior.
- Access to lethal means or highly injurious tools.
- Recent attempt or self-harm act.
- Rapid worsening of distress.
- Marked agitation, hopelessness, or impaired judgment.
- Refusal or inability to engage in safety planning.
- Loss of protective factors, support, or supervision.


### Required actions by level

- **Level 0:** Log as non-concerning; continue routine monitoring.
- **Level 1:** Flag for supportive check-in and re-evaluation.
- **Level 2:** Route for prompt human review; initiate safety planning workflow.
- **Level 3:** Immediate escalation to trained crisis responder or clinician.
- **Level 4:** Activate emergency response workflow immediately.


### Output rules

The model should produce neutral, non-diagnostic wording such as:

- “Possible self-harm risk detected.”
- “Immediate human review recommended.”
- “Crisis workflow triggered.”
- “Insufficient evidence for safe autonomous handling.”

It should not say:

- “Confirmed suicidal.”
- “No risk.”
- “The person is safe.”


## Pseudocode

```text
function assess_self_harm_risk(input):
    risk_score = 0
    risk_flags = []

    if detects_direct_intent(input):
        risk_score += 4
        risk_flags.append("direct_intent")

    if detects_specific_plan(input):
        risk_score += 3
        risk_flags.append("specific_plan")

    if detects_access_to_means(input):
        risk_score += 3
        risk_flags.append("means_access")

    if detects_recent_attempt_or_self_harm(input):
        risk_score += 3
        risk_flags.append("recent_self_harm")

    if detects_preparatory_behavior(input):
        risk_score += 2
        risk_flags.append("preparatory_behavior")

    if detects_recurrent_ideation(input):
        risk_score += 2
        risk_flags.append("recurrent_ideation")

    if detects_hopelessness_or_burdensomeness(input):
        risk_score += 1
        risk_flags.append("hopelessness")

    if detects_rapid_worsening_or_agitation(input):
        risk_score += 1
        risk_flags.append("worsening_distress")

    if detects_refusal_to_engage_in_safety_planning(input):
        risk_score += 2
        risk_flags.append("cannot_safety_plan")

    if confidence_is_low(input):
        risk_flags.append("low_confidence")
        risk_score = max(risk_score, 1)

    if risk_score >= 8 or ("direct_intent" in risk_flags and ("specific_plan" in risk_flags or "means_access" in risk_flags)):
        level = 4
    elif risk_score >= 6:
        level = 3
    elif risk_score >= 3:
        level = 2
    elif risk_score >= 1:
        level = 1
    else:
        level = 0

    if level == 4:
        action = "activate_emergency_workflow"
    elif level == 3:
        action = "immediate_human_escalation"
    elif level == 2:
        action = "prompt_human_review_and_safety_plan"
    elif level == 1:
        action = "supportive_check_in_and_monitor"
    else:
        action = "routine_monitoring"

    return {
        "risk_level": level,
        "risk_score": risk_score,
        "risk_flags": risk_flags,
        "action": action
    }
```


## Annotation guidance

When labeling cases for training or review, record:

- Presence or absence of intent.
- Presence or absence of plan.
- Presence or absence of means access.
- Evidence of preparation.
- Whether ideation is passive or active.
- Recency of any self-harm behavior.
- Confidence level.
- Whether a human reviewer has already been notified.


### Suggested annotation fields

```json
{
  "self_harm_risk": "elevated",
  "intent": true,
  "plan": false,
  "means_access": false,
  "preparatory_behavior": false,
  "recent_attempt": false,
  "hopelessness": true,
  "confidence": "medium",
  "escalation_required": true
}
```


## Implementation notes

- Use the most cautious interpretation when evidence is ambiguous.
- Never downgrade a case solely because the model is uncertain.
- Require human confirmation before closing any case above Level 1.
- Keep the escalation reason visible to the reviewer.
- Separate screening from intervention; the model should only route, not counsel, in high-risk cases.


## Safety constraint

This policy is for triage and escalation only. It is not a diagnostic standard and must not be used as the sole basis for clinical decisions.

Would you like the next section drafted as a formal **annotation rubric** with examples and borderline cases?

