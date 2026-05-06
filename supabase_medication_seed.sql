-- ============================================================
-- CognaSync — Medication Reference Seed
-- Run once in Supabase > SQL Editor
-- Safe to re-run (ON CONFLICT DO NOTHING)
-- ============================================================
-- Columns: name, category, common_dose, dose_unit,
--          typical_onset_hours, common_side_effects (JSONB),
--          notes (interaction_warnings shown in UI)
-- ============================================================

-- Add unique constraint on name if missing so ON CONFLICT works
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'medication_reference'::regclass AND contype = 'u'
      AND conname = 'medication_reference_name_key'
  ) THEN
    ALTER TABLE medication_reference ADD CONSTRAINT medication_reference_name_key UNIQUE (name);
  END IF;
END $$;

INSERT INTO medication_reference
  (name, category, common_dose, dose_unit, typical_onset_hours, common_side_effects, notes)
VALUES

-- ── SSRIs ──────────────────────────────────────────────────────────────────
('sertraline',    'SSRI', 50,  'mg', 336,
 '["nausea","insomnia","sexual dysfunction","diarrhea","dry mouth","dizziness","fatigue"]',
 'Avoid with MAOIs (serotonin syndrome). Use caution with tramadol, lithium, triptans, and anticoagulants.'),

('fluoxetine',    'SSRI', 20,  'mg', 336,
 '["nausea","insomnia","sexual dysfunction","anxiety","headache","dry mouth","diarrhea"]',
 'Very long half-life (~5 days). Strong CYP2D6 inhibitor — raises levels of many co-medications. 5-week washout required before MAOI. Avoid MAOIs.'),

('escitalopram',  'SSRI', 10,  'mg', 336,
 '["nausea","insomnia","sexual dysfunction","fatigue","dry mouth","sweating","diarrhea"]',
 'Dose-dependent QT prolongation — avoid other QT-prolonging drugs and high doses in elderly. Fewer CYP interactions than other SSRIs. Avoid MAOIs.'),

('citalopram',    'SSRI', 20,  'mg', 336,
 '["nausea","dry mouth","sweating","fatigue","insomnia","sexual dysfunction"]',
 'Max 20 mg/day if age >60 or hepatic impairment (QT prolongation risk). Avoid other QT-prolonging agents. Avoid MAOIs.'),

('paroxetine',    'SSRI', 20,  'mg', 336,
 '["nausea","sedation","weight gain","sexual dysfunction","constipation","dry mouth","discontinuation syndrome"]',
 'Strong CYP2D6 inhibitor. Short half-life — high discontinuation syndrome risk; taper slowly. Teratogenic risk. Avoid MAOIs.'),

('fluvoxamine',   'SSRI', 100, 'mg', 336,
 '["nausea","insomnia","sedation","sexual dysfunction","dry mouth"]',
 'Potent CYP1A2 and CYP3A4 inhibitor — markedly raises levels of clozapine, theophylline, tizanidine, and caffeine. Avoid MAOIs.'),

('vilazodone',    'SSRI / 5-HT1A partial agonist', 20, 'mg', 336,
 '["diarrhea","nausea","insomnia","dry mouth","dizziness","sexual dysfunction"]',
 'Take with food to increase absorption. Avoid MAOIs. CYP3A4 substrate.'),

('vortioxetine',  'Serotonin modulator', 10, 'mg', 168,
 '["nausea","constipation","dry mouth","sexual dysfunction","vomiting"]',
 'CYP2D6 substrate — adjust dose with strong CYP2D6 inhibitors (e.g., bupropion, fluoxetine). Avoid MAOIs.'),

-- ── SNRIs ──────────────────────────────────────────────────────────────────
('venlafaxine',   'SNRI', 75,  'mg', 168,
 '["nausea","insomnia","sexual dysfunction","hypertension","dry mouth","sweating","discontinuation syndrome"]',
 'Can raise blood pressure at higher doses — monitor BP. High discontinuation syndrome risk; taper slowly. Avoid MAOIs.'),

('duloxetine',    'SNRI', 60,  'mg', 168,
 '["nausea","dry mouth","constipation","fatigue","insomnia","sexual dysfunction","sweating"]',
 'CYP2D6 substrate/inhibitor. Avoid in significant hepatic impairment. Monitor BP. Avoid MAOIs.'),

('desvenlafaxine','SNRI', 50,  'mg', 168,
 '["nausea","dizziness","sweating","constipation","sexual dysfunction"]',
 'Active metabolite of venlafaxine. Similar interaction profile. Avoid MAOIs.'),

('levomilnacipran','SNRI', 40, 'mg', 168,
 '["tachycardia","hypertension","nausea","constipation","hyperhidrosis","sexual dysfunction"]',
 'Norepinephrine-selective SNRI. Monitor BP and heart rate. Avoid MAOIs.'),

-- ── Atypical antidepressants ────────────────────────────────────────────────
('bupropion',     'Atypical antidepressant', 150, 'mg', 168,
 '["insomnia","dry mouth","headache","nausea","agitation","constipation","tachycardia"]',
 'Lowers seizure threshold — contraindicated with seizure disorders, eating disorders, or benzodiazepine withdrawal. Strong CYP2D6 inhibitor. Stimulant-like properties. Avoid MAOIs.'),

('mirtazapine',   'Atypical antidepressant', 15,  'mg', 168,
 '["sedation","weight gain","increased appetite","dry mouth","dizziness","constipation"]',
 'H1 antihistamine mechanism — sedating, useful for insomnia and low appetite. Additive CNS depression with alcohol and benzodiazepines. Avoid MAOIs.'),

('trazodone',     'Atypical antidepressant', 50,  'mg', 48,
 '["sedation","orthostatic hypotension","dizziness","dry mouth","blurred vision","priapism"]',
 'Commonly used off-label for insomnia at 50–100 mg. Risk of priapism. Additive CNS depression. Avoid MAOIs. CYP3A4 substrate.'),

('nefazodone',    'Atypical antidepressant', 200, 'mg', 168,
 '["sedation","nausea","dry mouth","constipation","blurred vision","dizziness"]',
 'Potent CYP3A4 inhibitor — multiple drug interactions. Rare but serious hepatotoxicity. Avoid MAOIs and CYP3A4 substrates with narrow therapeutic index.'),

-- ── TCAs ───────────────────────────────────────────────────────────────────
('amitriptyline',  'Tricyclic antidepressant', 75, 'mg', 168,
 '["dry mouth","constipation","sedation","weight gain","orthostatic hypotension","blurred vision","urinary retention","QT prolongation"]',
 'High anticholinergic burden. QT prolongation risk. Lethal in overdose. Avoid MAOIs. Multiple drug interactions — CYP2D6 substrate.'),

('nortriptyline',  'Tricyclic antidepressant', 75, 'mg', 168,
 '["dry mouth","constipation","sedation","orthostatic hypotension","blurred vision","weight gain"]',
 'Less sedating than amitriptyline. QT prolongation risk. Monitor therapeutic drug levels. Avoid MAOIs. CYP2D6 substrate.'),

('clomipramine',   'Tricyclic antidepressant', 50, 'mg', 336,
 '["dry mouth","constipation","sedation","weight gain","sexual dysfunction","tremor","seizures"]',
 'First-line for OCD. Lowers seizure threshold more than other TCAs. Strong CYP2D6 inhibitor. Avoid MAOIs.'),

('imipramine',     'Tricyclic antidepressant', 50, 'mg', 168,
 '["dry mouth","constipation","sedation","orthostatic hypotension","weight gain","urinary retention","QT prolongation"]',
 'High anticholinergic and cardiac side-effect burden. Avoid MAOIs. CYP2D6 substrate. Lethal in overdose.'),

-- ── MAOIs ──────────────────────────────────────────────────────────────────
('phenelzine',     'MAOI', 45, 'mg', 336,
 '["orthostatic hypotension","insomnia","sedation","weight gain","sexual dysfunction","edema","hypertensive crisis with tyramine"]',
 'Strict tyramine-free diet required. Dangerous interactions: SSRIs, SNRIs, stimulants, most opioids, sympathomimetics, dextromethorphan. 2-week washout required before starting another antidepressant.'),

('tranylcypromine','MAOI', 30, 'mg', 336,
 '["insomnia","agitation","orthostatic hypotension","hypertensive crisis with tyramine","weight loss"]',
 'Same interaction and dietary restrictions as phenelzine. Has amphetamine-like stimulant activity. 2-week washout required.'),

('selegiline',     'MAOI', 6,  'mg', 336,
 '["insomnia","nausea","application-site reaction (patch form)","orthostatic hypotension"]',
 'Transdermal 6 mg/day patch requires no dietary restrictions. Oral high-dose: full MAOI restrictions apply. Drug interactions same as other MAOIs.'),

-- ── Mood stabilizers ────────────────────────────────────────────────────────
('lithium',        'Mood stabilizer', 300, 'mg', 336,
 '["tremor","polyuria","polydipsia","weight gain","cognitive dulling","hypothyroidism","acne","nausea"]',
 'Narrow therapeutic index — monitor serum levels (0.6–1.2 mEq/L), renal function, and TSH. NSAIDs, diuretics, and ACE inhibitors raise lithium levels to toxic range. Dehydration and low-sodium diet increase toxicity risk.'),

('lamotrigine',    'Mood stabilizer / anticonvulsant', 100, 'mg', 336,
 '["rash (may be severe)","dizziness","headache","diplopia","ataxia","nausea","insomnia"]',
 'Titrate slowly — rapid escalation causes Stevens-Johnson syndrome risk. Valproate approximately doubles lamotrigine levels (halve lamotrigine dose). Combined oral contraceptives reduce lamotrigine levels by ~50%.'),

('valproate',      'Mood stabilizer / anticonvulsant', 500, 'mg', 168,
 '["nausea","weight gain","hair loss","tremor","sedation","liver toxicity","thrombocytopenia"]',
 'Monitor LFTs and CBC. Teratogenic — use effective contraception. Roughly doubles lamotrigine levels. Interacts with carbamazepine and other anticonvulsants.'),

('carbamazepine',  'Mood stabilizer / anticonvulsant', 400, 'mg', 336,
 '["dizziness","ataxia","diplopia","nausea","leukopenia","hyponatremia","rash"]',
 'Potent CYP3A4 inducer — lowers levels of most antipsychotics, antidepressants, benzodiazepines, and oral contraceptives. Monitor CBC and sodium. Stevens-Johnson risk. Avoid clozapine (additive bone marrow suppression).'),

('oxcarbazepine',  'Anticonvulsant / mood stabilizer', 300, 'mg', 168,
 '["dizziness","diplopia","fatigue","hyponatremia","nausea","ataxia"]',
 'CYP3A4 inducer (weaker than carbamazepine). Hyponatremia risk — monitor sodium. Reduces OCP efficacy. Fewer drug interactions than carbamazepine.'),

-- ── Antipsychotics ──────────────────────────────────────────────────────────
('quetiapine',     'Atypical antipsychotic', 100, 'mg', 8,
 '["sedation","weight gain","orthostatic hypotension","dry mouth","constipation","metabolic syndrome","QT prolongation"]',
 'QT prolongation — avoid other QT-prolonging agents. CYP3A4 substrate. Monitor metabolic parameters (weight, glucose, lipids). Commonly used off-label for insomnia and anxiety.'),

('aripiprazole',   'Atypical antipsychotic', 10,  'mg', 168,
 '["akathisia","insomnia","nausea","headache","constipation","modest weight gain"]',
 'Partial D2 agonist. Less metabolic burden than most antipsychotics. CYP2D6 and CYP3A4 substrate. Akathisia is common. Monitor for tardive dyskinesia.'),

('risperidone',    'Atypical antipsychotic', 2,   'mg', 48,
 '["EPS / akathisia","prolactin elevation","weight gain","sedation","orthostatic hypotension","tardive dyskinesia"]',
 'High prolactin elevation. CYP2D6 substrate. QT prolongation risk. Higher EPS risk than most other atypicals. Monitor metabolic parameters.'),

('olanzapine',     'Atypical antipsychotic', 10,  'mg', 48,
 '["weight gain","sedation","metabolic syndrome","hyperglycemia","constipation","dyslipidemia"]',
 'Highest metabolic burden of atypicals — monitor weight, glucose, and lipids frequently. Additive CNS depression with other sedatives. Avoid MAOIs.'),

('ziprasidone',    'Atypical antipsychotic', 60,  'mg', 48,
 '["QT prolongation","insomnia","nausea","dizziness","akathisia","EPS"]',
 'Must be taken with ≥500 calories — absorption is highly food-dependent. QT prolongation — avoid combining with other QT-prolonging agents. Twice-daily dosing required.'),

('lurasidone',     'Atypical antipsychotic', 40,  'mg', 48,
 '["akathisia","nausea","sedation","EPS","insomnia","anxiety"]',
 'Must be taken with ≥350 calories. Low metabolic burden. CYP3A4 substrate — avoid strong inhibitors/inducers. Once-daily dosing.'),

('clozapine',      'Atypical antipsychotic', 200, 'mg', 168,
 '["agranulocytosis","sedation","weight gain","hypersalivation","myocarditis","seizures","metabolic syndrome","constipation"]',
 'Mandatory CBC monitoring (REMS program) — agranulocytosis risk. Avoid carbamazepine (additive bone marrow suppression). Fluvoxamine dramatically raises clozapine levels. QT prolongation. Constipation can be severe.'),

('haloperidol',    'Typical antipsychotic', 5,   'mg', 24,
 '["EPS","akathisia","tardive dyskinesia","QT prolongation","neuroleptic malignant syndrome","prolactin elevation","sedation"]',
 'High EPS risk. QT prolongation — avoid other QT-prolonging agents. NMS risk. CYP2D6 substrate. Use lowest effective dose.'),

('paliperidone',   'Atypical antipsychotic', 6,   'mg', 48,
 '["EPS / akathisia","prolactin elevation","weight gain","sedation","tachycardia","QT prolongation"]',
 'Active metabolite of risperidone. Renally cleared — adjust dose in renal impairment. High prolactin elevation. QT prolongation risk.'),

('brexpiprazole',  'Atypical antipsychotic', 2,   'mg', 168,
 '["akathisia","weight gain","somnolence","constipation","restlessness"]',
 'FDA-approved as adjunct for MDD and for schizophrenia. CYP2D6 and CYP3A4 substrate. Similar to aripiprazole. Monitor metabolic parameters.'),

('cariprazine',    'Atypical antipsychotic', 1.5, 'mg', 168,
 '["akathisia","EPS","weight gain","nausea","insomnia","somnolence"]',
 'CYP3A4 substrate. Long-acting active metabolite (DCAR). Dose-adjust with CYP3A4 inhibitors/inducers. Approved for schizophrenia and bipolar depression.'),

('asenapine',      'Atypical antipsychotic', 5,   'mg', 48,
 '["sedation","akathisia","oral hypoesthesia","weight gain","dizziness","EPS"]',
 'Sublingual administration only — do not swallow or take with food/water for 10 min. CYP1A2 substrate/inhibitor. Monitor metabolic parameters.'),

-- ── Benzodiazepines ─────────────────────────────────────────────────────────
('alprazolam',    'Benzodiazepine', 0.5, 'mg', 1,
 '["sedation","cognitive impairment","dependence","tolerance","rebound anxiety","memory impairment","falls"]',
 'High-potency, short half-life — higher abuse liability and discontinuation symptoms than long-acting benzos. Combined CNS/respiratory depression with opioids (potentially fatal). Do not abruptly discontinue after regular use.'),

('clonazepam',    'Benzodiazepine', 0.5, 'mg', 2,
 '["sedation","cognitive impairment","ataxia","dependence","tolerance","depression","memory impairment"]',
 'Long half-life — less rebound anxiety. Additive CNS/respiratory depression. Dependence risk with long-term use. Taper slowly on discontinuation.'),

('lorazepam',     'Benzodiazepine', 1,   'mg', 1,
 '["sedation","respiratory depression","dependence","anterograde amnesia","falls","cognitive impairment"]',
 'No active metabolites — preferred in hepatic impairment and elderly (though still Beers Criteria). Additive CNS/respiratory depression with opioids and alcohol. Dependence risk.'),

('diazepam',      'Benzodiazepine', 5,   'mg', 1,
 '["sedation","cognitive impairment","ataxia","dependence","tolerance","respiratory depression"]',
 'Very long half-life (20–100 h) with active metabolites — accumulates especially in elderly. Additive CNS/respiratory depression. Dependence risk with regular use.'),

('temazepam',     'Benzodiazepine', 15,  'mg', 0.5,
 '["sedation","dizziness","cognitive impairment","dependence","next-day hangover"]',
 'Short-acting — used for sleep initiation. Dependence risk. Additive CNS/respiratory depression. Avoid in elderly (Beers Criteria).'),

('oxazepam',      'Benzodiazepine', 15,  'mg', 2,
 '["sedation","dizziness","cognitive impairment","ataxia","dependence"]',
 'No active metabolites — safest benzo in hepatic impairment and elderly. Slow onset. Dependence and CNS depression risks apply.'),

-- ── Stimulants ──────────────────────────────────────────────────────────────
('methylphenidate','Stimulant', 10, 'mg', 1,
 '["appetite suppression","insomnia","anxiety","tachycardia","hypertension","headache","irritability"]',
 'Schedule II. Monitor cardiovascular status. Avoid in structural cardiac disease. Contraindicated with MAOIs. May worsen anxiety and tics.'),

('amphetamine',    'Stimulant', 10, 'mg', 1,
 '["appetite suppression","insomnia","anxiety","tachycardia","hypertension","irritability","dependence"]',
 'Schedule II. Absolute contraindication with MAOIs (hypertensive crisis). Monitor BP and HR. May worsen anxiety, tics, or psychosis. High abuse potential.'),

('lisdexamfetamine','Stimulant', 30, 'mg', 2,
 '["appetite suppression","insomnia","anxiety","tachycardia","hypertension","dry mouth","irritability"]',
 'Prodrug of d-amphetamine — activated by gut enzymes. Schedule II. Contraindicated with MAOIs. Cardiovascular monitoring required. Lower abuse potential than immediate-release amphetamines.'),

('dextroamphetamine','Stimulant', 10, 'mg', 1,
 '["appetite suppression","insomnia","anxiety","tachycardia","hypertension","dry mouth","dependence"]',
 'Schedule II. Same interaction profile as amphetamine. Contraindicated with MAOIs. High abuse potential.'),

('dexmethylphenidate','Stimulant', 5, 'mg', 1,
 '["appetite suppression","insomnia","anxiety","tachycardia","headache","abdominal pain"]',
 'D-enantiomer of methylphenidate. Schedule II. Same warnings and contraindications as methylphenidate.'),

('atomoxetine',   'Non-stimulant ADHD', 40, 'mg', 336,
 '["decreased appetite","nausea","dry mouth","insomnia","irritability","urinary hesitancy","mood lability"]',
 'Not a controlled substance. CYP2D6 substrate — fluoxetine, paroxetine, bupropion significantly raise levels; reduce dose. Monitor BP and HR.'),

('viloxazine',    'Non-stimulant ADHD', 100, 'mg', 24,
 '["somnolence","decreased appetite","nausea","irritability","headache"]',
 'CYP1A2 inhibitor — raises levels of caffeine, clozapine, and other CYP1A2 substrates. CYP3A4 inducer. Monitor for serotonergic effects.'),

('guanfacine',    'Alpha-2 agonist / non-stimulant ADHD', 1, 'mg', 168,
 '["sedation","dry mouth","hypotension","bradycardia","constipation","irritability on discontinuation"]',
 'Extended-release form used for ADHD. CYP3A4 substrate — adjust dose with inhibitors/inducers. Taper slowly on discontinuation. Additive hypotension with antihypertensives.'),

('clonidine',     'Alpha-2 agonist', 0.1, 'mg', 2,
 '["sedation","dry mouth","hypotension","bradycardia","rebound hypertension on discontinuation","constipation"]',
 'Rebound hypertension if abruptly discontinued — always taper. Additive hypotension. Used off-label for ADHD, anxiety, PTSD, and opioid/alcohol withdrawal. More sedating than guanfacine.'),

('modafinil',     'Wakefulness agent', 200, 'mg', 2,
 '["headache","nausea","anxiety","insomnia","dry mouth","decreased appetite"]',
 'CYP3A4 inducer — reduces efficacy of oral contraceptives and other CYP3A4 substrates. Lower abuse potential than amphetamines. Not indicated for primary insomnia.'),

('armodafinil',   'Wakefulness agent', 150, 'mg', 2,
 '["headache","nausea","dry mouth","insomnia","anxiety","dizziness"]',
 'R-enantiomer of modafinil with longer duration. Same CYP3A4 induction and interaction profile. Reduces OCP efficacy.'),

-- ── Sedative-hypnotics ──────────────────────────────────────────────────────
('zolpidem',      'Sedative-hypnotic', 5,   'mg', 0.5,
 '["sedation","amnesia","sleepwalking","rebound insomnia","falls","complex sleep behaviors"]',
 'Take immediately before bed with no subsequent obligations. Avoid in elderly — falls and delirium risk (Beers Criteria). Additive CNS depression with alcohol and other sedatives. Tolerance and dependence risk with nightly use.'),

('eszopiclone',   'Sedative-hypnotic', 2,   'mg', 0.5,
 '["unpleasant metallic or bitter taste","sedation","dizziness","dry mouth","complex sleep behaviors"]',
 'CYP3A4 substrate. Unpleasant taste in many users. Additive CNS depression with alcohol. Tolerance risk with nightly use.'),

('zaleplon',      'Sedative-hypnotic', 10,  'mg', 0.25,
 '["dizziness","amnesia","sedation","rebound insomnia","headache"]',
 'Very short duration (~1 hour) — can be taken as late as 4 h before scheduled wake time. Additive CNS depression. Lower tolerance risk than longer-acting agents.'),

('hydroxyzine',   'Antihistamine / anxiolytic', 25, 'mg', 1,
 '["sedation","dry mouth","blurred vision","constipation","urinary retention"]',
 'Non-habit-forming. Additive CNS depression with other sedatives. Anticholinergic side effects. QT prolongation at higher doses. Avoid in elderly (Beers Criteria — anticholinergic).'),

('melatonin',     'Sleep supplement', 0.5, 'mg', 0.5,
 '["daytime sleepiness","dizziness","headache","nausea"]',
 'Low interaction potential. Fluvoxamine markedly increases melatonin levels (CYP1A2). May potentiate CNS depressants. Use lowest effective dose (0.5–3 mg).'),

-- ── Anxiolytics ─────────────────────────────────────────────────────────────
('buspirone',     'Anxiolytic', 10, 'mg', 336,
 '["nausea","dizziness","headache","nervousness","insomnia","lightheadedness"]',
 'Non-benzodiazepine — no addiction or abuse potential. Takes 2–4 weeks for anxiolytic effect. CYP3A4 substrate — avoid grapefruit. Avoid MAOIs. Does not treat acute anxiety.'),

-- ── Beta-blockers ───────────────────────────────────────────────────────────
('propranolol',   'Beta-blocker', 10, 'mg', 1,
 '["bradycardia","hypotension","fatigue","bronchospasm","cold extremities","depression","sexual dysfunction"]',
 'Contraindicated in asthma and COPD. Masks hypoglycemia symptoms in insulin-dependent diabetes. Additive hypotension. CYP2D6 substrate. Do not abruptly discontinue. Used off-label for performance anxiety and tremor.'),

-- ── Anticonvulsants used in psychiatry ─────────────────────────────────────
('gabapentin',    'Anticonvulsant / adjunctive anxiolytic', 300, 'mg', 2,
 '["sedation","dizziness","ataxia","weight gain","peripheral edema","cognitive blunting","fatigue"]',
 'Increasing misuse reports — assess abuse history. Additive CNS depression with opioids, benzodiazepines, and alcohol. Respiratory depression risk when combined with opioids in patients with respiratory compromise.'),

('pregabalin',    'Anticonvulsant / anxiolytic', 75, 'mg', 2,
 '["sedation","dizziness","weight gain","peripheral edema","blurred vision","euphoria at higher doses"]',
 'Schedule V — misuse potential. Additive CNS/respiratory depression with benzodiazepines and opioids. FDA-approved for generalized anxiety disorder in Europe; off-label in US.'),

('topiramate',    'Anticonvulsant', 25, 'mg', 168,
 '["cognitive slowing","word-finding difficulty","appetite suppression","weight loss","kidney stones","paresthesias","metabolic acidosis"]',
 'CYP3A4 inducer — reduces OCP efficacy. Monitor bicarbonate levels. Used off-label for weight loss, alcohol use disorder, PTSD, and migraine prophylaxis.'),

-- ── Opioid antagonists ──────────────────────────────────────────────────────
('naltrexone',    'Opioid antagonist', 50, 'mg', 2,
 '["nausea","abdominal pain","headache","insomnia","anxiety","fatigue"]',
 'Contraindicated if currently using opioids — precipitates acute withdrawal. Blocks opioid analgesia. Used for AUD and OUD. Monthly injectable (Vivitrol) available. Monitor LFTs at high doses.'),

('naloxone',      'Opioid antagonist', 4, 'mg', 0.1,
 '["acute opioid withdrawal symptoms (if opioid-dependent)","nausea","tachycardia","sweating"]',
 'Rescue medication for opioid overdose. Extremely short-acting — repeat dosing often needed. Has no effect in absence of opioids.'),

-- ── Anticonvulsant / mood stabilizer ────────────────────────────────────────
('levetiracetam', 'Anticonvulsant', 500, 'mg', 24,
 '["irritability","aggression","depression","fatigue","dizziness","somnolence"]',
 'Renal excretion — adjust dose in renal impairment. Psychiatric side effects (irritability, mood changes) can be significant. Few pharmacokinetic interactions.'),

-- ── Adjunctive / other ──────────────────────────────────────────────────────
('lithium orotate','Dietary supplement', 5, 'mg', 168,
 '["nausea at high doses","fatigue","potential tremor at very high doses"]',
 'OTC supplement — much lower doses than prescription lithium carbonate. Limited clinical evidence at supplement doses. Avoid combining with prescription lithium.'),

('N-acetylcysteine','Antioxidant supplement', 600, 'mg', 24,
 '["nausea","vomiting","diarrhea","GI upset"]',
 'Used adjunctively for OCD, trichotillomania, addiction, and bipolar disorder. Low interaction profile. Avoid with nitroglycerin (profound hypotension).'),

('esketamine',    'NMDA antagonist / antidepressant', 56, 'mg', 2,
 '["dissociation","dizziness","nausea","somnolence","increased blood pressure","vertigo"]',
 'Intranasal administration in certified healthcare settings only (REMS). Rapid-acting for treatment-resistant depression. Monitor BP after each dose. Do not drive same day as dose.')

ON CONFLICT (name) DO NOTHING;
