<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# I need the escalation logic for handling potential self-harm risks

Yes — for an AI training document, the safest escalation logic is a **tiered safety workflow** that treats self-harm signals as a human-reviewed crisis domain, not an automated diagnosis. High acute risk should trigger immediate escalation, while moderate risk should trigger safety planning, closer monitoring, and clinical review.[^1][^2]

## Escalation tiers

Use four operational levels:

- **Level 0: No apparent risk.** No self-harm content, no concerning pattern, or the signal is clearly unrelated.
- **Level 1: Passive concern.** Vague hopelessness, self-deprecating language, or mild warning signs without intent or means.
- **Level 2: Elevated concern.** Recurrent ideation, worsening distress, limited coping, or emerging access-related concerns.
- **Level 3: High risk.** Clear intent, plan, means, recent escalation, or inability to stay safe.
- **Level 4: Imminent danger.** Credible immediate intent or behavior suggesting harm may occur very soon; this requires emergency response.[^3][^4][^1]


## Trigger conditions

Escalate based on **content, context, and change over time**:

- Direct suicidal intent or self-harm intent.
- Specific plan or preparation.
- Access to lethal means or highly injurious tools.
- Recent self-harm act, attempt, or rehearsal.
- Rapid intensification in distress.
- Marked agitation, hopelessness, or impaired judgment.
- Refusal or inability to engage in safety planning.
- Loss of protective factors, such as support or supervision.[^2][^4][^1]


## Decision rules

A simple rule set for the AI can be:

1. If there is **direct intent plus a plan or means**, classify as high risk and escalate immediately.[^4][^1]
2. If there is **intent without a clear plan**, or a vague plan with concerning context, classify as elevated to high risk and route to human review fast.[^1]
3. If there are **warning signs but no intent**, classify as elevated concern and initiate supportive outreach and monitoring.[^5][^2]
4. If there is **recent self-harm behavior** even without stated intent, treat as at least elevated concern and assess for escalation.[^6][^4]
5. If the signal is ambiguous, default to the **more cautious** tier and request human review.[^3][^1]

## Required response by tier

| Tier | AI action | Human action |
| :-- | :-- | :-- |
| Level 1 | Acknowledge concern, encourage check-in, monitor for change | Optional review if pattern persists [^2] |
| Level 2 | Flag for prompt human review, suggest safety planning, increase monitoring | Clinical assessment, protective factor review, safety plan [^2][^5] |
| Level 3 | Immediate escalation to trained clinician or crisis team | High acuity evaluation, means safety, emergency referral if needed [^1][^4] |
| Level 4 | Activate emergency workflow immediately | Emergency services / ED / crisis response [^3][^4] |

## Safety-plan steps

For non-imminent cases, the workflow should move to a brief safety plan that includes warning signs, coping strategies, supportive contacts, professional contacts, and lethal-means reduction where appropriate. The model should not try to “solve” the crisis itself; it should hand off to a human-led process that can assess risk and coordinate care.[^2][^5][^1][^3]

## Output wording rules

The AI should use language like:

- “Possible self-harm risk detected.”
- “Immediate human review recommended.”
- “Crisis workflow triggered.”
- “Insufficient evidence to assess safely.”

It should avoid:

- “Confirmed suicide risk.”
- “This person is suicidal.”
- “No danger” unless a human review has actually verified that.


## Example escalation policy text

> If the model detects direct self-harm intent, a specific plan, access to means, or recent self-harm behavior, it must classify the case as high risk or imminent danger and immediately route it to a human crisis responder. If the model detects hopelessness, vague ideation, or repeated distress without clear intent, it must flag the case for prompt human review and safety planning. The model must never manage high-risk cases autonomously.[^1][^2][^3]

## Operational guardrails

- Do not rely on a single cue; require convergence across signals when possible.
- Treat self-harm as a **safety workflow**, not a labeling problem alone.
- Escalate more readily when confidence is low but the potential harm is high.
- Log the reasons for escalation in plain language for the human reviewer.
- Preserve privacy and limit access to only the people needed for response.[^7][^8][^9]

I can turn this into a formal policy section with pseudocode, severity thresholds, and review annotations next.
<span style="display:none">[^10][^11][^12][^13]</span>

<div align="center">⁂</div>

[^1]: https://therapistsupport.rula.com/hc/en-us/articles/41441552558619-How-to-Engage-Clients-in-a-Risk-Assessment

[^2]: https://afsp.org/brief-interventions-for-managing-suicidal-crises/

[^3]: https://www.emergencyphysicians.org/article/mental-health/protecting-patients-at-risk-of-self-harm

[^4]: https://health.choc.org/making-your-home-safe-for-a-suicidal-or-self-harming-child/

[^5]: https://www.charliehealth.com/post/how-to-create-a-self-harm-safety-plan

[^6]: https://my.clevelandclinic.org/health/diseases/12201-self-harm

[^7]: https://www.psychiatry.org/psychiatrists/practice/mental-health-apps/the-app-evaluation-model

[^8]: https://www.apa.org/news/press/releases/2025/03/privacy-protections-psychological-data

[^9]: https://pmc.ncbi.nlm.nih.gov/articles/PMC7195295/

[^10]: https://wearefamiliesrising.org/resource/silent-suffering-responding-to-self-harm/

[^11]: https://pmc.ncbi.nlm.nih.gov/articles/PMC3702671/

[^12]: https://www.willowbehavioralhealth.com/blog/what-to-do-if-you-find-someone-self-harming

[^13]: https://www.icanotes.com/2025/10/13/self-harm-treatment-plan-interventions-goals/

