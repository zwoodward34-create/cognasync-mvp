<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

## Older adult policy appendix

This appendix sets a more sensitive escalation posture for older adults while keeping the same core rule: **direct intent, plan, means access, preparatory behavior, or recent self-harm always overrides everything else**. The main difference for this group is that passive or indirect warning signs should be treated as more clinically significant because distress can present with less visible emotion and greater physical or cognitive burden.[^1][^2][^3]

### Population definition

Use the older-adult appendix for adults roughly 60+ or for any person whose presentation is dominated by age-related vulnerabilities such as frailty, chronic illness, mobility limits, cognitive change, or social isolation. The appendix should also apply when the person is in a senior-living, assisted-living, homebound, or caregiving-dependent setting, since support and means-restriction needs are different in those environments. Population status should not be used to infer diagnosis, only to adjust the **threshold for review**.[^2][^3][^1]

### Risk amplifiers

Escalate more readily when older-adult self-harm concerns appear alongside any of the following: loneliness, recent bereavement, chronic pain, disability, major medical illness, caregiver strain, medication burden, alcohol or substance misuse, impaired mobility, or cognitive decline. Warning behaviors that deserve special attention include giving away belongings, neglecting self-care, preoccupation with death, sudden irritability, withdrawal from activities, and changes in will or final affairs. In older adults, these signs may represent a more urgent safety issue than they would in a younger population because the consequences of delayed intervention can be more severe.[^4][^3][^1]

### Threshold rules

- **Level 1 — Passive concern:** Hopelessness, withdrawal, or mild self-neglect without intent should still be logged and reviewed sooner than usual in this population.[^1][^4]
- **Level 2 — Elevated concern:** Any combination of passive ideation with isolation, frailty, chronic pain, or recent loss should trigger prompt human review.[^3][^1]
- **Level 3 — High risk:** Any intent, plan, preparatory behavior, or access to means should trigger immediate crisis review.[^4][^1]
- **Level 4 — Imminent danger:** Current intent plus specific timing, method, or inability to stay safe requires emergency response.[^1][^4]


### Required handling rules

The system should not rely on a single score or risk scale to make a decision, because holistic assessment is preferred over rigid cutoffs. When older-adult concern is present, the model should document support system strength, access to medications or other means, cognitive status, and whether the person can realistically carry out a safety plan. If the person is isolated or lacks reliable supervision, the case should move up a tier faster than it would in a well-supported setting.[^5][^3][^1]

### Example policy text

> For older adults, the system shall treat passive hopelessness, withdrawal, self-neglect, or death preoccupation as stronger warning signs than in younger adults. When these signs occur with frailty, chronic illness, isolation, cognitive change, or recent loss, the case shall be routed to prompt human review. Any direct intent, plan, means access, preparatory behavior, or recent self-harm shall trigger high-risk or imminent-danger handling immediately.[^3][^4][^1]

### Annotation fields

Use a compact note block like this:

```json
{
  "population": "older_adult",
  "amplifiers": ["isolation", "frailty", "chronic_pain"],
  "warning_signs": ["withdrawal", "self_neglect"],
  "threshold_adjustment": "one_level_lower_for_review",
  "override_present": false,
  "action": "prompt_human_review"
}
```


### Pseudocode

```text
function older_adult_adjustment(base_level, features):
    adjusted = base_level

    if features.hopelessness or features.withdrawal or features.self_neglect or features.death_preoccupation:
        adjusted = max(adjusted, 1)

    if features.isolation or features.frailty or features.chronic_pain or features.cognitive_change or features.recent_loss:
        adjusted = min(adjusted + 1, 4)

    if features.giving_away_belongings or features.changing_will or features.neglecting_medications:
        adjusted = min(adjusted + 1, 4)

    if features.access_to_means or features.preparatory_behavior or features.recent_attempt:
        adjusted = max(adjusted, 3)

    if features.direct_intent or features.specific_plan or features.imminent_danger:
        adjusted = 4

    return adjusted
```


### Reviewer note language

Use concise rationale text such as:

- “Older-adult context increases urgency because isolation and frailty amplify risk.”
- “Self-neglect and death preoccupation are concerning in this age group.”
- “Cognitive change may reduce the reliability of self-report and safety planning.”
- “Access to medications/means requires faster escalation.”

If you want, I can now format this into the same style as the adolescent, veteran, and prior-self-harm appendix so all four match exactly.
<span style="display:none">[^10][^6][^7][^8][^9]</span>

<div align="center">⁂</div>

[^1]: https://pmc.ncbi.nlm.nih.gov/articles/PMC8801854/

[^2]: https://www.ncbi.nlm.nih.gov/books/NBK588204/

[^3]: https://dphhs.mt.gov/suicideprevention/toolkit/olderpopulation

[^4]: https://www.ncoa.org/article/suicide-and-older-adults-what-you-should-know/

[^5]: https://pmc.ncbi.nlm.nih.gov/articles/PMC12887452/

[^6]: https://www.thesupportivecare.com/blog/suicide-prevention-strategies-for-the-senior-population

[^7]: https://my.clevelandclinic.org/health/articles/22306-cognitive-test

[^8]: https://www.pmc.gov.au/sites/default/files/resource/download/unlocking-the-prevention-potential-4.pdf

[^9]: https://corporate.walmart.com/policies

[^10]: https://www.ncbi.nlm.nih.gov/books/NBK565877/

