<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Can you add severity thresholds for different patient populations

Yes — but I’d recommend making these **population-aware modifiers**, not separate diagnostic thresholds, because the literature emphasizes that suicide/self-harm risk is dynamic and cannot be predicted accurately with static low/medium/high labels alone. The safest policy is to keep the same escalation framework across groups while lowering the threshold for human review when a population has higher baseline vulnerability or weaker protective factors.[^1][^2][^3][^4]

## Population modifiers

Use these groups as **risk amplifiers** that increase urgency, not as standalone labels:

- **Adolescents and young people:** elevate concern for passive ideation, escalating distress, social withdrawal, or sudden behavioral change; use universal screening for ages 12+ when medically and developmentally appropriate.[^3][^4]
- **Older adults:** escalate faster when self-harm, hopelessness, isolation, frailty, cognitive impairment, or physical illness is present, because older people can have higher post–self-harm suicide risk.[^2][^5]
- **Military veterans/service members:** treat weapons-related access, transition stress, PTSD symptoms, and prior service-related trauma as stronger escalation factors.[^6][^7]
- **People with serious mental illness, major mood disorders, or substance use disorders:** reduce the threshold for human review because these conditions are associated with increased suicidality risk.[^8][^4]
- **People with prior self-harm or suicide attempt history:** escalate more quickly for any recurrence, worsening distress, or preparatory behavior.[^4][^2]


## Threshold adjustments

A simple policy approach is:

- **Base thresholds stay the same** for all populations.
- **Escalation is one level more sensitive** for higher-vulnerability groups when the signal is ambiguous or sustained.
- **Any direct intent, plan, means access, or recent attempt remains Level 3 or 4 regardless of population**.[^9][^10][^11]
- **Passive warning signs** should move from Level 1 to Level 2 more readily in adolescents, older adults, veterans, and people with prior self-harm.[^2][^3][^4]


## Formal policy language

> Population status does not replace clinical evidence. When a person belongs to a higher-vulnerability group, the model shall apply a lower threshold for human review, especially for passive ideation, hopelessness, social withdrawal, sleep disruption, or rapid worsening. The model shall not downgrade any case because the person is in a lower-risk demographic if direct intent, plan, means access, preparatory behavior, or recent self-harm is present.[^1][^4]

## Updated severity matrix

| Population | Lower-bound trigger for Level 2 | Lower-bound trigger for Level 3 |
| :-- | :-- | :-- |
| Adolescents | Passive ideation plus worsening distress, isolation, or school/peer withdrawal [^3][^4] | Active ideation, preparatory behavior, or inability to stay safe [^4] |
| Older adults | Hopelessness plus isolation, frailty, cognitive decline, or recent self-harm [^2][^5] | Any intent, plan, or recurrent self-harm with physical illness or limited support [^2] |
| Veterans/service members | Passive ideation plus trauma cues, weapons focus, or transition stress [^6][^7] | Intent, plan, means access, or marked agitation/PTSD destabilization [^7] |
| Serious mental illness / mood disorder / substance use | Recurrent ideation or rapid symptom worsening [^8][^4] | Active intent, plan, or inability to maintain safety [^4] |
| Prior self-harm history | Any return of self-harm thoughts with rising distress [^2] | Any recurrence with preparation, means access, or recent act [^2][^4] |

## Pseudocode update

```text
function adjust_risk_for_population(base_level, population, features):
    modifier = 0

    if population in ["adolescent", "older_adult", "veteran", "prior_self_harm", "serious_mental_illness", "substance_use_disorder"]:
        modifier += 1

    if population == "older_adult" and (features.frailty or features.cognitive_impairment or features.isolation):
        modifier += 1

    if population == "veteran" and (features.weapons_access or features.ptsd_cues or features.transition_stress):
        modifier += 1

    if population == "adolescent" and (features.school_withdrawal or features.peer_withdrawal or features.family_conflict):
        modifier += 1

    adjusted_level = min(base_level + modifier, 4)

    if features.direct_intent or features.specific_plan or features.means_access or features.recent_attempt:
        adjusted_level = max(adjusted_level, 3)

    if features.imminent_danger:
        adjusted_level = 4

    return adjusted_level
```


## Guardrails

- Do not use population membership alone to label risk.
- Do not reduce response intensity because a demographic is stereotypically “less likely” to self-harm.
- Use population factors only to **increase sensitivity** and prompt human review sooner.
- Document why the population modifier was applied so reviewers can see the rationale.[^4][^1]

A next useful step would be a polished **policy appendix** with one-page rules for adolescents, older adults, veterans, and chronic mental illness.
<span style="display:none">[^12][^13]</span>

<div align="center">⁂</div>

[^1]: https://www.psych.ox.ac.uk/files/research/psychosocial-assessment-following-self-harm-clinicians-guide.pdf/

[^2]: https://www.ncbi.nlm.nih.gov/books/NBK588208/

[^3]: https://www.aap.org/en/patient-care/blueprint-for-youth-suicide-prevention/strategies-for-clinical-settings-for-youth-suicide-prevention/screening-for-suicide-risk-in-clinical-practice/

[^4]: https://www.psychiatry.org/getmedia/41d9d241-e823-4176-994a-f9b96bb9af3f/Suicidality-Youth-Wagner-Jacobs.pdf

[^5]: https://www.cambridge.org/core/journals/the-british-journal-of-psychiatry/article/selfharm-in-older-adults-systematic-review/F8B3EBA9C6032E3E802B4388C464294E

[^6]: https://www.shu.edu/documents/Understanding-Risk-for-Teens-Elderly-and-Military-Veterans-857310.pdf

[^7]: https://health.mil/News/Dvids-Articles/2024/06/07/news473280

[^8]: https://abpp.org/newsletter-post/suicide-risk-assessment-and-management-current-trends-in-society-and-opportunities-for-focus-by-specialty-boards/

[^9]: https://therapistsupport.rula.com/hc/en-us/articles/41441552558619-How-to-Engage-Clients-in-a-Risk-Assessment

[^10]: https://www.emergencyphysicians.org/article/mental-health/protecting-patients-at-risk-of-self-harm

[^11]: https://health.choc.org/making-your-home-safe-for-a-suicidal-or-self-harming-child/

[^12]: https://www.limbic-cenc.org/wp-content/uploads/VA-DoD-Clinical-Practice-guideline-for-Suicide-Risk-Full-2019.pdf

[^13]: https://www.youtube.com/watch?v=zhpCvzR9-1k

