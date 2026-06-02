<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Implementing Model Cards for Non-AI Wellness Algorithms

Model cards—originally designed for ML models—work equally well for **non-AI wellness algorithms** (like simple averages, thresholds, and counts). They provide standardized transparency, build user trust, and explicitly demonstrate that your algorithms are **not AI/ML** (which would trigger SaMD classification).[^1][^2]

***

## Why Model Cards for Non-AI Algorithms?

| Benefit | Why It Matters for Wellness Apps |
| :-- | :-- |
| **Demonstrates non-AI status** | Explicitly state "NOT AI or ML" to avoid SaMD [^1] |
| **Standardized transparency** | Nutrition-label format users recognize [^3] |
| **Builds trust** | Users understand how output is generated [^4] |
| **Regulatory protection** | Evidence if regulators question classification |
| **Ethical compliance** | Shows responsible algorithm design [^4] |
| **Guides proper use** | Clearly states what algorithm is NOT for |

**Key insight:** Just as nutrition labels tell you what's in food, model cards tell you what's in your algorithm.[^3]

***

## Model Card Template for Non-AI Wellness Algorithms

```markdown
# Model Card: Wellness Algorithm

## 1. Model Overview

| Field | Value |
|-------|-------|
| **Algorithm Name** | Mood Average Calculator |
| **Version** | 1.2 (2026-05) |
| **Release Date** | May 1, 2026 |
| **Last Updated** | May 15, 2026 |
| **Developer** | Wellness App Team |
| **Contact** | support@wellnessapp.com |
| **License** | Proprietary (user license) |
| **Type** | **Simple Arithmetic (NOT AI/ML)** |

---

## 2. Intended Use

### What This Algorithm Is For
- **Primary purpose:** Personal mood tracking for wellness reflection
- **Intended users:** General population (not diagnosed patients)
- **Intended environment:** Mobile app (personal use only)
- **Type of output:** Average mood score (1-10 scale)

### What This Algorithm Is NOT For
- ❌ **NOT for medical diagnosis**
- ❌ **NOT for treatment decisions**
- ❌ **NOT for clinical monitoring**
- ❌ **NOT for risk assessment**
- ❌ **NOT for treatment recommendations**
- ❌ **NOT for preventive care**

**Disclaimer:** This algorithm is for wellness purposes only. It does NOT detect, diagnose, treat, or prevent any medical condition.

---

## 3. Algorithm Details

### How It Works

**Algorithm Type:** Simple arithmetic (average calculation)

**NOT AI/ML:** This algorithm uses basic mathematical operations. Anyone can verify the calculation manually [web:360].

### Formula

```

average_mood = sum(mood_scores) / count(mood_scores)

```

### Step-by-Step Process

1. **Input:** Collect mood_scores list from user entries (e.g., [6, 7, 5, 8, 4])
2. **Sum:** Calculate sum of all values (6+7+5+8+4 = 30)
3. **Count:** Count number of entries (5 entries)
4. **Divide:** Divide sum by count (30/5 = 6.0)
5. **Output:** Return average mood score (6.0)

### Code Snippet (Simplified)

```python
def calculate_average_mood(mood_entries):
    """
    Calculates average mood from mood_entries list
    
    Input: mood_entries =[^5][^6][^7][^8][^9]
    Output: 6.0 (average)
    
    Formula: sum(mood_entries) / len(mood_entries)
    Verification: (6+7+5+8+4)/5 = 30/5 = 6.0
    
    This is simple arithmetic—NOT AI or ML.
    Anyone can verify this calculation manually.
    """
    if len(mood_entries) == 0:
        return None  # No entries
    
    total = sum(mood_entries)  # Sum all mood scores
    count = len(mood_entries)  # Count number of entries
    average = total / count  # Calculate average
    
    return round(average, 1)  # Output: average mood score
```


---

## 4. Training \& Data

### Training Data

**N/A** — This algorithm is NOT trained on data. It uses simple arithmetic.

### Data Sources

| Data Type | Source | Collection Method |
| :-- | :-- | :-- |
| Mood score | User self-report | App journal entry (1-10 scale) |
| Timestamp | System clock | Automatic timestamp |
| User ID | User account | Login authentication |

### Data Preprocessing

**None** — Raw values are used directly in calculation.

### Data Storage

- **Where:** User's device (local storage)
- **Retention:** Until user deletes
- **Sharing:** No data shared without explicit consent

---

## 5. Performance Metrics

### Accuracy

**100%** — Simple arithmetic produces exact results (deterministic)

### Precision

**100%** — Same input always produces same output (deterministic)

### Reproducibility

**Yes** — Identical input → identical output

### Error Rate

**0%** — No failure modes for valid input

### Performance Summary

| Metric | Value | Notes |
| :-- | :-- | :-- |
| Accuracy | 100% | Deterministic calculation |
| Precision | 100% | No randomness |
| Reproducibility | Yes | Same input → same output |
| Error rate | 0% | No failure modes |


---

## 6. Evaluation Factors

### Demographic Groups

**Not applicable** — This algorithm calculates only user's own data. No demographic bias exists.

### Subgroup Performance

**Not applicable** — Works equally for all users regardless of:

- Age
- Gender
- Race/Ethnicity
- Language
- Socioeconomic status


### Data Conditions

**Not applicable** — Only works with valid mood entries (1-10 scale).

---

## 7. Known Limitations

### Failure Modes

| Limitation | Description | Mitigation |
| :-- | :-- | :-- |
| **Empty dataset** | Returns None if no mood entries | User sees "No entries yet" message |
| **Invalid input** | Non-numeric values rejected | Input validation (1-10 range only) |
| **Missing data** | Only calculates what user enters | User sees "X entries" count |
| **User honesty** | Depends on accurate self-reporting | No mitigation (user self-reports) |

### Population Limitations

**None** — Works for all users regardless of demographics.

### Out-of-Scope Uses

- ❌ Medical diagnosis
- ❌ Treatment decisions
- ❌ Clinical monitoring
- ❌ Risk assessment
- ❌ Treatment recommendations

---

## 8. Quantitative Analysis

### Performance by Subgroup

**Not applicable** — No subgroup variation (algorithm calculates only user's own data).

### Bias Assessment

**No bias detected** — Algorithm does not use demographic information.

### Fairness Testing

**Not applicable** — Algorithm is neutral (no demographic data used).

---

## 9. Ethical Considerations

### Fairness

- ✅ **No demographic bias** — Calculates only user's own data
- ✅ **Works equally** for all users regardless of age, gender, race
- ✅ **No subgroup disparities** (algorithm is neutral)


### Transparency

- ✅ **Logic fully explained** above
- ✅ **Anyone can verify** calculation manually
- ✅ **No black box** or AI involved
- ✅ **Formula is simple** arithmetic


### Privacy

- ✅ **Data stored locally** on user's device
- ✅ **No data shared** without explicit consent
- ✅ **User can delete** data at any time
- ✅ **Meets GDPR/CCPA** requirements


### Safety

- ✅ **Not for medical use**
- ✅ **Clear disclaimer** included
- ✅ **Crisis resources** provided if user reports severe symptoms
- ✅ **Human oversight** — algorithm doesn't make decisions


### Potential Risks

| Risk | Likelihood | Mitigation |
| :-- | :-- | :-- |
| Misinterpretation as medical tool | Low | Clear disclaimer: "Not for diagnosis" |
| User reliance without professional help | Low | Crisis resources provided |
| Data breach | Low | Local storage, encryption |


---

## 10. Caveats \& Recommendations

### How to Use This Algorithm

- ✅ Use for **personal reflection** only
- ✅ Use for **wellness tracking**
- ✅ Use for **general wellbeing support**
- ✅ Check with **healthcare professional** for clinical concerns


### How NOT to Use This Algorithm

- ❌ **NOT for diagnosis** of any condition
- ❌ **NOT for treatment** decisions
- ❌ **NOT for clinical monitoring**
- ❌ **NOT for risk assessment**
- ❌ **NOT for medical advice**


### Recommendations for Users

1. **Use for reflection** — Track your mood over time
2. **Don't self-diagnose** — Consult professional for clinical concerns
3. **Share with care** — If sharing data with healthcare provider, clarify it's for wellness only
4. **Crisis resources** — If mood is severely low, contact crisis line immediately

### Recommendations for Developers

1. **Review quarterly** — Update if algorithm changes
2. **Document changes** — Update version number when logic changes
3. **Test thoroughly** — Verify calculation is correct
4. **Monitor feedback** — Address user concerns about interpretation

---

## 11. Governance \& Maintenance

### Version History

| Version | Date | Changes |
| :-- | :-- | :-- |
| 1.0 | Jan 1, 2026 | Initial release |
| 1.1 | Mar 15, 2026 | Added error handling for empty dataset |
| 1.2 | May 1, 2026 | Improved documentation, added model card |

### Review Schedule

- **Algorithm review:** Quarterly
- **Last review date:** May 1, 2026
- **Next review date:** August 1, 2026


### Audit Trail

- Who approved: Jane Doe (Lead Developer)
- When approved: May 1, 2026
- Approval notes: Algorithm verified as simple arithmetic, not AI/ML


### Maintenance

- **Responsible team:** Wellness App Development Team
- **Contact for issues:** support@wellnessapp.com
- **Update frequency:** Per logic change (not automatic)

---

## 12. References \& Resources

### Related Documentation

- User guide: [Link to user documentation]
- Privacy policy: [Link to privacy policy]
- Terms of service: [Link to terms]


### Crisis Resources

- **National Suicide Prevention Lifeline:** 988 (US)
- **Crisis Text Line:** Text HOME to 741741
- **Emergency:** 911 (US)


### Regulatory References

- MHRA: "Software as a Medical Device" guidance [web:359]
- FDA: "General Wellness Policy" [web:365]
- TGA: "Digital mental health: Software based medical devices" [web:361]

---

## 13. Contact \& Support

| Purpose | Contact |
| :-- | :-- |
| Questions | support@wellnessapp.com |
| Report issues | support@wellnessapp.com |
| Complaints | compliance@wellnessapp.com |
| Privacy concerns | privacy@wellnessapp.com |


---

**Last Updated:** May 15, 2026
**Version:** 1.2
**Status:** Active

```

***

## Implementation Checklist

### Document Creation

| Item | Requirement | Status |
|------|-------------|--------|
| **Algorithm name** | Clear, descriptive name | ☐ |
| **Version number** | Track changes over time | ☐ |
| **Type classification** | Explicitly state "NOT AI/ML" | ☐ |
| **Formula** | Exact mathematical formula | ☐ |
| **Code snippet** | Simplified code (if possible) | ☐ |
| **Data sources** | Document origin, collection method | ☐ |
| **Performance metrics** | Accuracy, precision, reproducibility | ☐ |
| **Limitations** | Known biases, failure modes | ☐ |
| **Intended use** | What it's NOT for (diagnosis, treatment) | ☐ |
| **Ethical considerations** | Fairness, transparency, privacy | ☐ |

### Review & Approval

| Item | Requirement | Status |
|------|-------------|--------|
| **Legal review** | Ensure compliance with regulations | ☐ |
| **Technical review** | Verify formula is correct | ☐ |
| **Ethics review** | Confirm responsible AI practices | ☐ |
| **User test** | Can users understand it? | ☐ |
| **Approval** | Sign-off from responsible party | ☐ |

### Deployment

| Item | Requirement | Status |
|------|-------------|--------|
| **Accessible** | Available to users in app | ☐ |
| **Linked** | Connected from algorithm output | ☐ |
| **Searchable** | Easy to find in documentation | ☐ |
| **Versioned** | Tracked with algorithm version | ☐ |
| **Updated** | Updated when algorithm changes | ☐ |

***

## Best Practices for Non-AI Model Cards

### 1. **Explicitly State "NOT AI/ML"**

| Include | Why |
|---------|-----|
| "NOT AI or ML" in algorithm type | Avoids SaMD classification [^1] |
| "Simple arithmetic" in description | Demonstrates verifiability [^2] |
| "Anyone can verify manually" | Reduces regulatory risk [^2] |

### 2. **Keep It Accessible**

| Layer | Audience | Content |
|-------|---------|---------|
| **Summary** | General users | 1-page overview |
| **Details** | Developers | Full formula, code, testing |
| **Technical** | Regulators | Complete documentation |

**Example:**
```

Quick Summary (1 page):

- What it does: Calculates average mood
- How it works: Simple arithmetic (N/A)
- NOT for: Medical diagnosis/treatment
- Contact: support@wellnessapp.com

Full Details (5+ pages):

- Complete formula
- Code snippet
- Performance metrics
- Limitations
- Ethical considerations

```

### 3. **Use "Nutrition Label" Format**

Like food nutrition labels, model cards should be:
- **Visual** (tables, boxes, clear sections)
- **Standardized** (same format across algorithms)
- **Easy to scan** (quick lookup of key info)
- **Layered** (overview + details)[^10][^3]

### 4. **Document What It's NOT For**

| Must Include | Purpose |
|-------------|---------|
| "NOT for medical diagnosis" | Avoids SaMD claims [^2] |
| "NOT for treatment decisions" | Avoids SaMD claims [^2] |
| "NOT for clinical monitoring" | Avoids SaMD claims [^2] |
| "NOT for risk assessment" | Avoids SaMD claims [^2] |

### 5. **Track Version Changes**

| Version Element | When to Update |
|----------------|----------------|
| Version number | Any logic change |
| Release date | New version |
| Changes | What changed |
| Approval who/when | Who approved change |

***

## Automation Tools

### Automated Model Card Generation

| Tool | Features | Best For |
|------|----------|---------|
| **Model Card Toolkit** (Google) | Auto-extract metadata from pipelines | ML models (not needed for non-AI) |
| **Hugging Face** | Card generation features | ML models (not needed for non-AI) |
| **Custom script** | Template-based generation | Non-AI wellness algorithms |

**For non-AI algorithms:** Manual template filling is appropriate (no need for automated tools designed for ML).[^11]

***

## Regulatory Alignment

### UK (MHRA)
- **Requirement:** Algorithms must be "solidly evidenced and verifiable"[^12]
- **Model card role:** Demonstrates verifiability[^12]

### Australia (TGA)
- **Requirement:** Software with logic beyond data collection = medical device[^13]
- **Model card role:** Shows logic is simple arithmetic, not AI/ML[^13]

### USA (FDA)
- **Requirement:** General wellness tools must NOT claim diagnosis/treatment[^14]
- **Model card role:** Explicitly states what algorithm is NOT for[^14]

***

## Key Takeaways

| Principle | Implementation |
|-----------|---------------|
| **Explicitly non-AI** | State "NOT AI or ML" prominently [^1] |
| **Simple arithmetic** | Show exact formula; label as "easily verifiable" [^2] |
| **Standardized format** | Use nutrition-label style (tables, clear sections) |
| **Layered access** | Summary (1 page) + Details (5+ pages) |
| **What it's NOT for** | Explicitly list out-of-scope uses |
| **Version tracking** | Update when algorithm changes |
| **Accessibility** | Available to users in app, searchable |
| **Ethical considerations** | Fairness, transparency, privacy documented |
| **Governance** | Quarterly review, version history |
| **Contact info** | Clear support/complaint channels |

**Bottom line:** Model cards for non-AI wellness algorithms work the same as for ML models but are simpler to create. They demonstrate transparency, avoid SaMD classification, build user trust, and provide evidence of responsible algorithm design.[^2][^3][^1]
<span style="display:none">[^15][^16][^17][^18][^19][^20][^21]</span>

<div align="center">⁂</div>

[^1]: https://www.horizon.ac.uk/regulating-digital-mental-health-technologies/
[^2]: https://www.scarlet.cc/post/wellness-or-mental-health-samd-how-to-know-the-difference
[^3]: https://blogs.sas.com/content/sascom/2024/07/31/model-cards-the-ai-transparency-label-you-need/
[^4]: https://www.franklyhelp.com/blog/where-wellness-meets-algorithms-ethical-boundaries-of-ai-in-therapy/
[^5]: https://www.apa.org/monitor/2023/06/measurement-based-care-patients-treatment
[^6]: https://www.zoho.com/bookings/industries/psychiatrist-appointment-scheduling-software.html
[^7]: https://www.keragon.com/blog/appointment-scheduling-mental-health
[^8]: https://pmc.ncbi.nlm.nih.gov/articles/PMC11379786/
[^9]: https://www.valant.io/resources/blog/the-top-5-reports-you-should-be-using-in-your-behavioral-health-practice/
[^10]: https://www.nature.com/articles/s41746-025-01482-9
[^11]: https://aisecurityandsafety.org/en/glossary/model-cards/
[^12]: https://www.pinsentmasons.com/out-law/news/compliance-risks-considered-wellness-apps
[^13]: https://www.tga.gov.au/sites/default/files/digital-mental-health-software-based-medical-devices.pdf
[^14]: https://globalforum.diaglobal.org/issue/november-2024/mental-health-apps-regulation-and-validation-are-needed/
[^15]: https://research.google/pubs/model-cards-for-model-reporting/
[^16]: https://iapp.org/news/a/5-things-to-know-about-ai-model-cards
[^17]: https://www.modelop.com/good-decisions-series/ai-nutrition-labels-in-action-how-modelop-operationalizes-model-cards
[^18]: https://pmc.ncbi.nlm.nih.gov/articles/PMC11861263/
[^19]: https://developer.nvidia.com/blog/enhancing-ai-transparency-and-ethical-considerations-with-model-card/
[^20]: https://arxiv.org/pdf/1810.03993.pdf
[^21]: https://arxiv.org/pdf/2311.12560.pdf```

