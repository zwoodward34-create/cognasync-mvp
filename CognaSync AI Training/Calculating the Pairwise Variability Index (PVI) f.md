<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Calculating the Pairwise Variability Index (PVI) for Rhythm Type Classification

The **Pairwise Variability Index (PVI)** is the gold-standard metric for classifying languages as **stress-timed** vs **syllable-timed** based on durational variability between successive vocalic or consonantal intervals. It was developed by **Grabe \& Low (2002)** and is widely used in phonetics, linguistics, and speech analysis.[^1][^2]

## Two Types of PVI

| Type | Formula | Best For | Why |
| :-- | :-- | :-- | :-- |
| **rPVI** (raw PVI) | See below | **Consonantal intervals** [^1] | No normalization needed; measures absolute differences [^1] |
| **nPVI** (normalized PVI) | See below | **Vocalic intervals** [^1] | Normalizes for speech rate, which strongly affects vowel duration [^1] |

**Key insight:** Grabe \& Low recommend using **rPVI for consonants** and **nPVI for vowels**.[^1]

## Formulas

### **1. Raw Pairwise Variability Index (rPVI)**

$$
\text{rPVI} = \frac{1}{m-1} \sum_{k=1}^{m-1} |d_k - d_{k+1}|
$$

Where:

- $m$ = number of intervals (consonantal or vocalic)[^1]
- $d_k$ = duration of the $k$-th interval[^2][^1]
- $d_{k+1}$ = duration of the next interval[^1]

**What it measures:** Average absolute difference in duration between **adjacent** intervals.[^1]

**Units:** Milliseconds (ms) - same as input durations.[^1]

### **2. Normalized Pairwise Variability Index (nPVI)**

$$
\text{nPVI} = \frac{100}{m-1} \sum_{k=1}^{m-1} \frac{|d_k - d_{k+1}|}{\max(d_k, d_{k+1})}
$$

**Alternative equivalent form** (often used):

$$
\text{nPVI} = \frac{100}{m-1} \sum_{k=1}^{m-1} \frac{|d_k - d_{k+1}|}{(d_k + d_{k+1})/2}
$$

Where:

- $m$ = number of vocalic intervals[^1]
- $d_k$ = duration of the $k$-th vocalic interval[^1]
- $\max(d_k, d_{k+1})$ = longer of the two consecutive intervals[^1]

**What it measures:** Average **relative** difference between adjacent vocalic intervals, normalized by the longer interval.[^1]

**Units:** Percentage (%) - dimensionless (multiplied by 100).[^1]

**Why normalize:** Vocalic intervals are more prone to speech rate influence; normalization removes this effect.[^1]

## Step-by-Step Calculation Example

### **Example Data: Vocalic Intervals (in ms)**

Assume you have extracted 5 vocalic intervals from a speech sample:

- $d_1 = 150$ ms
- $d_2 = 50$ ms
- $d_3 = 120$ ms
- $d_4 = 60$ ms
- $d_5 = 140$ ms

This represents alternation between stressed (longer) and unstressed (shorter) vowels.[^2]

### **Step 1: Calculate Pairwise Differences**

For **nPVI**, calculate for each consecutive pair:

| Pair | $d_k$ | $d_{k+1}$ | $|d_k - d_{k+1}|$ | $\max(d_k, d_{k+1})$ | Ratio |
|------|---------|-------------|---------------------|------------------------|-------|
| 1 | 150 | 50 | $\lvert 150 - 50 \rvert = 100$ | 150 | $100/150 = 0.667$ |
| 2 | 50 | 120 | $\lvert 50 - 120 \rvert = 70$ | 120 | $70/120 = 0.583$ |
| 3 | 120 | 60 | $\lvert 120 - 60 \rvert = 60$ | 120 | $60/120 = 0.500$ |
| 4 | 60 | 140 | $\lvert 60 - 140 \rvert = 80$ | 140 | $80/140 = 0.571$ |

### **Step 2: Calculate nPVI**

$$
\text{nPVI} = \frac{100}{5-1} \left( 0.667 + 0.583 + 0.500 + 0.571 \right)
$$

$$
\text{nPVI} = \frac{100}{4} \times 2.321 = 25 \times 2.321 = 58.03
$$

**Result:** nPVI = **58.03** (for vocalic intervals)

### **Step 3: Calculate rPVI (for comparison)**

$$
\text{rPVI} = \frac{1}{5-1} (100 + 70 + 60 + 80) = \frac{310}{4} = 77.5 \text{ ms}
$$

**Result:** rPVI = **77.5 ms** (for consonantal intervals)

## Python Implementation

<span style="display:none">[^3][^4][^5][^6][^7][^8][^9]</span>

<div align="center">⁂</div>

[^1]: https://www.lfsag.unito.it/sito_old/ritmo/pvi_en.html

[^2]: http://wwwhomes.uni-bielefeld.de/~gibbon/AK-Phon/Rhythmus/Grabe/Grabe_Low-reformatted.pdf

[^3]: https://emusicology.org/article/id/4742/

[^4]: https://online.ucpress.edu/mp/article/36/3/300/62795/Deconstructing-the-nPVIA-Methodological-Critique

[^5]: https://github.com/HuwCheston/npyvi

[^6]: https://pubmed.ncbi.nlm.nih.gov/19390231/

[^7]: https://www.isca-archive.org/speechprosody_2018/hattori18_speechprosody.html

[^8]: https://icmpc-escom2012.web.auth.gr/files/papers/1001_Proc.pdf

[^9]: https://www.sciencedirect.com/science/article/abs/pii/S0885230815300280

