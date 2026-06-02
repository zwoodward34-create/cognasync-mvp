<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Protocol Template: Bias Mitigation for Speech-Based Mental Health Screening Datasets


***

## **Protocol Title**

Bias Mitigation Protocol for Speech-Based Mental Health Screening Dataset Development and Validation

***

## **1. Study Overview**

### 1.1 Objective

To develop and validate a speech-based mental health screening dataset that minimizes selection bias, ensures demographic representativeness, and produces fair, generalizable models across all population subgroups.[^11][^12]

### 1.2 Scope

- **Target condition**: Depression, anxiety, PTSD, or other mental health conditions being screened
- **Speech modality**: Audio recordings from clinical interviews, phone calls, or in-person assessments
- **Intended population**: [Specify target clinical population]
- **Deployment setting**: [e.g., primary care, telehealth, community clinic]

***

## **2. Pre-Data Collection Phase**

### 2.1 Define Target Population Explicitly

| Requirement | Specification | Documentation |
| :-- | :-- | :-- |
| **Demographic parameters** | Age range, sex/gender, race/ethnicity, language, socioeconomic status | [Fill in your criteria] |
| **Clinical parameters** | Diagnostic criteria (DSM-5-TR/ICD-11), severity range, comorbidities | [Fill in your criteria] |
| **Geographic parameters** | Region, urban/rural, clinic type | [Fill in your criteria] |
| **Exclusion criteria** | Medical conditions affecting speech, non-native speakers, age limits | [List explicitly] |

**Rationale**: Clear inclusion/exclusion criteria prevent post-hoc filtering that introduces selection bias.[^11]

### 2.2 Sample Size Justification

| Parameter | Minimum Target | Justification |
| :-- | :-- | :-- |
| **Total sample size** | ≥100 participants (preferably ≥500) | Based on meta-analysis of 105 depression detection studies [^13] |
| **Depression prevalence** | 45-55% in sample | Balanced case-control design [^13] |
| **Subgroup minimums** | ≥30 participants per subgroup | Adequate power for subgroup analysis [^12] |
| **Gender balance** | 45-55% female/male | Avoid gender imbalance seen in DAIC-WoZ [^11] |
| **Race/ethnicity diversity** | At least 3-4 racial/ethnic groups | Capture demographic diversity [^12] |

### 2.3 Recruitment Strategy

| Recruitment Channel | Target % | Bias Mitigation Strategy |
| :-- | :-- | :-- |
| **Clinical sites** | [Specify %] | Multiple sites across different regions [^13] |
| **Community settings** | [Specify %] | Avoid clinic-only convenience sampling [^11] |
| **Online platforms** | [Specify %] | Document digital divide limitations [^11] |
| **Referral networks** | [Specify %] | Avoid self-selection bias [^11] |

**Key strategy**: Use **consecutive or random sampling** within recruitment channels (low risk of bias in 81% of high-quality studies).[^13]

***

## **3. Data Collection Phase**

### 3.1 Demographic Data Collection

| Variable | How to Collect | Options |
| :-- | :-- | :-- |
| **Sex assigned at birth** | Self-report | Male, Female, Intersex, Prefer not to answer |
| **Gender identity** | Self-report | Male, Female, Non-binary, Transgender, Genderqueer, Other (open text), Prefer not to answer |
| **Race/ethnicity** | Self-report | Multiple selections allowed; include "...of another race" option [^11][^12] |
| **Age** | Self-report | Exact age (continuous) |
| **Primary language** | Self-report | List all languages spoken; include dialect information [^11] |
| **Socioeconomic status** | Self-report | Income bracket, education level, employment status |
| **Geographic location** | Self-report | Urban/rural, region, state/country |
| **Disability status** | Self-report | Hearing impairment, speech impairment, other disabilities |

**Privacy note**: Collect identity labels sensitively; allow "prefer not to answer" for all demographic questions.[^11]

### 3.2 Clinical Data Collection

| Variable | Instrument | Ground Truth Standard |
| :-- | :-- | :-- |
| **Diagnostic status** | SCID-5, MINI, or CIDI | **Gold standard**: DSM-5-TR diagnosis [^13] |
| **Depression severity** | PHQ-9, HAM-D, or BDI | **Prefer**: Clinician-rated (HAM-D) over self-report [^13] |
| **Anxiety severity** | GAD-7, HAM-A | Specify cutoff for clinical significance |
| **Other disorders** | [Specify instruments] | Document all comorbidities |
| **Medication status** | Self-report | List all psychotropic medications |
| **Treatment history** | Self-report | Duration, type of treatment |

**Critical**: Use **clinical diagnosis** (DSM-5-TR/ICD-11) as ground truth when possible; self-report alone is insufficient for validation.[^13]

### 3.3 Speech Data Collection

| Parameter | Recommendation | Rationale |
| :-- | :-- | :-- |
| **Speech task** | Free speech (clinical interview) | 72.4% of studies; best ecological validity [^13] |
| **Recording quality** | 16+ kHz sampling, quiet environment | Standard for acoustic analysis [^13] |
| **Microphone type** | Document exactly (phone, mic model) | Measurement bias risk [^7] |
| **Recording duration** | Minimum 2-3 minutes | Short subsections unstable for PVI metrics [^14] |
| **Background noise** | Measure SNR; exclude if <15 dB | Noise affects acoustic features [^11] |
| **Task order** | Randomized or counterbalanced | Avoid order effects [^11] |
| **Language consistency** | Same language for all participants | Cross-language invalid [^13] |

**Documentation**: Record all environmental conditions, equipment specifications, and interviewer characteristics.[^11]

***

## **4. Data Processing Phase**

### 4.1 Preprocessing Pipeline

| Step | Action | Documentation Required |
| :-- | :-- | :-- |
| **Quality control** | Exclude recordings with <15 dB SNR, clipping, or artifacts | Document exclusion rate and reasons |
| **Speaker verification** | Confirm speaker identity matches demographic data | Track mismatches |
| **Segmentation** | Define speech boundaries consistently | Document segmentation method |
| **Feature extraction** | Use openSMILE, Praat, or librosa | Version number, parameter settings |
| **Missing data** | Document missing values; use multiple imputation | List imputation method |

**Bias risk**: 93.3% of studies have unclear data preprocessing documentation; document everything.[^13]

### 4.2 Label Assignment

| Decision | Rule | Justification |
| :-- | :-- | :-- |
| **Depression case** | SCID-5 diagnosis OR PHQ-9 ≥10 | Dual criteria increase validity [^13] |
| **Control** | No DSM-5 diagnosis, PHQ-9 <5 | Clear exclusion criteria [^13] |
| **Uncertain cases** | Create separate category | Don't exclude (78.1% exclusion is high risk) [^13] |
| **Multiple disorders** | Label all comorbidities | Don't hide comorbidity [^11] |

**Critical**: 81% of studies have unclear timing between speech test and reference standard; maintain ≤14-day interval.[^13]

***

## **5. Bias Assessment Phase**

### 5.1 Dataset Representativeness Audit

| Metric | Target | Current Status | Action If Below Target |
| :-- | :-- | :-- | :-- |
| **Age distribution** | Match census/target population | [Calculate %] | Stratified recruitment |
| **Gender balance** | 45-55% female/male | [Calculate %] | Targeted recruitment |
| **Race/ethnicity** | ≥3-4 groups, ≥10% each | [Calculate %] | Partner with diverse clinics |
| **Language diversity** | ≥2 languages if applicable | [Calculate %] | Collect in multiple languages |
| **SES distribution** | Match census/target population | [Calculate %] | Include community settings |
| **Geographic diversity** | ≥3 regions if possible | [Calculate %] | Multi-site recruitment |

**Use**: Compare dataset demographics to target population census data.[^12][^11]

### 5.2 Subgroup Performance Analysis

| Subgroup | N | Accuracy | Sensitivity | Specificity | 95% CI |
| :-- | :-- | :-- | :-- | :-- | :-- |
| **Overall** | [Total] | [Value] | [Value] | [Value] | [CI] |
| **Female** | [N] | [Value] | [Value] | [Value] | [CI] |
| **Male** | [N] | [Value] | [Value] | [Value] | [CI] |
| **Non-binary/Other** | [N] | [Value] | [Value] | [Value] | [CI] |
| **White** | [N] | [Value] | [Value] | [Value] | [CI] |
| **Black/African American** | [N] | [Value] | [Value] | [Value] | [CI] |
| **Hispanic/Latino** | [N] | [Value] | [Value] | [Value] | [CI] |
| **Asian** | [N] | [Value] | [Value] | [Value] | [CI] |
| **Age <30** | [N] | [Value] | [Value] | [Value] | [CI] |
| **Age 30-50** | [N] | [Value] | [Value] | [Value] | [CI] |
| **Age >50** | [N] | [Value] | [Value] | [Value] | [CI] |

**Threshold**: If accuracy differs by >10% across subgroups, flag as bias risk.[^12]

### 5.3 Statistical Bias Tests

| Test | Purpose | Threshold for Concern |
| :-- | :-- | :-- |
| **Cochran's Q** | Test heterogeneity across subgroups | P ≤ 0.05 = significant bias risk [^13] |
| **I² statistic** | Proportion of variation due to true heterogeneity | I² > 50% = moderate bias risk [^13] |
| **Chi-square test** | Compare demographic proportions | P ≤ 0.05 = non-representative |
| **t-test/ANOVA** | Compare acoustic features by subgroup | P ≤ 0.05 after Bonferroni correction [^12] |
| **F1-score difference** | Compare model performance | Difference >10% = bias concern [^12] |


***

## **6. Bias Mitigation Strategies**

### 6.1 Pre-Processing (Data-Level)

| Strategy | Implementation | When to Use |
| :-- | :-- | :-- |
| **Oversampling** | Use SMOTE or similar for underrepresented groups | Minority groups <10% of sample |
| **Undersampling** | Reduce majority group to balance | When oversampling insufficient |
| **Stratified splitting** | Maintain subgroup proportions in train/test | Always use for validation |
| **Data augmentation** | Add synthetic samples for underrepresented groups | When data scarce |
| **Feature normalization** | Normalize features within subgroups | When acoustic features differ by demographic |

**Warning**: Balancing is a **supplement**, not a substitute, for better sampling.[^12]

### 6.2 In-Processing (Model-Level)

| Strategy | Implementation | Algorithm |
| :-- | :-- | :-- |
| **Fairness constraints** | Add fairness penalty to loss function | SVM, Neural Networks |
| **Adversarial debiasing** | Train adversary to remove demographic information | Neural Networks [^15] |
| **Multi-task learning** | Predict both outcome and subgroup | Neural Networks |
| **Class weighting** | Weight minority class higher | All algorithms |
| **Domain adversarial training** | Remove gender/race bias from features | Neural Networks [^15] |

**Recent finding**: Domain adversarial training reduces gender bias in speech-based depression detection.[^15]

### 6.3 Post-Processing (Output-Level)

| Strategy | Implementation | Trade-off |
| :-- | :-- | :-- |
| **Threshold adjustment** | Different thresholds per subgroup | May reduce overall accuracy |
| **Score calibration** | Calibrate scores separately per subgroup | Requires validation data |
| **Ensemble voting** | Combine multiple models with different biases | Increases complexity |
| **Uncertainty quantification** | Flag low-confidence predictions for review | May increase false positives |


***

## **7. Validation Phase**

### 7.1 Internal Validation

| Method | Requirements | Reporting |
| :-- | :-- | :-- |
| **K-fold cross-validation** | K=5 or K=10, stratified by subgroup | Report mean ± SD across folds |
| **Nested cross-validation** | Outer loop for evaluation, inner for tuning | Prevents overfitting [^13] |
| **Hold-out validation** | 20-30% reserved test set | Never used for training |
| **Bootstrap validation** | 1000+ resamples | Report bias-corrected estimates |

### 7.2 External Validation

| Validation Type | Requirements | Acceptance Criteria |
| :-- | :-- | :-- |
| **Temporal** | Data collected at different time | Accuracy drop ≤10% [^13] |
| **Site** | Different clinic/location | Accuracy drop ≤15% [^13] |
| **Population** | Different demographic group | Accuracy drop ≤20% [^13] |
| **Cross-cultural** | Different culture/language | Accuracy ≥70% (58% is failure) [^16] |
| **Independent** | Separate research team | Gold standard for clinical readiness [^13] |

**Critical**: If cross-cultural accuracy drops below 58%, the model is at/below chance for that population.[^16]

### 7.3 QUADAS-2 Risk of Bias Assessment

| Domain | Signaling Questions | Risk Level |
| :-- | :-- | :-- |
| **Patient Selection** | -  Consecutive/random sampling?<br>-  No inappropriate exclusions?<br>-  Sample size ≥100? | Low / High / Unclear [^17] |
| **Index Test** | -  AI model thoroughly described?<br>-  Features clearly outlined?<br>-  Blinded to outcome? | Low / High / Unclear [^17] |
| **Reference Standard** | -  Appropriate diagnostic standard?<br>-  Outcome defined consistently?<br>-  Blinded to speech data? | Low / High / Unclear [^17] |
| **Flow and Timing** | -  Interval ≤14 days?<br>-  All participants included?<br>-  Same reference standard? | Low / High / Unclear [^17] |

**Target**: ≤1 domain with high risk of bias (47.6% of studies exceed this).[^13]

***

## **8. Reporting Phase**

### 8.1 Minimum Reporting Requirements

| Category | Required Information |
| :-- | :-- |
| **Study characteristics** | Year, country, publication type, sample size, age, gender, depression prevalence [^13] |
| **Recruitment** | Source, method, inclusion/exclusion criteria, response rate [^11] |
| **Demographics** | Complete table with all collected variables [^11][^12] |
| **Clinical data** | Diagnostic instrument, rater training, inter-rater reliability [^13] |
| **Speech features** | All features extracted (not just best), software versions [^13] |
| **AI algorithms** | Algorithm type, hyperparameters, training procedure [^13] |
| **Performance metrics** | Accuracy, sensitivity, specificity, precision with 95% CI [^13] |
| **Subgroup analysis** | Performance by gender, race/ethnicity, age, language [^12] |
| **Validation method** | Cross-validation type, train/test split, external validation |
| **Bias mitigation** | All strategies used, effectiveness quantified [^11] |

**Best practice**: Report **both highest and lowest performance** across experiments.[^13]

### 8.2 Dataset Card Template

```markdown
# Dataset Card: [Dataset Name]

## Overview
- **Purpose**: [Clinical screening, research, etc.]
- **Condition**: [Depression, anxiety, etc.]
- **Language(s)**: [List all]
- **Collection period**: [Dates]

## Demographics
| Group | N | % |
|-------|---|---|
| Total | [N] | 100% |
| Female | [N] | [%] |
| Male | [N] | [%] |
| Non-binary | [N] | [%] |
| White | [N] | [%] |
| Black | [N] | [%] |
| [Other] | [N] | [%] |

## Clinical Characteristics
- Depression prevalence: [%]
- Mean PHQ-9: [Value] (SD: [Value])
- Mean HAM-D: [Value] (SD: [Value])

## Data Collection
- **Speech task**: [Free speech, reading, etc.]
- **Recording quality**: [kHz, bit depth]
- **Environment**: [Clinic, phone, home]
- **Interviewer**: [Details]

## Limitations
- [List all known biases, underrepresented groups, etc.]

## Use Cases
- **Intended**: [Clinical screening, research]
- **Not intended**: [Standalone diagnosis, cross-cultural use without validation]

## Citation
[Full citation]
```


***

## **9. Quality Assurance Checklist**

### Pre-Collection

- [ ] Target population explicitly defined[^11]
- [ ] Sample size justified (≥100, preferably ≥500)[^13]
- [ ] Recruitment strategy avoids convenience sampling[^11]
- [ ] Inclusion/exclusion criteria documented[^11]
- [ ] Demographic variables selected[^11]
- [ ] Ground truth standard selected (DSM-5-TR preferred)[^13]


### During Collection

- [ ] Consecutive/random sampling used (81% of high-quality studies)[^13]
- [ ] Demographic data collected for all participants[^11]
- [ ] Clinical assessment completed within 14 days of speech recording[^13]
- [ ] Recording quality meets standards (≥16 kHz, SNR ≥15 dB)[^13]
- [ ] All participants included in analysis (not 78.1% exclusion)[^13]


### Post-Collection

- [ ] Dataset representativeness audit completed[^12][^11]
- [ ] Subgroup performance analysis completed[^12]
- [ ] Bias tests conducted (Cochran's Q, I², chi-square)[^12][^13]
- [ ] Bias mitigation strategies implemented[^11]
- [ ] External validation performed[^13]
- [ ] QUADAS-2 risk of bias assessment completed[^17]
- [ ] Dataset card created[^11]

***

## **10. Ongoing Monitoring**

### Post-Deployment Monitoring

| Metric | Frequency | Threshold for Action |
| :-- | :-- | :-- |
| **Subgroup accuracy** | Quarterly | Drop >5% from baseline [^12] |
| **Demographic distribution** | Quarterly | Shift >10% from target [^11] |
| **False positive rate** | Monthly | Difference >10% across subgroups [^12] |
| **False negative rate** | Monthly | Difference >10% across subgroups [^12] |
| **Clinical outcomes** | Annually | Disparate impact detected |

**Action plan**: If bias is detected, retrain with updated data from underrepresented groups.[^12][^11]

***

## **11. Tools and Resources**

### Bias Detection Tools

- **Holistic AI Library**: Python toolkit for bias measurement and mitigation[^7]
- **AIF360 (IBM)**: AI Fairness 360 toolkit for fairness metrics[^7]
- **Fairness Indicators (Google)**: TensorFlow-based fairness evaluation[^7]
- **LinkedIn Fairness Toolkit**: Scala/Spark library for large-scale bias assessment[^7]


### Speech Processing Tools

- **openSMILE**: Speech feature extraction (used in 86.7% of studies)[^13]
- **Praat**: Acoustic analysis software[^13]
- **librosa**: Python audio processing library[^13]


### Diagnostic Standards

- **SCID-5**: Structured Clinical Interview for DSM-5[^13]
- **MINI**: Mini International Neuropsychiatric Interview[^13]
- **PHQ-9**: Patient Health Questionnaire-9[^13]
- **HAM-D**: Hamilton Depression Rating Scale[^13]

***

## **12. Approval and Sign-Off**

| Role | Name | Signature | Date |
| :-- | :-- | :-- | :-- |
| **Principal Investigator** |  |  |  |
| **Data Scientist** |  |  |  |
| **Clinical Lead** |  |  |  |
| **Ethics Reviewer** |  |  |  |
| **Bias Audit Lead** |  |  |  |


***

## **Key References**

1. Grabe \& Low (2002). Durational variability in speech and the rhythm class hypothesis.[^18]
2. Systematic review of 105 depression detection studies (2025).[^13]
3. Deconstructing demographic bias in speech-based ML (2024).[^12]
4. Promoting Fairness and Diversity in Speech Datasets (2024).[^11]
5. QUADAS-2: Revised tool for quality assessment (2011).[^19][^17]
6. Cross-cultural validation study (2025).[^16]

***

**Protocol Version**: 1.0
**Last Updated**: May 31, 2026
**Next Review**: [Date]

This protocol should be adapted to your specific clinical context, target population, and available resources while maintaining the core principles of representativeness, transparency, and subgroup fairness.
<span style="display:none">[^1][^10][^2][^3][^4][^5][^6][^8][^9]</span>

<div align="center">⁂</div>

[^1]: https://genai.illinois.edu/best-practice-bias-mitigation/

[^2]: https://www.theblackprintinc.com/7-forms

[^3]: https://healthra.org/resources/bias-mitigation-in-peer-review-training-for-reviewers/

[^4]: https://www.brimco.io/terms/bias-mitigation-protocol/

[^5]: https://www.meegle.com/en_us/advanced-templates/ai_requirements_development_process/data_bias_monitoring_protocol_template

[^6]: https://www.meegle.com/en_us/advanced-templates/prompt_tuning/logit_bias_modification_protocol

[^7]: https://www.holisticai.com/blog/technical-resources-bias-mitigation

[^8]: https://www.linkedin.com/pulse/assumption-bias-mitigation-protocol-copy-paste-your-ai-sorensen--ipurc

[^9]: https://support.textio.com/s/article/Bias-Mitigation-Protocols-and-Practices-for-our-AI-Development-at-Textio

[^10]: https://pmc.ncbi.nlm.nih.gov/articles/PMC11751650/

[^11]: https://arxiv.org/html/2406.04116v1

[^12]: https://pmc.ncbi.nlm.nih.gov/articles/PMC11306200/

[^13]: https://mental.jmir.org/2025/1/e67802

[^14]: https://pmc.ncbi.nlm.nih.gov/articles/PMC4240963/

[^15]: https://arxiv.org/html/2505.03359v1

[^16]: https://www.academia.edu/83264892/Cross_Cultural_Depression_Recognition_from_Vocal_Biomarkers

[^17]: https://pubmed.ncbi.nlm.nih.gov/22007046/

[^18]: http://wwwhomes.uni-bielefeld.de/~gibbon/AK-Phon/Rhythmus/Grabe/Grabe_Low-reformatted.pdf

[^19]: https://www.acpjournals.org/doi/10.7326/0003-4819-155-8-201110180-00009

