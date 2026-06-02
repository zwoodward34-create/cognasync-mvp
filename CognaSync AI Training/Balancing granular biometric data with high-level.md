<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Balancing granular biometric data with high-level trends

Balancing granular biometric data with high-level trends requires a **hierarchical visualization strategy** that lets users see the forest (patterns) before the trees (individual data points), while providing **smooth, intuitive pathways** to deeper detail when clinically relevant.

## The Core Challenge

| Granular Data | High-Level Trends |
| :-- | :-- |
| Raw sensor readings (e.g., every accelerometer sample, every heartbeat) | Aggregated patterns (e.g., daily step count, average HRV) |
| High fidelity but **overwhelming** | Clear patterns but may **miss important details** |
| Useful for **investigation** | Useful for **screening and monitoring** |
| **Storage-intensive** | **Storage-efficient** |

The goal is to show **both** without overwhelming clinicians or obscuring clinically meaningful details.[^1]

## Multi-Layer Aggregation Strategy

### **Layer 1: Raw Data (Granular Level)**

| Data Type | Example | Use Case |
| :-- | :-- | :-- |
| **Accelerometer** | 100 Hz samples (x, y, z axes) | Detecting falls, precise movement patterns |
| **Heart rate** | Every beat (RR intervals) | HRV calculation, arrhythmia detection |
| **EDA** | Skin conductance every second | Stress spikes, flashbacks (PTSD) [^2] |
| **GPS** | Location every 1–5 seconds | Detailed movement tracking, geofencing |

**When to show:** Only when investigating specific anomalies, validating algorithm accuracy, or進行 research analysis.[^1]

### **Layer 2: Aggregated Metrics (Trend Level)**

| Aggregation | Example | Clinical Value |
| :-- | :-- | :-- |
| **Daily totals** | Steps/day, minutes of sleep, avg HR | Compare day-to-day changes [^1] |
| **Hourly averages** | HR per hour, activity per hour | Identify circadian patterns [^2] |
| **Weekly summaries** | 7-day moving average, variability | Smooth noise, reveal underlying trends [^3] |
| **Statistical summaries** | Mean, median, SD, min, max | Quantify variability and stability [^4] |

**When to show:** Default view for clinical monitoring; what clinicians need for 95% of decisions.[^5]

### **Layer 3: Derived Features (Insight Level)**

| Feature | Calculation | Clinical Significance |
| :-- | :-- | :-- |
| **Z-scores** | (current − baseline) / baseline SD | Standardized deviation from normal [^6] |
| **Percent change** | (current − baseline) / baseline × 100% | Simple clinical interpretation [^7] |
| **Trend direction** | Slope of linear regression over time | Increasing, decreasing, stable [^6] |
| **Variability index** | Coefficient of variation (SD/mean) | High variability = instability [^6] |

**When to show:** Key insights in dashboard highlights; contextual information.[^5]

## Practical Implementation Frameworks

### **1. Progressive Disclosure Design**

```
┌─────────────────────────────────────────────────────────────┐
│ SUMMARY VIEW (High-Level Trends)                           │
│ ┌───────────────────────────────────────────────────────┐  │
│ │ MOOD: 4/10 ↓ 30% from baseline (5-day downward trend)│  │
│ │ SLEEP: 6 hrs ↓ 25% (irregular, 3-night alert)       │  │
│ │ ACTIVITY: 2000 steps ↓ 40% (7-day decline)          │  │
│ │ HRV: 45ms ↓ 20% (stable)                             │  │
│ └───────────────────────────────────────────────────────┘  │
│ [View Details] [Export Report] [Add Note]                  │
└─────────────────────────────────────────────────────────────┘
                    ↓ Click "View Details"
┌─────────────────────────────────────────────────────────────┐
│ TREND VIEW (Aggregated Metrics)                            │
│ ┌───────────────────────────────────────────────────────┐  │
│ │ Line chart: 30-day trend with baseline overlay       │  │
│ │ • Daily points (not raw data)                        │  │
│ │ • 7-day moving average                               │  │
│ │ • Event markers (medication changes, therapy)        │  │
│ └───────────────────────────────────────────────────────┘  │
│ ┌───────────────────────────────────────────────────────┐  │
│ │ Heatmap: Sleep by hour of day (weekly avg)           │  │
│ └───────────────────────────────────────────────────────┘  │
│ [View Raw Data] [Download CSV] [Report Anomaly]            │
└─────────────────────────────────────────────────────────────┘
                    ↓ Click "View Raw Data"
┌─────────────────────────────────────────────────────────────┐
│ RAW DATA VIEW (Granular Level)                             │
│ ┌───────────────────────────────────────────────────────┐  │
│ │ Table: Individual data points (expandable)           │  │
│ │ Date | Time | HR | HRV | Steps | Location | EDA     │  │
│ ├───────────────────────────────────────────────────────┤  │
│ │ 03/15│ 2:00am│82 │42ms│ 0    │ Home    │ 2.5μS     │  │
│ │ 03/15│ 2:05am│78 │45ms│ 0    │ Home    │ 2.3μS     │  │
│ │ ...                                                  │  │
│ └───────────────────────────────────────────────────────┘  │
│ [Back to Trends] [Export All Data] [Report Issue]          │
└─────────────────────────────────────────────────────────────┘
```

**Key principle:** Users start with high-level trends, then drill down to details only when needed.[^8]

### **2. Smart Aggregation with Context**

Rather than showing all raw data, use **intelligent aggregation** that preserves clinically relevant information:


| Time Period | Aggregation Method | Retained Information |
| :-- | :-- | :-- |
| **Per-second** | Average HR, activity count | Smoothed signal, removes noise |
| **Per-minute** | Min, max, mean, SD | Variability within minute |
| **Per-hour** | Trend line, peak detection | Hourly patterns, circadian rhythms |
| **Per-day** | Total steps, sleep duration, avg HRV | Daily summaries for trend analysis [^1] |

**Example:** Instead of storing 86,400 heart rate readings per day, store:

- Daily average HR
- Daily min/max HR
- Daily HRV (RMSSD)
- Time spent in HR zones (resting, moderate, high)

This reduces storage by **99.9%** while preserving clinically meaningful information.[^1]

### **3. Anomaly-Driven Detail Display**

Show granular data **only when anomalies are detected**:

```
HIGH-LEVEL ALERT
┌─────────────────────────────────────────────────────┐
│ ⚠️  ALERT: Unusual sleep pattern detected           │
│ • Sleep duration: 3 hrs (↓ 50% from baseline)      │
│ • Bedtime: 3:47 AM (2.5 hrs later than usual)      │
│ • Sleep fragmentation: 4 awakenings                │
│                                                     │
│ [View Raw Sleep Data] [Dismiss] [Add Note]          │
└─────────────────────────────────────────────────────┘
                    ↓ Click "View Raw Sleep Data"
GRANULAR DETAIL
┌─────────────────────────────────────────────────────┐
│ Sleep Stage Timeline (3/15/2026)                   │
│                                                     │
│ 10pm ──▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓     │
│ 11pm ──▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓     │
│ 12am ──▓▓▓▓▓▓▓▓▓░░░░░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  │
│  1am ──░░░░░▓▓▓▓▓▓▓░░░░░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░  │
│  2am ──░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│  3am ──░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│  4am ──▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓    │
│ Legend: ▓▓ = Deep Sleep, ░░ = Awake                │
│                                                     │
│ Hourly Heart Rate: 12am=78, 1am=82, 2am=75...      │
└─────────────────────────────────────────────────────┘
```

This approach:

- **Reduces cognitive load** by not showing raw data by default
- **Preserves investigability** when something is unusual
- **Focuses attention** on clinically relevant anomalies[^1]


## Technical Implementation Strategies

### **1. Data Preprocessing Pipeline**

```
Raw Sensor Data (100 Hz)
        ↓
Quality Filtering (remove outliers, artifacts)
        ↓
Feature Extraction (HRV, steps, sleep stages)
        ↓
Aggregation (hourly → daily → weekly)
        ↓
Statistical Summary (mean, SD, trend, percentiles)
        ↓
Visualization Layer (trends, alerts, summaries)
```

**Key insight:** Do aggregation **at data ingestion time**, not at query time, to reduce real-time processing load.[^1]

### **2. Multi-Resolution Storage**

| Time Range | Storage Resolution | Storage Size |
| :-- | :-- | :-- |
| **Last 7 days** | Per-minute aggregates | ~100 KB/day |
| **Last 30 days** | Per-hour aggregates | ~10 KB/day |
| **Last 90 days** | Daily summaries | ~1 KB/day |
| **Last 2 years** | Weekly summaries | ~100 bytes/day |
| **Raw data** | Only on-demand or for flagged events | Variable |

**Example:** For heart rate monitoring:

- Store raw RR intervals for **last 24 hours** only
- Store 1-minute averages for **last 7 days**
- Store 1-hour averages for **last 30 days**
- Store daily HR/HRV for **indefinite period**

This balances **storage efficiency** with **investigability**.[^1]

### **3. Smart Sampling for Visualization**

When displaying long time ranges, use **progressive sampling**:


| Time Range | Sampling Method | Number of Points |
| :-- | :-- | :-- |
| **24 hours** | Show all 1440 minutes | 1,440 points |
| **7 days** | Show 1 point per 15 min | 672 points |
| **30 days** | Show 1 point per hour | 720 points |
| **90 days** | Show 1 point per 6 hours | 360 points |
| **1 year** | Show daily averages | 365 points |

**Principle:** Maintain **visual consistency** (similar number of points) across different time scales for better readability.[^3]

## Clinical Context Integration

### **When Granular Data Matters**

| Clinical Scenario | Granular Data Needed | High-Level Sufficient |
| :-- | :-- | :-- |
| **Investigating anomalies** | Raw EDA spikes during sleep | Daily sleep summary |
| **Medication timing effects** | Hourly HR changes after dose | Daily average HR |
| **PTSD flashbacks** | Per-minute EDA/HR nighttime surges | Nighttime average HRV |
| **Mania onset** | Hourly activity/sleep pattern changes | Daily activity count |
| **Routine monitoring** | Daily HRV, sleep duration | Weekly averages |

**Rule of thumb:** Show granular data when investigating **specific clinical questions**, not for routine monitoring.[^2]

### **When High-Level Trends Are Sufficient**

| Use Case | Appropriate Aggregation |
| :-- | :-- |
| **Screening for relapse** | 7-day moving averages of activity, sleep |
| **Treatment response** | Weekly symptom scores vs. baseline |
| **General wellness tracking** | Daily step count, sleep hours |
| **Session preparation** | Summary metrics for last 2 weeks |
| **Patient education** | Simple trend lines, progress bars |

## Privacy and Security Considerations

| Concern | Mitigation Strategy |
| :-- | :-- |
| **Re-identification risk** | Raw accelerometry can re-identify individuals with 96% accuracy [^9] |
| **Granular data storage** | Store raw data only for short periods; aggregate longer-term |
| **Data sharing** | Share aggregated metrics, not raw sensor data |
| **Consent** | Clearly explain what granular data is collected and how long it's stored [^9] |

## Dashboard Design Patterns

### **Pattern 1: Sparkline + Detail on Hover**

```
Daily Activity Summary
Mon ▂▃▄▅▆ 2000  ↑  [hover: 2:30pm peak, 150 steps/hr]
Tue ▂▃▄▅▇ 2200  ↑  [hover: 3:00pm peak, 180 steps/hr]
Wed ▂▃▅▆▉ 2500  ↑  [hover: 2:00pm peak, 200 steps/hr]
Thu ▂▃▄▅▆ 2000  ↓  [hover: 1:00pm peak, 150 steps/hr]
Fri ▂▂▃▄▅ 1500  ↓  [hover: 2:00pm peak, 120 steps/hr]
```

**Benefits:** Shows trend (sparkline) + exact value + detailed info on hover without clutter.[^5]

### **Pattern 2: Aggregated Chart with Drill-Down**

```
Main Chart (30-day trend):
Daily HRV ──○────○────○────○────○────○────○────○────○
           50   48   45   47   44   42   40   43   41

Click on point → Drill-down to hourly breakdown:
HRV by Hour ──▓▓░░▓▓▓▓░░▓▓▓▓░░▓▓▓▓░░▓▓▓▓
              12am 3am  6am  9am 12pm 3pm
```

**Benefits:** Shows both long-term trend and immediate detail when needed.[^5]

### **Pattern 3: Faceted View (Multiple Time Scales)**

```
┌───────────────────┬───────────────────┬───────────────────┐
│ Last 24 Hours     │ Last 7 Days       │ Last 30 Days      │
│ (per-minute)      │ (daily avg)       │ (daily avg)       │
│ ┌───────────────┐ │ ┌───────────────┐ │ ┌───────────────┐ │
│ │ HR: 78-82 bpm │ │ │ HR: 75-80 bpm │ │ │ HR: 72-85 bpm │ │
│ │ HRV: 45ms     │ │ │ HRV: 42-48ms  │ │ │ HRV: 38-52ms  │ │
│ └───────────────┘ │ └───────────────┘ │ └───────────────┘ │
└───────────────────┴───────────────────┴───────────────────┘
```

**Benefits:** Shows all time scales simultaneously; users can compare patterns across resolutions.[^5]

## Summary: Key Principles for Balance

| Principle | Application |
| :-- | :-- |
| **Progressive Disclosure** | Start with high-level trends, drill down to details only when needed [^8] |
| **Smart Aggregation** | Aggregate at ingestion time; store multi-resolution data [^1] |
| **Anomaly-Driven Detail** | Show raw data only when anomalies are detected [^1] |
| **3-Layer Structure** | Overview → Trends → Raw data with 3-click access [^8] |
| **Clinical Relevance** | Match granularity to clinical question (investigation vs. monitoring) [^2] |
| **Visual Consistency** | Similar number of points per chart regardless of time scale [^3] |
| **Privacy Protection** | Store raw data only briefly; share aggregated metrics [^9] |

The goal is to show **the right level of detail at the right time**—high-level trends for routine monitoring, granular data for investigation—without overwhelming clinicians or obscuring clinically meaningful patterns.[^8][^1]
<span style="display:none">[^10][^11][^12][^13][^14]</span>

<div align="center">⁂</div>

[^1]: https://www.warmanobrien.com/resources/blog/5-future-trends-in-biometrics-shaping-the-health-and-life-sciences/

[^2]: https://www.hilarispublisher.com/open-access/wearable-mental-health-tech-biometrics-and-behavioral-sensing-in-psychiatric-care-114660.html

[^3]: https://clauswilke.com/dataviz/visualizing-trends.html

[^4]: https://researchportal.helsinki.fi/files/251788857/1_s2.0_S1574119222000566_main.pdf

[^5]: https://www.zigpoll.com/content/how-can-we-design-an-engaging-dashboard-that-visualizes-key-metrics-on-client-wellness-trends-and-therapist-performance-in-a-way-that-is-intuitive-for-psychologists-tracking-their-practice-outcomes

[^6]: https://www.linkedin.com/pulse/digital-phenotyping-mental-health-beyond-bridging-data-athukorala-bgzhc

[^7]: https://pmc.ncbi.nlm.nih.gov/articles/PMC11584197/

[^8]: https://alma-lasers.com.au/best-practices-for-clinical-dashboards/

[^9]: https://pmc.ncbi.nlm.nih.gov/articles/PMC13108794/

[^10]: https://techpolicy.press/the-high-stakes-of-biometric-surveillance

[^11]: https://www.oloid.com/blog/the-future-of-identity-management-trends-to-watch-out-for

[^12]: https://www.sciencedirect.com/science/article/pii/S2590198225004403

[^13]: https://journals.sagepub.com/doi/10.1177/14614448231201638

[^14]: https://arxiv.org/html/2405.00650v1

