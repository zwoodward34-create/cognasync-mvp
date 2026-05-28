# Product

## Register

product

## Users

Two distinct user types sharing the same codebase:

**Patients** — people actively managing mental health day-to-day. They log mood, sleep, stress, medication timing, and journal entries. They use the app between appointments, often on mobile, often in private moments. They want to feel understood and in control, not monitored or judged. The app is a tool they carry, not a dashboard they manage.

**Providers** — clinicians (psychiatrists, therapists, prescribers) reviewing patient data before and between appointments. They scan multiple patients. They need structured, specific, flagged-first content. They want signal, not sentiment. The Intel layer (transcript analysis, briefs) is built for them.

## Product Purpose

CognaSync is a behavioral intelligence platform. It tracks what patients do and feel, identifies patterns in that data, and surfaces those patterns in plain language — to patients so they can prepare for appointments, and to providers so they can have more informed clinical conversations.

The AI explains patterns. Humans make clinical decisions. The product is the bridge between self-tracked data and the clinical relationship; it is not a replacement for either.

Success looks like: a patient arrives at their appointment with a pre-visit summary that actually changes the conversation. A provider opens the dashboard and immediately sees who needs attention.

## Brand Personality

Calm, clinical, trustworthy.

Voice: precise without being cold. Direct without being blunt. Human without being chatty. The product speaks the way a thoughtful clinician does when they're explaining something clearly: no hedging, no filler, no cheerfulness that undercuts the weight of the subject.

Tone varies by surface: warmer for patients (they're in a vulnerable moment), more data-forward for providers (they need to extract signal fast).

## Anti-references

**Generic SaaS dashboards** — no hero-metric cards, no identical icon-heading-text card grids, no navy-sidebar admin chrome, no gradient accents on numbers. CognaSync is not a KPI tracker.

**Clinical EHR software (Epic, Cerner)** — not cold, sterile, or form-heavy. Not the thing that makes patients feel like a record number. Not a sea of fields and tabs.

## Design Principles

1. **Data has weight.** A mood score of 3.2 means something real. The interface should make that legible, not pretty. Numbers are not decoration; they are the product.

2. **Calm is earned, not assumed.** The visual restraint should come from the confidence of good information architecture, not from avoiding commitment. Whitespace earns its place; it does not substitute for decisions.

3. **Two audiences, one codebase.** Patient surfaces are human-first, warm where warmth matters, sparse where cognitive load matters. Provider surfaces are data-first, structured, flagged. Never mix the registers on the same screen.

4. **Trust through specificity.** Vague reassurance erodes trust. Specific numbers build it. "Your mood averaged 4.2 over 14 days" is trustworthy. "You've been doing okay" is not. The design should signal precision at every layer: typography, spacing, layout all suggest rigor.

5. **Persistence, not urgency.** This is a chronic-care tool used every day, not a crisis intervention tool. The UI should feel sustainable and returnable, not alarming or gamified.

## Accessibility & Inclusion

WCAG AA minimum. High contrast text on all surfaces. Reduced-motion support for transitions (patients may be in sensory-sensitive states). Touch targets minimum 44px on mobile. No color-only encoding for clinical signals (always paired with text label or icon).
