Vocal features used to detect mental health conditions broadly fall into several categories, ranging from basic acoustic measures to advanced linguistic and deep learning representations.  
**Prosodic and Temporal Features (Rhythm and Timing)**These features measure the flow and structure of speech:

* **Speech rate and articulation rate:** Measures such as how many words or syllables are spoken per minute 1-3.  
* **Pause patterns:** The number of pauses, total pause duration, and "switching pauses" (the gap between one person stopping and another starting) are heavily analyzed 2-4. For example, longer utterance-initial pauses and an increase in unfilled pauses (silences without filler words like "um") are noted in patients with formal thought disorder and schizophrenia 5\.  
* **Speech activity:** Overall speech volume is tracked; reduced speech activity is a known symptom of depression, while increased speech activity can predict a switch to hypomania in bipolar disorder 6\.

**Acoustic Features (Pitch and Energy)**These evaluate the fundamental sound wave characteristics of the voice:

* **Fundamental Frequency (F0) / Pitch:** The mean and variability of a speaker's pitch are core metrics 2, 3\. Studies show that an **increased F0 is a physiological indicator of social anxiety disorder** 7, whereas **reduced F0 and lowered loudness are strongly associated with depression** 8, 9\. Additionally, reduced pitch variability (a monotonous voice) is frequently observed in schizophrenia spectrum disorders 10\.  
* **Energy and Intensity:** Measures of vocal loudness and its variation 2, 3\. For instance, a lower standard deviation in energy contours (a flatter, less animated voice) has been linked to patients experiencing suicidal ideation 11\.

**Voice Quality and Spectral Features**These features capture the texture, clarity, and timbre of the voice:

* **Jitter and Shimmer:** Jitter measures micro-instabilities in voice frequency (pitch), while shimmer measures micro-instabilities in voice amplitude (loudness) 2, 3\.  
* **Harmonics-to-Noise Ratio (HNR):** This assesses the amount of acoustic noise in the voice signal 12, 13\.  
* **Phase Distortion Deviation (PDD):** This metric evaluates glottal source characteristics (the vibration of the vocal cords) to quantify perceived **hoarseness and breathiness**, which are highly correlated with depressed speech 14, 15\.  
* **Formants and Vowel Space:** Frequencies of the first and second formants (F1, F2) and the overall "vowel space" (the separation between frequencies used to articulate vowels) indicate the coordination of vocal tract articulators 2, 3\.  
* **Spectral Features:** These include spectral slope, spectral tilt, spectral flux, zero-crossing rates, and Mel-Frequency Cepstral Coefficients (MFCCs), which represent how acoustic energy is distributed across different frequency bands 2, 16-18.

**Linguistic and Semantic Features**By transcribing the audio using Automatic Speech Recognition (ASR), researchers extract patterns about *how* language is used:

* **Vocabulary diversity, word length, and sentence complexity** 18\.  
* **Filler word ratios**, word repetition rates, spoken words ratios, and lexical complexity scores (such as n-gram probabilities or word ambiguity) 1\.

**Deep Audio Embeddings**Rather than extracting specific hand-crafted features, modern approaches use pre-trained neural networks to encode subtle, high-dimensional paralinguistic patterns directly from raw audio or spectrograms. Popular embedding models used in mental health detection include **X-vectors, Wav2Vec2, and Trillsson** 19-22.  
