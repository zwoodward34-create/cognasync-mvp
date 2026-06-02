<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# AI Learning Module: Keeping Your Wellness App Out of SaMD Territory

## Module Overview

**Target audience:** Developers, product managers, and business leaders building wellness apps with any level of automation

**Learning objective:** Understand how to build AI-powered wellness features while staying within non-SaMD (wellness) boundaries

**Duration:** 45-60 minutes

**Prerequisites:** Basic understanding of software development

***

## Learning Objectives

By the end of this module, you will be able to:

1. **Identify** the SaMD boundary and recognize when you're crossing it
2. **Apply** the two-question test to classify your software
3. **Implement** wellness-appropriate features without triggering medical device status
4. **Document** your algorithms to demonstrate non-AI status
5. **Avoid** common pitfalls that lead to SaMD classification

***

## Module 1: Understanding SaMD (10 minutes)

### What is SaMD?

**Software as a Medical Device (SaMD)** is software intended for **medical purposes** with **sufficient functionality**.[^1][^2]


| Medical Purpose | Suff. Functionality |
| :-- | :-- |
| Diagnosis | AI/ML analysis |
| Monitoring | Personalized output |
| Treatment | Non-verifiable algorithm |
| Prevention | Clinical interpretation |
| Mitigation of disease | Risk flagging |

**Key insight:** AI/ML automatically triggers SaMD classification.[^3][^1]

### Why This Matters

| Scenario | Regulatory Status | Requirements |
| :-- | :-- | :-- |
| Wellness app (no AI) | Non-SaMD | None (consumer product) |
| Wellness app (with AI) | SaMD | CE/UKCA, clinical evidence, post-market surveillance |
| Medical device app | SaMD | 510(k), De Novo, or PMA submission |

**Cost of SaMD:** \$500K-\$2M+ for regulatory clearance, 12-24 months timeline[^1]

***

## Module 2: The Two-Question Test (10 minutes)

### Question 1: Medical Purpose?

| Ask Yourself | Answer | Implication |
| :-- | :-- | :-- |
| Is it intended for diagnosis? | YES → Medical purpose | SaMD territory |
| Is it intended for monitoring? | YES → Medical purpose | SaMD territory |
| Is it intended for treatment? | YES → Medical purpose | SaMD territory |
| Is it for general wellbeing only? | NO → Wellness | Likely non-SaMD |

**Examples:**


| Claim | Medical Purpose? | Risk |
| :-- | :-- | :-- |
| "Supports stress management" | NO | Wellness (safe) |
| "Reduces anxiety symptoms" | YES | SaMD (risky) |
| "Tracks mood for reflection" | NO | Wellness (safe) |
| "Detects depression patterns" | YES | SaMD (risky) |

### Question 2: Sufficient Functionality?

| Ask Yourself | Answer | Implication |
| :-- | :-- | :-- |
| Does it use AI/ML? | YES → High functionality | SaMD (automatic) |
| Is output personalized/interactive? | YES → High functionality | SaMD |
| Is algorithm easily verifiable? | NO → High functionality | SaMD |
| Does it interpret data? | YES → High functionality | SaMD |
| Does it just store/communicate data? | NO → Low functionality | Wellness (safe) |

**Decision Matrix:**


| Question 1 | Question 2 | Result |
| :-- | :-- | :-- |
| NO (Wellness) | NO (Low func.) | Wellness (Non-SaMD) ✓ |
| YES (Medical) | YES (High func.) | SaMD (Medical Device) ✗ |
| NO (Wellness) | YES (High func.) | **Grey Zone** (review carefully) |
| YES (Medical) | NO (Low func.) | **Grey Zone** (review carefully) |

**Critical rule:** If you use AI/ML for analysis, you are **automatically SaMD**.[^2][^1]

***

## Module 3: AI/ML Red Flags (10 minutes)

### What Triggers SaMD Automatically

| Feature | Why It's Risky | SaMD Alternative |
| :-- | :-- | :-- |
| **Machine learning models** | Learns patterns from data [^4] | Simple arithmetic (averages, counts) |
| **Neural networks** | Black box, not verifiable | Fixed rules, thresholds |
| **Predictive algorithms** | Forecasts future outcomes | Descriptive trends only |
| **Personalized recommendations** | "Based on your data, try X" | User selects content |
| **Risk scoring** | "73% risk score" | Raw counts (e.g., "3 days with mood < 4") |
| **Clinical interpretation** | "This suggests depression" | "Mood decreased from 8 to 5" |
| **Triage algorithms** | "Contact therapist now" | No algorithmic routing |

### AI vs. Non-AI: What's the Difference?

| Task | AI Version (SaMD) | Non-AI Version (Wellness) |
| :-- | :-- | :-- |
| **Mood analysis** | "AI detects depression patterns" [^1] | "Average mood: 6.2" (arithmetic) |
| **Trend detection** | "ML predicts mood will worsen" | "Mood decreased from 8 to 5" (manual) |
| **Anomaly detection** | "ML flags unusual patterns" | "3 outliers detected" (user sees) |
| **Recommendations** | "AI recommends CBT exercise X" | "Choose from 3 journaling prompts" [^2] |
| **Risk assessment** | "Risk score: 73%" | "Mood < 4 for 5 days" (threshold) |

### Common AI Misconceptions

| Myth | Reality |
| :-- | :-- |
| "AI is just a fancy algorithm" | AI = automatic SaMD classification [^1] |
| "If I don't call it AI, it's OK" | FDA looks at functionality, not marketing [^5] |
| "AI is only risky if medical claims" | AI itself triggers SaMD, regardless of claims [^1] |
| "Wellness apps can't use AI" | They can, but become SaMD and need full compliance |


***

## Module 4: Building Wellness Features Safely (10 minutes)

### ✅ Safe Features (Non-SaMD)

| Feature | Implementation | Why It's Safe |
| :-- | :-- | :-- |
| **Mood tracking** | User enters 1-10, app stores it | Simple data collection [^2] |
| **Mood averages** | `sum(mood_scores) / count(mood_scores)` | Simple arithmetic (easily verifiable) [^2] |
| **Trend charts** | Line chart showing values over time | Shows what happened, no interpretation [^2] |
| **Frequency counts** | "45% of days reported poor sleep" | Simple calculation [^2] |
| **User-selected filters** | User chooses what to see | No algorithmic judgment [^2] |
| **Manual thresholds** | "If mood < 4 for 5 days, show summary" | Fixed rule, user can verify [^2] |

### ❌ Unsafe Features (SaMD)

| Feature | Why It's Risky | SaMD Alternative |
| :-- | :-- | :-- |
| **AI risk scoring** | Automatic SaMD [^1] | Raw counts only |
| **Predictive models** | Predicts future outcomes | Descriptive trends |
| **Personalized CBT** | Treatment recommendation | User selects content |
| **Symptom interpretation** | "This suggests anxiety" | "Mood decreased from 8 to 5" |
| **Clinical triage** | "Contact therapist now" | Provide crisis resources only |

### Example: Safe Mood Tracking App

```python
# SAFE: Wellness app (Non-SaMD)

# 1. Data collection (user input)
mood_entry = {
    'date': '2026-05-31',
    'mood': 6,  # User self-reports 1-10
    'sleep_hours': 7,
    'exercise': True
}

# 2. Storage without change
datastore.append(mood_entry)

# 3. Simple arithmetic (easily verifiable)
avg_mood = sum([entry['mood'] for entry in datastore]) / len(datastore)
# Output: "Average mood: 6.2"

# 4. Manual threshold (easily verifiable)
low_mood_days = sum(1 for m in mood_scores if m < 4)
# Output: "3 days with mood < 4"

# 5. Descriptive trend (shows what happened)
mood_change = mood_logs[-1]['mood'] - mood_logs[^0]['mood']
# Output: "Mood decreased from 8 to 5"
```

**What it displays:**

- ✅ "Average mood: 6.2 (range: 3-9)"
- ✅ "3 days with mood < 4"
- ✅ "Mood decreased from 8 to 5 between Week 1-2"

**What it does NOT display:**

- ❌ "Risk score: 73%" (SaMD)
- ❌ "AI detects deterioration" (SaMD)
- ❌ "We recommend CBT" (SaMD)

***

## Module 5: Documentation for Compliance (10 minutes)

### Why Document?

| Reason | What It Proves |
| :-- | :-- |
| **Avoid SaMD** | Algorithms are simple, verifiable, not AI-based |
| **Ethical compliance** | Demonstrates responsible design |
| **User trust** | Users understand how output is generated |
| **Regulatory protection** | Evidence if regulators question classification |

### Model Card Template (Non-AI)

```markdown
# Model Card: Mood Average Calculator

## Algorithm Type
**Simple Arithmetic (NOT AI/ML)**

## Purpose
Calculates average mood score from user entries

## Formula
```

average_mood = sum(mood_scores) / count(mood_scores)

```

## Verification
Anyone can manually verify this calculation [web:360]

## NOT for
- ❌ Medical diagnosis
- ❌ Treatment decisions
- ❌ Clinical monitoring
- ❌ Risk assessment
```


### Key Documentation Elements

| Element | What to Include |
| :-- | :-- |
| **Algorithm type** | Explicitly state "NOT AI/ML" |
| **Formula** | Exact mathematical formula |
| **Code snippet** | Simplified code (if possible) |
| **Data sources** | Where data comes from |
| **Limitations** | Known biases, failure modes |
| **Intended use** | What it's NOT for (diagnosis, treatment) |


***

## Module 6: Common Pitfalls \& How to Avoid Them (5 minutes)

### Pitfall 1: "It's Just a Little AI"

| Situation | Risk | Fix |
| :-- | :-- | :-- |
| Using ML for "detection" | Automatic SaMD [^1] | Use simple thresholds instead |
| "AI-powered" in marketing | Attracts regulatory scrutiny | Remove AI language |
| Third-party AI API | Still counts as AI use | Use non-AI alternatives |

### Pitfall 2: "We Don't Make Medical Claims"

| Situation | Risk | Fix |
| :-- | :-- | :-- |
| AI functionality without claims | Still SaMD (functionality matters) | Remove AI, keep wellness claims |
| "Wellness" branding with medical features | Regulators look at functionality, not branding | Ensure features match branding |
| User can infer medical purpose | Still SaMD if functionality is medical | Keep features descriptive only |

### Pitfall 3: "It's Just Analytics"

| Situation | Risk | Fix |
| :-- | :-- | :-- |
| "Analytics" with predictive models | Predictive = SaMD | Use descriptive analytics only |
| AI for "pattern detection" | Pattern detection = SaMD | Use simple counts/frequencies |
| Risk scoring for "wellness" | Risk scoring = SaMD | Use raw counts only |

### Pitfall 4: "No One Will Notice"

| Situation | Risk | Fix |
| :-- | :-- | :-- |
| Hidden AI in background | Regulators can audit code | Document everything transparently |
| "Black box" algorithms | Not easily verifiable = SaMD | Use transparent, verifiable logic |
| Third-party models without documentation | Can't prove non-AI status | Require vendor documentation |


***

## Module 7: Regulatory Framework Overview (5 minutes)

### UK (MHRA)

| Requirement | Wellness | SaMD |
| :-- | :-- | :-- |
| **Regulation** | None (consumer product) | MHRA [^1] |
| **Classification** | N/A | Class I/IIa/IIb/III |
| **Certification** | None | CE/UKCA mark [^6] |
| **Evidence** | None | Clinical evidence required [^1] |

### Australia (TGA)

| Requirement | Wellness | SaMD |
| :-- | :-- | :-- |
| **Exclusion** | Follows clinical guidelines + displays references [^7] | Regulated by TGA [^7] |
| **ARTG registration** | Not required | Required [^7] |
| **Software rules** | Digitizes paper questionnaire = NOT device [^7] | Additional logic = device [^7] |

### USA (FDA)

| Requirement | Wellness | SaMD |
| :-- | :-- | :-- |
| **Regulation** | "Hands-off" for low-risk general wellness [^5] | FDA clearance required [^5] |
| **Classification** | N/A | Class I (low), II (moderate), III (high) [^5] |
| **Pre-Cert** | Streamlined for qualifying orgs [^5] | Full regulatory pathway [^5] |


***

## Module 8: Decision Framework (5 minutes)

### Quick Decision Tree

```
START: Planning wellness app feature
         │
         ▼
┌─────────────────────────────┐
│ Does it use AI/ML?           │
│ • Machine learning?          │
│ • Neural networks?           │
│ • Predictive models?         │
│                              │
│ YES → You are SaMD ✗       │
│     (must comply with full  │
│     regulatory requirements)│
│                              │
│ NO → Go to next question   │
└─────────────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│ Does it have personalized/   │
│ interactive output?           │
│ • "Based on your data, try X"?│
│ • Personalized recommendations?│
│                              │
│ YES → You are SaMD ✗       │
│ NO → Go to next question   │
└─────────────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│ Is algorithm easily          │
│ verifiable?                  │
│ • Can anyone manually verify?│
│ • Simple arithmetic?         │
│                              │
│ YES → Wellness (Non-SaMD) ✓│
│ NO → You are SaMD ✗        │
└─────────────────────────────┘
```


***

## Module 9: Assessment \& Quiz (10 minutes)

### Quiz 1: Classification

**Question 1:** Your app uses a simple average to calculate mood scores. Is this SaMD?

- A) Yes, because it analyzes data
- B) No, because it's simple arithmetic[^2]
- C) Yes, because it tracks mood
- D) It depends on the marketing

**Correct answer: B** — Simple arithmetic is easily verifiable and not AI/ML.[^2]

***

### Quiz 2: AI Risk

**Question 2:** Your app uses machine learning to detect "depression patterns" but doesn't make medical claims. Is this SaMD?

- A) No, because no medical claims
- B) Yes, because AI/ML automatically triggers SaMD[^1]
- C) It depends on the algorithm complexity
- D) Only if it makes treatment recommendations

**Correct answer: B** — AI/ML automatically triggers SaMD classification regardless of claims.[^1]

***

### Quiz 3: Safe Features

**Question 3:** Which feature is safe for a wellness app (Non-SaMD)?

- A) AI detects deterioration patterns
- B) "Risk score: 73%"
- C) "Average mood: 6.2" (simple arithmetic)[^2]
- D) "We recommend CBT exercise X"

**Correct answer: C** — Simple arithmetic is easily verifiable and not AI/ML.[^2]

***

### Quiz 4: Documentation

**Question 4:** What should you explicitly state in your algorithm documentation?

- A) "AI-powered for accuracy"
- B) "NOT AI/ML" and "easily verifiable"[^1][^2]
- C) "Advanced machine learning"
- D) "Predictive analytics"

**Correct answer: B** — Explicitly state "NOT AI/ML" to avoid SaMD classification.[^1]

***

### Quiz 5: Claims

**Question 5:** Which claim is safe for a wellness app?

- A) "Detects depression"
- B) "Reduces anxiety symptoms"
- C) "Supports stress management"[^2]
- D) "Prevents panic attacks"

**Correct answer: C** — "Supports stress management" is wellness; others are medical claims.[^2]

***

## Module 10: Action Plan (5 minutes)

### Before Development

| Step | Action |
| :-- | :-- |
| **1. Classify** | Use the two-question test |
| **2. Plan features** | Avoid AI/ML, personalized output, risk scoring |
| **3. Choose algorithms** | Simple arithmetic, fixed rules, manual thresholds |
| **4. Prepare documentation** | Create model cards for all algorithms |

### During Development

| Step | Action |
| :-- | :-- |
| **5. Code review** | Check for AI/ML libraries, predictive models |
| **6. Algorithm verification** | Ensure anyone can manually verify calculations |
| **7. Claims review** | Remove medical claims from marketing |
| **8. Test with users** | Ensure users don't infer medical purpose |

### After Deployment

| Step | Action |
| :-- | :-- |
| **9. Monitor** | Track user feedback, regulatory changes |
| **10. Review quarterly** | Update documentation, check for drift |
| **11. Audit** | Periodic review of algorithm changes |
| **12. Train team** | Ensure all team members understand SaMD boundary |


***

## Key Takeaways

| Principle | Implementation |
| :-- | :-- |
| **AI = SaMD** | Any machine learning automatically triggers SaMD [^1] |
| **Simple arithmetic** | Use averages, counts, percentages (easily verifiable) [^2] |
| **No personalized output** | User selects content, not AI recommendations [^2] |
| **No interpretation** | "What happened", not "what it means" [^2] |
| **No risk flagging** | Never flag "high risk" or "clinical concern" [^2] |
| **Document everything** | Explicitly state "NOT AI/ML" in model cards [^1] |
| **Claims must match** | "Supports wellbeing", not "treats symptoms" [^2] |
| **Verify manually** | Anyone should be able to recalculate output [^2] |

**Bottom line:** Keep your wellness app out of SaMD territory by avoiding AI/ML entirely, using simple verifiable algorithms, and making only wellness-appropriate claims. If you need AI for advanced features, you must comply with full SaMD regulatory requirements.[^1][^2]
<span style="display:none">[^10][^11][^12][^13][^14][^15][^8][^9]</span>

<div align="center">⁂</div>

[^1]: https://www.horizon.ac.uk/regulating-digital-mental-health-technologies/

[^2]: https://www.scarlet.cc/post/wellness-or-mental-health-samd-how-to-know-the-difference

[^3]: https://www.complizen.ai/post/artificial-intelligence-and-machine-learning-ai-ml-in-software-as-a-medical-device-samd

[^4]: https://research.uky.edu/sites/default/files/2024-10/algorithms_clinical_decision_support_software.pdf

[^5]: https://globalforum.diaglobal.org/issue/november-2024/mental-health-apps-regulation-and-validation-are-needed/

[^6]: https://www.gov.uk/government/news/mhra-issues-new-guidance-for-people-using-mental-health-apps-and-technologies

[^7]: https://www.tga.gov.au/sites/default/files/digital-mental-health-software-based-medical-devices.pdf

[^8]: https://medenvoyglobal.com/blog/ai-and-machine-learning-best-practices-in-samd/

[^9]: https://rookqs.com/blog-rqs/fda-expectations-for-ai/ml-model-training-in-samd-2025-guide

[^10]: https://www.berkleyls.com/blog/fda-aiml-samd-framework-what-companies-need-know-now

[^11]: https://www.fda.gov/medical-devices/software-medical-device-samd/artificial-intelligence-software-medical-device

[^12]: https://intuitionlabs.ai/articles/fda-samd-classification-ai-machine-learning

[^13]: https://pmc.ncbi.nlm.nih.gov/articles/PMC11988595/

[^14]: https://softteco.com/blog/software-as-a-medical-device-samd

[^15]: https://www.sciencedirect.com/science/article/pii/S294976122400124X

