<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Collecting and Analyzing Mental Health Data Without Crossing the SaMD Boundary

## Understanding the SaMD Boundary

**Software as a Medical Device (SaMD)** is triggered when software is **intended** for medical purposes **and** has sufficient functionality. You can collect and analyze mental health data while staying outside SaMD regulation by maintaining **wellness/appletance** status rather than **medical device** status.[^1][^2]

***

## Two-Question Test for SaMD Qualification

Before designing your data collection system, answer these questions:[^2][^1]


| Question | Wellness (Non-SaMD) Answer | SaMD Answer |
| :-- | :-- | :-- |
| **1. Medical purpose?** | NO — supports general wellbeing | YES — clinical task for diagnosis/ monitoring/treatment |
| **2. Sufficient functionality?** | NO — stores/communicates data without change | YES — personalized/interpretive/predictive using AI |

**If both answers are NO** → You are likely in wellness territory[^1][^2]
**If both answers are YES** → You are SaMD and need regulatory approval[^2][^1]

***

## Acceptable vs. Unacceptable Functions

### ✅ Acceptable Functions (Non-SaMD / Wellness)

| Function | Example | Why It's Safe |
| :-- | :-- | :-- |
| **Stores data without change** | "Mood log: Jan 1 = 5/10, Jan 2 = 6/10" | Simply records user input [^2] |
| **Communicates data without prioritization** | "Recent entries: [list all]" | No sorting, ranking, or highlighting [^2] |
| **Processes user instruction to show fixed content** | Selected journaling prompt displays [^2] | Similar to choosing a chapter in a book [^2] |
| **Easily verifiable calculation** | "Average mood: (5+6+7)/3 = 6" | Simple arithmetic anyone can verify [^2] |
| **Generic educational content** | "What is mindfulness?" article | No personalization or interpretation |
| **Simple tracking** | "Sleep: 7 hours last night" | Raw data without interpretation [^2] |
| **Display trends without interpretation** | Line chart showing mood over time | Shows what happened, not what it means [^2] |

### ❌ Unacceptable Functions (SaMD Territory)

| Function | Example | Why It Crosses the Line |
| :-- | :-- | :-- |
| **Personalized/interactive output** | "Based on your mood, try CBT exercise X" | Interactive AND personalized [^2] |
| **Algorithm not easily verifiable** | "Risk score: 73% (AI model)" | Cannot be manually verified [^2] |
| **Uses AI/ML** | "AI detects depression patterns" | AI automatically triggers SaMD [^1][^2] |
| **Interprets entries** | "Your mood shows deterioration" | Interpretive, not just descriptive [^2] |
| **Flags deterioration** | "⚠️ Warning: Symptoms worsening" | Clinical interpretation [^2] |
| **Recommends CBT practices** | "We recommend CBT technique Y" | Treatment recommendation [^2] |
| **Flags clinical risk** | "At risk of depression" | Diagnostic/predictive claim [^2] |
| **Algorithmic triage** | "Contact your therapist now" | Clinical decision support [^2] |
| **Uses AI for analysis** | "Machine learning model analysis" | AI = high functionality = SaMD [^1] |


***

## Permitted Activities (Non-SaMD)

### 1. **Data Collection**

| Activity | Acceptable Implementation |
| :-- | :-- |
| **Self-reported mood** | "Rate your mood 1-10" (simple input) |
| **Symptom tracking** | "Check boxes: slept poorly, felt anxious, etc." |
| **Speech/audio recording** | Record for descriptive analysis only |
| **Activity logs** | "Walked 5,000 steps today" (raw data) |
| **Sleep tracking** | "Slept 6 hours" (no interpretation) |
| **Journaling** | Open text field (no AI analysis) |
| **Questionnaires** | PHQ-9 displayed digitally (no scoring logic) [^3] |

**Key principle:** Collect data without **interpreting** or **scoring** it.[^3]

### 2. **Descriptive Analysis**

| Analysis Type | Acceptable Output |
| :-- | :-- |
| **Frequency counts** | "Mood 1-10: 15 times, Mood 6-7: 8 times" |
| **Trends over time** | "Mood decreased from 8 to 5 between Week 1-2" |
| **Averages** | "Average mood: 6.2 (range: 3-9)" |
| **Percentages** | "45% of days reported poor sleep" |
| **Clustering** | "Data grouped into 3 clusters" (no labels) |
| **Anomaly detection** | "3 outliers detected" (no interpretation) |

**What to avoid:**

- ❌ "Your mood is below average" (normative claim)[^4]
- ❌ "This suggests anxiety" (interpretive)[^4]
- ❌ "Risk score: 73%" (predictive)[^2]
- ❌ "You should seek help" (recommendation)[^2]


### 3. **Visualization**

| Visualization | Acceptable Implementation |
| :-- | :-- |
| **Line chart** | "Mood over time" (no arrows, no target line) |
| **Bar chart** | "Sleep hours by day" (y-axis starts at 0) |
| **Histogram** | "Distribution of mood scores" |
| **Box plot** | "Range of values" (no "outlier" labels) |

**What to avoid:**

- ❌ Red/green traffic light colors[^5]
- ❌ Trend arrows (▲▼) indicating "good/bad"[^5]
- ❌ Target/goal lines[^5]
- ❌ Labels like "normal range" or "abnormal"[^4]

***

## Claims and Marketing Language

### ✅ Acceptable Claims (Wellness)

| Claim Type | Example |
| :-- | :-- |
| **General wellbeing** | "Supports mindfulness practice" [^2] |
| **Lifestyle support** | "Helps you build healthier routines" [^2] |
| **Educational** | "Learn about stress management" [^2] |
| **Motivational** | "Track your progress" [^2] |
| **Reflection** | "Reflect on how you feel" [^2] |
| **Non-clinical** | "Support stress management" [^2] |

### ❌ Unacceptable Claims (SaMD)

| Claim Type | Example | Regulatory Risk |
| :-- | :-- | :-- |
| **Diagnosis** | "Detects depression" | Medical device [^2] |
| **Treatment** | "Reduces anxiety symptoms" | Medical device [^2] |
| **Prevention** | "Prevents panic attacks" | Medical device [^2] |
| **Management** | "Manages PTSD symptoms" | Medical device [^2] |
| **Risk flagging** | "Flags high-risk users" | Medical device [^2] |
| **Recommendations** | "Recommends evidence-based interventions" | Medical device [^2] |
| **Relapse** | "Prevents relapse" | Medical device [^2] |
| **Clinical outcome** | "Reduces depression scores" | Medical device [^2] |

**Key distinction:** "Supports stress management" (wellness) vs "Reduces anxiety symptoms" (SaMD).[^2]

***

## AI/ML: The Critical Boundary

### ⚠️ AI Automatically Triggers SaMD

| Function | AI Version (SaMD) | Non-AI Version (Wellness) |
| :-- | :-- | :-- |
| **Speech analysis** | "AI detects depression patterns" | "Speech rate: 142 WPM" (manual calculation) [^2] |
| **Mood prediction** | "ML predicts mood deterioration" | "Mood decreasing (manual chart)" [^2] |
| **Risk assessment** | "AI risk score: 73%" | "3 high-mood entries in past week" [^2] |
| **Anomaly detection** | "ML flags unusual patterns" | "3 outliers detected (manual)" [^2] |
| **Personalized content** | "AI recommends exercises" | "Choose from 3 journaling prompts" [^2] |

**Critical rule:** If you use AI/ML for analysis, you are **automatically SaMD**.[^1][^2]

### Acceptable Non-AI Alternatives

| Instead of AI, Use |
| :-- |
| **Simple arithmetic** (averages, sums, counts) [^2] |
| **Manual thresholds** (e.g., "mood < 4 for 5 days") [^2] |
| **Fixed rules** (e.g., "if 3+ entries, show summary") [^2] |
| **User-selected filters** (user chooses what to see) [^2] |
| **Descriptive statistics** (frequency, median, range) [^2] |


***

## User Profiles and Real-World Use

### Who Is Using Your Product?

| User Profile | Risk Level |
| :-- | :-- |
| **General population** | Lower risk (wellness) [^2] |
| **Diagnosed individuals** | Higher risk (likely SaMD) [^2] |
| **Clinical setting** | Higher risk (likely SaMD) [^2] |
| **Research participants** | Lower risk (research tool) |

**Important:** If predominantly used by people with diagnosed mental health conditions, it's **unlikely to be wellness** regardless of messaging.[^2]

***

## Documentation Requirements

### If You Are NOT SaMD (Wellness)

| Document | Purpose |
| :-- | :-- |
| **Disclaimer** | "Not for diagnosis or treatment" |
| **Intended use** | "Supports general wellbeing" |
| **Limitations** | "Not a medical device; consult professional for clinical concerns" |
| **Data collection** | "Collects data for personal tracking only" [^3] |
| **No claims** | "No clinical claims made" |

### If You Are SaMD (Medical Device)

| Document | Requirement |
| :-- | :-- |
| **Clinical evidence** | Prove safety and effectiveness [^1] |
| **Risk assessment** | ISO 14971 compliance [^1] |
| **CE/UKCA mark** | Required for UK market [^6] |
| **ARTG registration** | Required for Australian market [^3] |
| **Post-market surveillance** | Ongoing monitoring [^1] |
| **Quality management** | ISO 13485 compliance [^1] |


***

## Regulatory Frameworks by Region

### UK (MHRA Guidance)

| Requirement | Wellness | SaMD |
| :-- | :-- | :-- |
| **Regulation** | None (general consumer product) | MHRA [^1] |
| **Classification** | N/A | Class I/IIa/IIb/III [^1] |
| **Certification** | None | CE/UKCA mark [^6] |
| **Evidence** | None | Clinical evidence required [^1] |

### Australia (TGA)

| Requirement | Wellness | SaMD |
| :-- | :-- | :-- |
| **Exclusion criteria** | Follows clinical guidelines AND referenced displayed [^3] | Regulated by TGA [^3] |
| **ARTG registration** | Not required | Required [^3] |
| **Software rules** | Digitizes paper questionnaire = NOT medical device [^3] | Additional logic beyond data collection = medical device [^3] |

### USA (FDA)

| Requirement | Wellness | SaMD |
| :-- | :-- | :-- |
| **Regulation** | "Hands-off" for low-risk general wellness [^7] | FDA clearance required [^7] |
| **Classification** | N/A | Class I (low), II (moderate), III (high) [^7] |
| **Pre-Cert Program** | Streamlined for qualifying orgs [^7] | Full regulatory pathway [^7] |


***

## Decision Framework

```
┌─────────────────────────────────────────────────────────────────┐
│  START: Planning mental health data collection                  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Question 1: Does it have a medical purpose?                    │
│  • Intended for diagnosis/monitoring/treatment?                 │
│  • Targets clinical conditions?                                 │
│  • Part of mental health management process?                    │
│                                                                 │
│  NO → Go to Question 2                                          │
│  YES → You are SaMD (medical device)                            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Question 2: Does it have high functionality?                   │
│  • Processes user instruction with interactive/personalized     │
│    output?                                                      │
│  • Uses calculation/algorithm not easily verifiable?            │
│  • Uses AI/ML for analysis?                                     │
│                                                                 │
│  NO → You are wellness (non-SaMD) ✓                            │
│  YES → You are SaMD (medical device)                            │
└─────────────────────────────────────────────────────────────────┘
```


***

## Practical Checklist for Non-SaMD Data Collection

### ✅ Must-Have for Wellness Status

| Requirement | Implementation |
| :-- | :-- |
| **No medical claims** | Never claim diagnosis, treatment, or prevention |
| **No AI/ML** | Use manual calculations only [^2] |
| **No personalized output** | Display raw data, not personalized recommendations |
| **No interpretation** | Show what happened, not what it means [^2] |
| **No risk flagging** | Never flag "high risk" or "clinical concern" |
| **Simple calculations** | Averages, counts, percentages (easily verifiable) [^2] |
| **Descriptive language** | "Mood decreased from 8 to 5" (not "worsened") |
| **Neutral visuals** | No traffic light colors, arrows, or targets |
| **Wellness disclaimer** | "Not for diagnosis or treatment" |
| **Non-clinical users** | General population, not diagnosed patients |

### ❌ Must-Avoid for Wellness Status

| Risk | Avoid Completely |
| :-- | :-- |
| **AI/ML** | Any machine learning, neural networks, or AI [^1] |
| **Predictive models** | "Predicts risk" or "forecasts symptoms" |
| **Clinical recommendations** | "We recommend seeing a therapist" |
| **Personalized interventions** | "Based on your data, try X" [^2] |
| **Symptom assessment** | "Your symptoms indicate..." |
| **Treatment management** | "Manages your condition" |
| **Diagnostic claims** | "Detects depression/anxiety" |
| **Risk scores** | "73% risk score" [^2] |
| **Triage** | Algorithmic triage to clinical care |
| **Normative language** | "Normal/abnormal", "healthy/unhealthy" |


***

## Example: Mental Health Monitoring App (Non-SaMD)

### **Acceptable Implementation**

```python
# Collect data
mood_log = {
    'date': '2026-05-31',
    'mood': 6,  # User self-reports 1-10
    'sleep_hours': 7,
    'exercise': True
}

# Store without change
datastore.append(mood_log)

# Descriptive analysis (easily verifiable)
avg_mood = sum([entry['mood'] for entry in datastore]) / len(datastore)
# Output: "Average mood: 6.2"

# Display trend (no interpretation)
# Output: "Mood over time: [line chart]"

# Simple filter (user selects)
# Output: "Show entries where mood < 5"
```

**What it shows:**

- ✅ "Average mood: 6.2 (range: 3-9)"
- ✅ "Mood decreased from 8 to 5 between Week 1-2"
- ✅ "45% of days reported poor sleep"
- ✅ "3 entries with mood < 4"

**What it does NOT show:**

- ❌ "Your mood is below normal" (normative)
- ❌ "This suggests depression" (interpretive)
- ❌ "Risk score: 73%" (predictive)
- ❌ "We recommend CBT" (recommendation)


### **Unacceptable Implementation (SaMD)**

```python
# AI analysis (automatically SaMD)
risk_score = ai_model.predict_risk(datastore)
# Output: "Risk score: 73%"

# Personalized recommendation
recommendation = ai_model.recommend_intervention(datastore)
# Output: "Based on your mood, try CBT exercise X"

# Interpretive flagging
if mood_trajectory < threshold:
    flag = "⚠️ Warning: Symptoms worsening"
```

**What it shows (SaMD):**

- ❌ "AI detects depression patterns"
- ❌ "Risk score: 73%"
- ❌ "We recommend CBT exercise X"
- ❌ "⚠️ Warning: Symptoms worsening"

***

## Exclusion Criteria (Australia TGA Example)

Digital mental health software can be **excluded from regulation** if it meets ALL conditions:[^3]


| Condition | Requirement |
| :-- | :-- |
| **1. Management** | Intended for management of any aspect of mental health |
| **2. Clinical guidelines** | Follows established clinical practice guidelines |
| **3. References** | Guidelines are referenced and displayed in tool |
| **4. User visibility** | User can clearly view the guidelines |

**If NOT all conditions met** → Software is regulated by TGA as medical device.[^3]

***

## Risk Mitigation Strategies

### 1. **Labeling \& Disclaimers**

```
DISCLAIMER: This tool is for general wellbeing purposes only.
It is NOT a medical device and is NOT intended for diagnosis,
treatment, or prevention of any mental health condition.
Consult a qualified healthcare professional for clinical concerns.
```


### 2. **User Education**

| Include | Purpose |
| :-- | :-- |
| "This is for personal tracking" | Clarifies wellness purpose |
| "Not for diagnosis" | Prevents medical use |
| "Consult professional for clinical concerns" | Directs users to care |
| "Data is for personal reflection" | Clarifies no clinical interpretation |

### 3. **Data Governance**

| Requirement | Implementation |
| :-- | :-- |
| **HIPAA compliance** | If handling protected health information [^8] |
| **GDPR compliance** | If EU users involved |
| **Informed consent** | Users know data will be collected for wellness tracking |
| **Data minimization** | Collect only what's needed [^9] |
| **Purpose limitation** | Use data only for stated wellness purpose [^9] |


***

## Summary: Key Boundaries to Maintain Wellness Status

| Boundary | Stay On This Side |
| :-- | :-- |
| **Purpose** | Wellness support, not medical management |
| **Claims** | "Supports wellbeing", not "treats symptoms" |
| **Data** | Stores/communicates without change |
| **Analysis** | Descriptive (counts, averages), not predictive |
| **AI/ML** | NO AI/ML (triggers SaMD) |
| **Output** | Raw data, not personalized recommendations |
| **Interpretation** | "What happened", not "what it means" |
| **Users** | General population, not diagnosed patients |

**Bottom line:** You can collect and analyze mental health data for wellness purposes as long as you:

1. **Don't use AI/ML** (automatically SaMD)
2. **Don't make medical claims** (diagnosis, treatment, prevention)
3. **Don't personalize/interpret** data (interactive output = SaMD)
4. **Don't recommend** clinical interventions (treatment = SaMD)
5. **Keep it descriptive** (what happened, not what it means)

If you need to cross into SaMD territory (e.g., for clinical decision support), you must comply with full regulatory requirements (CE/UKCA mark, clinical evidence, post-market surveillance, etc.).[^1][^2]
<span style="display:none">[^10][^11][^12][^13][^14]</span>

<div align="center">⁂</div>

[^1]: https://www.horizon.ac.uk/regulating-digital-mental-health-technologies/

[^2]: https://www.scarlet.cc/post/wellness-or-mental-health-samd-how-to-know-the-difference

[^3]: https://www.tga.gov.au/sites/default/files/digital-mental-health-software-based-medical-devices.pdf

[^4]: https://www.toucantoco.com/en/blog/avoid-bias-in-data-reporting

[^5]: https://eab.com/resources/tool/how-to-overcome-common-mistakes-in-dashboard-design/

[^6]: https://www.gov.uk/government/news/mhra-issues-new-guidance-for-people-using-mental-health-apps-and-technologies

[^7]: https://globalforum.diaglobal.org/issue/november-2024/mental-health-apps-regulation-and-validation-are-needed/

[^8]: https://mental.jmir.org/2023/1/e37225/PDF

[^9]: https://www.ciklum.com/blog/the-ethics-of-trend-prediction-balancing-ai-insights-with-consumer-privacy/

[^10]: https://www.health.wa.gov.au/~/media/Corp/Documents/Health-for/PAD/Archive/2024/Community-mental-health-activity/Mental-Health-Data-Collection-Data-Dictionary-2024.pdf

[^11]: https://www.iconplc.com/insights/digital-disruption/software-medical-device-samd/clinical-strategies-optimise-samd-treating-mental-health

[^12]: https://www.iconplc.com/insights/digital-disruption/clinical-strategies-optimise-samd-treating-mental-health

[^13]: https://pmc.ncbi.nlm.nih.gov/articles/PMC5483244/

[^14]: https://assets.publishing.service.gov.uk/media/67a08ff6c496e5d3ddafb6c4/2025.01.29_MHRA_guidance_on_DMHT_-_Device_characterisation__regulatory_qualification_and_classification.pdf

