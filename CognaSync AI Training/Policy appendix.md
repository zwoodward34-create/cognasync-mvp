<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

## Policy appendix

This appendix defines how to adjust self-harm escalation sensitivity for four groups: adolescents, older adults, veterans/service members, and people with prior self-harm or serious mental illness. The core rule is that population context changes **how quickly to escalate**, but never replaces direct evidence such as intent, plan, means, preparatory behavior, or recent self-harm.[^1][^2][^3]

### 1) Adolescents

- Use universal screening for youth ages 12 and older when medically and developmentally appropriate, and screen ages 8 to 11 when clinically indicated.[^2]
- Escalate more readily for passive ideation, social withdrawal, sleep disruption, school refusal, family conflict, or sudden behavior change, because youth presentations can shift quickly.[^4][^2]
- Treat any self-harm signal plus access to means, recent escalation, or inability to engage with caregivers as at least Level 2, even if intent is unclear.[^4]
- If acute suicidal thoughts are present, move to emergency evaluation rather than continued screening.[^4]


### 2) Older adults

- Treat hopelessness, isolation, frailty, cognitive change, chronic pain, or recent loss as stronger amplifiers of concern.[^5][^1]
- Escalate faster for self-harm thoughts when physical illness, reduced mobility, or limited support is present, because these factors can worsen safety and reduce buffering.[^1][^5]
- Any evidence of planning, preparation, or access to lethal means should move the case to high risk, not simply elevated risk.[^5]
- Do not assume low acute risk because the person is calm or not emotionally expressive; older adults may present with less visible distress.[^5]


### 3) Veterans and service members

- Treat transition stress, trauma-related arousal, sleep disturbance, irritability, firearm relevance, and social isolation as meaningful risk amplifiers.[^6][^3]
- Lower the threshold for human review when passive hopelessness appears alongside trauma cues, reintegration stress, or repeated references to weapons.[^6]
- If direct intent, a plan, or means access is present, escalate immediately regardless of veteran status or apparent coping.[^3]
- In documentation, frame veteran context as a reason for heightened vigilance, not as a diagnosis or assumption of danger.[^3]


### 4) Prior self-harm or serious mental illness

- Any history of self-harm, prior attempt, major mood disorder, psychosis, or substance use disorder should reduce the threshold for escalation when new warning signs appear.[^1][^3]
- Recurrent ideation, worsening distress, increased frequency, or preparatory behavior should move the case up at least one level sooner than in a first-episode presentation.[^1][^5]
- Do not use comorbid diagnosis as a reason to withhold assessment or safety action; the response should still follow current risk features.[^1]
- When there is a past attempt, treat current ambiguity conservatively and route to human review rather than waiting for clearer evidence.[^5]


### Unified override rule

- Any **direct intent, specific plan, preparatory behavior, access to means, or recent attempt** overrides population modifiers and should trigger high-risk or imminent-danger handling.[^4][^5]
- If the signal is ambiguous, the system should escalate one level more cautiously for adolescents, older adults, veterans, and people with prior self-harm or severe mental illness.[^2][^3][^1]


### Example policy text

> Population-specific factors may lower the threshold for escalation, but they must not be used to infer diagnosis or to dismiss risk. Adolescents, older adults, veterans, and people with prior self-harm or serious mental illness require earlier human review when warning signs are passive, recurrent, or contextually amplified. Any direct intent, plan, means access, preparatory behavior, or recent self-harm action supersedes population modifiers and requires immediate crisis handling.[^2][^3][^1]

### Reviewer note fields

Use a short note block like this in the appendix:

- `population_factor`: adolescent / older_adult / veteran / prior_self_harm / serious_mental_illness.
- `amplifier`: isolation, trauma cues, frailty, recent loss, access to means, sleep disruption.
- `threshold_adjustment`: none / one_level_lower_for_review.
- `override_present`: yes / no.
- `action`: monitor / human_review / urgent_escalation / emergency_response.


### Pseudocode

```text
function population_adjustment(base_level, population, features):
    adjusted = base_level

    if population in ["adolescent", "older_adult", "veteran", "prior_self_harm", "serious_mental_illness"]:
        adjusted = min(adjusted + 1, 4)

    if population == "adolescent" and (features.school_withdrawal or features.family_conflict or features.sudden_behavior_change):
        adjusted = min(adjusted + 1, 4)

    if population == "older_adult" and (features.frailty or features.cognitive_change or features.isolation or features.chronic_pain):
        adjusted = min(adjusted + 1, 4)

    if population == "veteran" and (features.trauma_cues or features.weapons_relevance or features.reintegration_stress or features.sleep_disturbance):
        adjusted = min(adjusted + 1, 4)

    if population in ["prior_self_harm", "serious_mental_illness"] and (features.recurrent_ideation or features.rapid_worsening):
        adjusted = min(adjusted + 1, 4)

    if features.direct_intent or features.specific_plan or features.means_access or features.preparatory_behavior or features.recent_attempt:
        adjusted = max(adjusted, 3)

    if features.imminent_danger:
        adjusted = 4

    return adjusted
```

If you want, I can convert this into a single polished appendix page with consistent style and a matching decision table.
<span style="display:none">[^10][^7][^8][^9]</span>

<div align="center">⁂</div>

[^1]: https://www.ncbi.nlm.nih.gov/books/NBK588208/

[^2]: https://www.aap.org/en/patient-care/blueprint-for-youth-suicide-prevention/strategies-for-clinical-settings-for-youth-suicide-prevention/screening-for-suicide-risk-in-clinical-practice/

[^3]: https://www.healthquality.va.gov/guidelines/mh/srb/index.asp

[^4]: https://www.aap.org/en/patient-care/blueprint-for-youth-suicide-prevention/strategies-for-clinical-settings-for-youth-suicide-prevention/clinical-pathways-for-suicide-prevention/

[^5]: https://pmc.ncbi.nlm.nih.gov/articles/PMC8801854/

[^6]: https://health.mil/News/Dvids-Articles/2024/06/07/news473280

[^7]: https://www.healthychildren.org/English/news/Pages/aap-updates-guidance-to-assess-teen-suicide-risk.aspx

[^8]: https://www.ncbi.nlm.nih.gov/books/NBK588204/

[^9]: https://www.acpjournals.org/doi/10.7326/ANNALS-24-01938

[^10]: https://www.aap.org/en/patient-care/blueprint-for-youth-suicide-prevention/additional-resources-for-suicide-prevention/

