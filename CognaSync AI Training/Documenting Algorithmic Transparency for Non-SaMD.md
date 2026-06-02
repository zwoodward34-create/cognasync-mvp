<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Documenting Algorithmic Transparency for Non-SaMD Wellness Software

Even though wellness software is not regulated as SaMD (Software as a Medical Device), **documenting algorithmic transparency** is essential for ethical compliance, user trust, and avoiding regulatory scrutiny. Below is a comprehensive framework for transparent documentation of algorithms in wellness apps.

***

## Why Document Transparency for Non-SaMD Software?

| Reason | Documentation Serves |
| :-- | :-- |
| **Avoid SaMD classification** | Show algorithms are simple, verifiable, not AI-based [^1][^2] |
| **Ethical compliance** | Demonstrate responsible AI practices [^3] |
| **User trust** | Users understand how output is generated [^3] |
| **Legal protection** | Evidence of transparency if regulatory scrutiny occurs |
| **Fairness audits** | Show bias mitigation across demographics [^3] |
| **Data governance** | Meet GDPR/CCPA transparency requirements [^4] |
| **Vendor accountability** | SLAs include transparency metrics [^3] |


***

## Core Documentation Components

### 1. **Algorithm Overview**

| Element | What to Include | Example |
| :-- | :-- | :-- |
| **Algorithm name** | Clear, descriptive name | "Mood Average Calculator" |
| **Version number** | Track changes over time | "v1.2 (2026-05)" |
| **Purpose** | What the algorithm does | "Calculates average mood score from user entries" |
| **Type** | Classification (simple arithmetic, threshold, etc.) | "Simple arithmetic (average, count)" |
| **Complexity** | Complexity level (low, medium, high) | "Low - easily verifiable manually" |

**Example:**

```
Algorithm: Mood Average Calculator
Version: 1.2 (2026-05)
Purpose: Calculates average mood from user entries
Type: Simple arithmetic (sum/count)
Complexity: Low - easily verifiable manually
```


### 2. **Logic \& Calculation Method**

| Element | What to Include | Why It Matters |
| :-- | :-- | :-- |
| **Formula** | Exact mathematical formula | Anyone can verify [^2] |
| **Input variables** | All data used in calculation | Transparency about data sources |
| **Output variables** | What the algorithm produces | Clear about output |
| **Step-by-step process** | Detailed calculation flow | Demonstrates verifiability |
| **Code snippet** | Simplified code (if possible) | Shows it's not complex |

**Example:**

```python
# Algorithm: Mood Average Calculator
# Purpose: Calculate average mood score from user entries

def calculate_average_mood(mood_entries):
    """
    Calculates average mood from mood_entries list
    
    Input: mood_entries = [6, 7, 5, 8, 4]
    Output: 6.0 (average)
    
    Formula: sum(mood_entries) / len(mood_entries)
    Verification: (6+7+5+8+4)/5 = 30/5 = 6.0
    """
    if len(mood_entries) == 0:
        return None  # No entries
    
    total = sum(mood_entries)  # Sum all mood scores
    count = len(mood_entries)  # Count number of entries
    average = total / count  # Calculate average
    
    return average  # Output: average mood score
```

**Why this is safe:**

- ✅ Simple arithmetic (addition, division)
- ✅ Easily verifiable manually[^2]
- ✅ No AI/ML (automatically SaMD)[^1]
- ✅ Anyone can recalculate[^2]


### 3. **Data Sources \& Processing**

| Element | What to Include | Example |
| :-- | :-- | :-- |
| **Data origin** | Where data comes from | "User self-reports (mood 1-10)" |
| **Data collection method** | How data is collected | "Daily journal entry in app" |
| **Data preprocessing** | Any transformations applied | "None (raw values used)" |
| **Data storage** | Where data is stored | "User's device (local storage)" |
| **Data retention** | How long data is kept | "Until user deletes" |

**Example:**

```
Data Sources:
- Source: User self-reports (mood 1-10)
- Collection: Daily journal entry in app
- Preprocessing: None (raw values used)
- Storage: User's device (local storage)
- Retention: Until user deletes
```


### 4. **Performance Metrics**

| Element | What to Include | Why It Matters |
| :-- | :-- | :-- |
| **Accuracy** | How often calculation is correct | 100% for arithmetic [^2] |
| **Precision** | Consistency of results | 100% (deterministic) |
| **Reproducibility** | Same input → same output | Yes (deterministic calculation) |
| **Error handling** | What happens with invalid input | "Returns None if no entries" |

**Example:**

```
Performance Metrics:
- Accuracy: 100% (simple arithmetic)
- Precision: 100% (deterministic)
- Reproducibility: Yes (same input → same output)
- Error handling: Returns None if no entries
```


### 5. **Limitations \& Known Issues**

| Element | What to Include | Example |
| :-- | :-- | :-- |
| **Known biases** | Any demographic biases | "None (calculates only user's own data)" |
| **Failure modes** | When algorithm fails | "Returns None if no entries" |
| **Data gaps** | Missing data scenarios | "Only works with mood entries" |
| **Population limitations** | Who it doesn't work for | "None (works for all users)" |
| **Circumstances where input won't align** | When data doesn't match training | "N/A (no training data)" |

**Example:**

```
Limitations:
- Known biases: None (calculates only user's own data)
- Failure modes: Returns None if no entries
- Data gaps: Only works with mood entries
- Population limitations: None (works for all users)
- Circumstances where input won't align: N/A (no training data)
```


### 6. **Intended Use \& Limitations**

| Element | What to Include | Example |
| :-- | :-- | :-- |
| **Intended purpose** | What algorithm is for | "Personal mood tracking" |
| **Intended users** | Who should use it | "General population (wellness)" |
| **Intended environment** | Where it's used | "Mobile app (personal use)" |
| **Not intended for** | What it's NOT for | "NOT for diagnosis or treatment" |
| **Clinical claims** | What it does NOT claim | "Does NOT detect depression" |

**Example:**

```
Intended Use:
- Purpose: Personal mood tracking (wellness)
- Users: General population (not diagnosed patients)
- Environment: Mobile app (personal use)
- NOT for: Diagnosis, treatment, or prevention
- Clinical claims: Does NOT detect depression/anxiety
```


***

## Model Card Template for Wellness Software

```markdown
# Algorithm Transparency Card

## 1. Basic Information

| Field | Value |
|-------|-------|
| **Algorithm Name** | Mood Average Calculator |
| **Version** | 1.2 (2026-05) |
| **Release Date** | May 1, 2026 |
| **Owning Team** | Wellness App Development Team |
| **Contact** | support@wellnessapp.com |

## 2. Solution Overview

**What it does:** Calculates average mood score from user entries

**How it works:** Simple arithmetic (sum all entries / count entries)

**Key functionality:**
- Calculates average of mood scores (1-10)
- Counts number of entries
- Identifies minimum/maximum values

## 3. Intended Use Cases

**Intended for:**
- Personal mood tracking
- Wellness reflection
- General wellbeing support

**NOT intended for:**
- Medical diagnosis
- Clinical treatment
- Risk assessment
- Treatment recommendations

## 4. Data Sources

| Data Type | Source | Collection Method |
|-----------|--------|------------------|
| Mood score | User self-report | App journal entry |
| Timestamp | System clock | Automatic |
| User ID | User account | Login |

**Data preprocessing:** None (raw values used)

**Data storage:** User's device (local storage)

## 5. Algorithm Details

**Type:** Simple arithmetic (average calculation)

**Formula:**
```

average = sum(mood_scores) / len(mood_scores)

```

**Step-by-step process:**
1. Collect mood_scores list from user entries
2. Calculate sum of all values
3. Count number of entries
4. Divide sum by count
5. Return average (rounded to 1 decimal place)

**Code snippet:**
```python
def calculate_average_mood(mood_entries):
    if len(mood_entries) == 0:
        return None
    total = sum(mood_entries)
    count = len(mood_entries)
    average = total / count
    return round(average, 1)
```

**Verification:** Anyone can manually verify this calculation [web:360]

## 6. Performance Metrics

| Metric | Value |
| :-- | :-- |
| **Accuracy** | 100% (simple arithmetic) |
| **Precision** | 100% (deterministic) |
| **Reproducibility** | Yes (same input → same output) |
| **Error rate** | 0% (no failure modes) |

## 7. Limitations \& Known Issues

| Limitation | Description | Mitigation |
| :-- | :-- | :-- |
| **Empty dataset** | Returns None if no entries | User sees "No entries yet" |
| **Invalid input** | Non-numeric values rejected | Input validation |
| **Population bias** | None (works for all users) | N/A |
| **Data quality** | Depends on user honesty | User self-reports |

## 8. Responsible AI Considerations

**Fairness:**

- No demographic bias (calculates only user's own data)
- Works equally for all users regardless of age, gender, race

**Transparency:**

- Logic is fully explained above
- Anyone can verify calculation manually
- No black box or AI involved

**Privacy:**

- Data stored locally on user's device
- No data shared with third parties without consent
- User can delete data at any time

**Safety:**

- Not for medical use
- Clear disclaimer: "Not for diagnosis or treatment"
- Crisis resources provided if user reports severe symptoms


## 9. Governance \& Oversight

**Review frequency:** Quarterly

**Last review date:** May 1, 2026

**Next review date:** August 1, 2026

**Version history:**

- v1.0 (Jan 2026): Initial release
- v1.1 (Mar 2026): Added error handling
- v1.2 (May 2026): Improved documentation


## 10. Contact \& Support

**Questions:** support@wellnessapp.com

**Report issues:** support@wellnessapp.com

**Complaints:** compliance@wellnessapp.com

```

***

## Documentation Standards by Algorithm Type

### Type 1: Simple Arithmetic (✅ Wellness)

| Requirement | Documentation |
|-------------|--------------|
| **Formula** | Show exact mathematical formula |
| **Verification** | State "Anyone can manually verify" |
| **Complexity** | Label as "Low - easily verifiable" |
| **AI/ML** | Explicitly state "NOT AI or ML" |
| **Accuracy** | 100% (deterministic) |

**Example algorithms:**
- Average mood score
- Count of entries
- Sum of values
- Percentage calculations

### Type 2: Threshold-Based Rules (✅ Wellness)

| Requirement | Documentation |
|-------------|--------------|
| **Rule** | Show exact threshold (e.g., "mood < 4") |
| **Logic** | "If condition X, then output Y" |
| **Verification** | "Anyone can test with sample data" |
| **Complexity** | Label as "Low - predictable" |
| **AI/ML** | Explicitly state "NOT AI or ML" |

**Example algorithms:**
- "If mood < 4 for 5 days, show summary"
- "If sleep < 6 hours, flag for review"

### Type 3: AI/ML-Based (❌ SaMD)

| Requirement | Documentation |
|-------------|--------------|
| **Model type** | Neural network, decision tree, etc. |
| **Training data** | Size, source, preprocessing |
| **Performance** | Accuracy, precision, recall, F1 score [^5] |
| **Bias testing** | Subgroup analysis results [^5] |
| **Limitations** | Known biases, failure modes [^5] |

**Note:** If you use AI/ML, you are **automatically SaMD** and must comply with full regulatory requirements.[^1][^2]

***

## Transparency Requirements by Regulation

### GDPR (EU)

| Requirement | Implementation |
|-------------|---------------|
| **Right to explanation** | "We explain how output is generated" |
| **Data minimization** | Collect only what's needed [^6] |
| **Purpose limitation** | Use data only for stated wellness purpose [^6] |
| **Transparency** | Clear disclosure about data collection & use [^4] |
| **Automated decision-making** | No automated profiling without consent [^4] |

### CCPA (California)

| Requirement | Implementation |
|-------------|---------------|
| **Disclosure** | "We collect: [list], Why: [purpose]" |
| **Opt-out** | "You can opt out of data sharing" |
| **Data access** | "You can request your data" |
| **Data deletion** | "You can delete your data" |

### HIPAA (US - if applicable)

| Requirement | Implementation |
|-------------|---------------|
| **PHI protection** | If handling protected health information [^7] |
| **Business associate agreement** | If sharing with covered entities |
| **Breach notification** | If data breach occurs |

***

## Checklist for Algorithmic Transparency

### Pre-Deployment

| Requirement | Pass Criteria |
|-------------|--------------|
| **Algorithm documented** | Formula, logic, code snippet provided |
| **Verifiable** | Anyone can manually verify calculation [^2] |
| **No AI/ML** | Explicitly state "NOT AI or ML" [^1] |
| **Data sources** | Document where data comes from |
| **Limitations** | Document known biases, failure modes |
| **Intended use** | Clear about what it's NOT for |
| **Model card** | Complete transparency card created |
| **GDPR/CCPA** | Meet data privacy requirements |

### Post-Deployment

| Requirement | Frequency | Action if Failed |
|-------------|-----------|-----------------|
| **Algorithm review** | Quarterly | Update if algorithm changes |
| **Bias audit** | Annually | Implement if bias detected |
| **User feedback** | Ongoing | Address concerns |
| **Version update** | Per change | Update documentation |
| **Regulatory scan** | Annually | Update if laws change |

***

## Key Takeaways

| Principle | Documentation Requirement |
|-----------|--------------------------|
| **Simple arithmetic** | Show exact formula; state "easily verifiable" [^2] |
| **No AI/ML** | Explicitly state "NOT AI or ML" [^1] |
| **Data sources** | Document origin, collection method, storage |
| **Performance** | Report accuracy (100% for arithmetic), precision, reproducibility |
| **Limitations** | Document known biases, failure modes, population limitations |
| **Intended use** | Clear about what algorithm is NOT for (diagnosis, treatment) |
| **Model card** | Create standardized transparency card (like nutrition label) [^8] |
| **Transparency** | Users understand how output is generated [^3] |
| **Human oversight** | Humans in the loop; not automated decision-making [^3] |
| **Governance** | Quarterly review, version tracking, bias monitoring |

**Bottom line:** Even for non-SaMD wellness software, documenting algorithmic transparency builds trust, demonstrates ethical compliance, and protects against regulatory scrutiny. Use standardized model cards, show exact formulas, and explicitly state that algorithms are simple, verifiable, and not AI-based.[^8][^1][^2]
<span style="display:none">[^10][^11][^12][^13][^14][^15][^16][^17][^18][^19][^20][^21][^22][^23][^24][^9]</span>

<div align="center">⁂</div>

[^1]: https://www.horizon.ac.uk/regulating-digital-mental-health-technologies/
[^2]: https://www.scarlet.cc/post/wellness-or-mental-health-samd-how-to-know-the-difference
[^3]: https://www.franklyhelp.com/blog/where-wellness-meets-algorithms-ethical-boundaries-of-ai-in-therapy/
[^4]: https://www.pinsentmasons.com/out-law/news/compliance-risks-considered-wellness-apps
[^5]: https://www.armand.so/ai-model-cards-101-an-introduction-to-the-key-concepts-and-terminology/
[^6]: https://www.ciklum.com/blog/the-ethics-of-trend-prediction-balancing-ai-insights-with-consumer-privacy/
[^7]: https://mental.jmir.org/2023/1/e37225/PDF
[^8]: https://blogs.sas.com/content/sascom/2024/07/31/model-cards-the-ai-transparency-label-you-need/
[^9]: https://www.fda.gov/medical-devices/software-medical-device-samd/transparency-machine-learning-enabled-medical-devices-guiding-principles
[^10]: https://www.jamasoftware.com/blog/navigating-fda-ai-guidance-for-medical-devices-a-practical-guide/
[^11]: https://eleos.health/blog-posts/ai-compliance-management-behavioral-health/
[^12]: https://www.nixonlawgroup.com/resources/fda-relaxes-clinical-decision-support-and-general-wellness-guidance-what-it-means-for-generative-ai-and-consumer-wearables
[^13]: https://pmc.ncbi.nlm.nih.gov/articles/PMC11668905/
[^14]: https://shorensteincenter.org/resource/clear-documentation-framework-ai-transparency-recommendations-practitioners-context-policymakers/
[^15]: https://censinet.com/perspectives/beyond-black-box-transparency-strategies-healthcare-ai
[^16]: https://www.nature.com/articles/s41746-025-02052-9
[^17]: https://lifesciences.mofo.com/topics/ai-transparency-in-healthcare-navigating-a-changing-regulatory-landscape
[^18]: https://panaseer.com/resources/blog/delivering-responsible-ai-with-model-cards
[^19]: https://trust.arcgis.com/en/trusted-ai/ai-transparency-cards.htm
[^20]: https://www.chai.org/workgroup/applied-model
[^21]: https://shorensteincenter.org/wp-content/uploads/2024/05/CleAR_KChmielinski_FINAL.pdf
[^22]: https://www.techaheadcorp.com/blog/ai-model-cards-data-provenance/
[^23]: https://developer.nvidia.com/blog/enhancing-ai-transparency-and-ethical-considerations-with-model-card/
[^24]: https://arxiv.org/pdf/2509.20394.pdf```

