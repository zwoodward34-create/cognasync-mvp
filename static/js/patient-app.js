// Patient app — check-in, journal, medication, settings logic

// ── Check-in ─────────────────────────────────────────────────────────────────

function initCheckin() {
  // Time tabs
  document.querySelectorAll('.time-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.time-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById('time_of_day').value = tab.dataset.time;
    });
  });

  // Add medication row
  document.getElementById('add-med-btn').addEventListener('click', () => {
    const list = document.getElementById('medications-list');
    const row = document.createElement('div');
    row.className = 'med-row';
    row.innerHTML = `
      <input type="text" class="med-name" placeholder="Medication name">
      <input type="text" class="med-dose" placeholder="Dose">
      <label class="med-taken-label">
        <input type="checkbox" class="med-taken"> Taken
      </label>
      <button type="button" class="btn-remove-med" onclick="this.parentElement.remove()">×</button>
    `;
    list.appendChild(row);
    row.querySelector('.med-name').focus();
  });

  // Submit
  document.getElementById('checkin-form').addEventListener('submit', async e => {
    e.preventDefault();
    const btn = document.getElementById('checkin-submit');
    btn.disabled = true;
    hideAlert('checkin-success');
    hideAlert('checkin-error');

    const medications = [];
    document.querySelectorAll('.med-row').forEach(row => {
      const name = row.querySelector('.med-name')?.value.trim();
      const dose = row.querySelector('.med-dose')?.value.trim();
      const taken = row.querySelector('.med-taken')?.checked || false;
      if (name) medications.push({ name, dose, taken });
    });

    const payload = {
      date: new Date().toISOString().slice(0, 10),
      time_of_day: document.getElementById('time_of_day').value,
      mood_score: parseInt(document.getElementById('mood_score').value),
      sleep_hours: parseFloat(document.getElementById('sleep_hours').value),
      stress_score: parseInt(document.getElementById('stress_score').value),
      symptoms: document.getElementById('symptoms').value.trim(),
      notes: document.getElementById('notes').value.trim(),
      medications,
    };

    try {
      await apiPost('/api/checkins', payload);
      showAlert('checkin-success', 'Check-in saved! Keep up the great work.', false);
      document.getElementById('checkin-form').reset();
      document.getElementById('mood-val').textContent = '5';
      document.getElementById('sleep-val').textContent = '7';
      document.getElementById('stress-val').textContent = '5';
      document.querySelectorAll('.time-tab').forEach(t => t.classList.remove('active'));
      document.querySelector('.time-tab').classList.add('active');
    } catch (err) {
      showAlert('checkin-error', err.message || 'Failed to save check-in. Please try again.');
    }
    btn.disabled = false;
  });
}


// ── Journal ───────────────────────────────────────────────────────────────────

const JOURNAL_PROMPTS = [
  'What is one thing that brought you even a small amount of comfort or peace today?',
  'Describe a moment this week where you felt like yourself. What made it feel that way?',
  'What thoughts keep returning to you lately? Are they helpful or not?',
  'If you could talk to yourself from six months ago, what would you say?',
  'What is one thing you\'re avoiding, and what might happen if you faced it?',
  'Describe your energy today — physically and emotionally.',
  'What did you need today that you didn\'t get? What did you get that you didn\'t expect?',
  'What is one belief about yourself you\'d like to challenge or examine?',
];

const GUIDED_QUESTIONS = [
  'How are you feeling right now, physically and emotionally? Try to be specific.',
  'What has been the most challenging thing in the past few days?',
  'Is there anything you\'ve been worrying about? How long has it been on your mind?',
  'Have you done anything to take care of yourself recently? What helped, what didn\'t?',
  'Is there anything you want your provider to know before your next appointment?',
];

let guidedAnswers = [];
let guidedIndex = 0;

function initJournal() {
  // Mode tabs
  document.querySelectorAll('.mode-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.mode-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      document.querySelectorAll('.journal-panel').forEach(p => p.classList.add('hidden'));
      document.getElementById('mode-' + tab.dataset.mode).classList.remove('hidden');
      if (tab.dataset.mode === 'prompt') refreshPrompt();
      if (tab.dataset.mode === 'guided') initGuided();
    });
  });

  // Char counter
  const textarea = document.getElementById('raw_entry');
  if (textarea) {
    textarea.addEventListener('input', () => {
      document.getElementById('char-count').textContent = textarea.value.length;
    });
  }

  // Free flow form
  const form = document.getElementById('journal-form');
  if (form) {
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const btn = document.getElementById('journal-submit');
      const entry = document.getElementById('raw_entry').value.trim();
      if (!entry) return;

      btn.disabled = true;
      btn.textContent = 'Analyzing…';
      ['journal-success', 'journal-error', 'journal-crisis'].forEach(hideAlert);
      document.getElementById('analysis-result').classList.add('hidden');

      try {
        const data = await apiPost('/api/journals', {
          entry_type: 'free_flow', raw_entry: entry });
        document.getElementById('display-entry').textContent = data.raw_entry;
        document.getElementById('display-analysis').textContent = data.ai_analysis;
        document.getElementById('analysis-result').classList.remove('hidden');
        if (data.alert === 'crisis') {
          showAlert('journal-crisis', data.ai_analysis);
        }
        form.reset();
        document.getElementById('char-count').textContent = '0';
      } catch (err) {
        showAlert('journal-error', err.message || 'Failed to save journal entry.');
      }
      btn.disabled = false;
      btn.textContent = 'Save & Analyze';
    });
  }

  // Prompt form
  const promptForm = document.getElementById('prompt-journal-form');
  if (promptForm) {
    promptForm.addEventListener('submit', async e => {
      e.preventDefault();
      const entry = document.getElementById('prompt_raw_entry').value.trim();
      const prompt = document.getElementById('prompt-text').textContent;
      if (!entry) return;

      try {
        const data = await apiPost('/api/journals', {
          entry_type: 'prompt',
          raw_entry: `[Prompt: ${prompt}]\n\n${entry}`,
        });
        document.getElementById('prompt-display-entry').textContent = entry;
        document.getElementById('prompt-display-analysis').textContent = data.ai_analysis;
        document.getElementById('prompt-analysis-result').classList.remove('hidden');
        promptForm.reset();
      } catch (err) {
        alert(err.message || 'Failed to save entry.');
      }
    });
  }

  refreshPrompt();
}

function refreshPrompt() {
  const el = document.getElementById('prompt-text');
  if (el) {
    el.textContent = JOURNAL_PROMPTS[Math.floor(Math.random() * JOURNAL_PROMPTS.length)];
  }
}

function initGuided() {
  guidedAnswers = new Array(GUIDED_QUESTIONS.length).fill('');
  guidedIndex = 0;
  renderGuidedQuestion();
}

function renderGuidedQuestion() {
  const q = document.getElementById('guided-question');
  const a = document.getElementById('guided-answer');
  const progress = document.getElementById('progress-fill');
  const progressText = document.getElementById('progress-text');
  const prevBtn = document.getElementById('guided-prev');
  const nextBtn = document.getElementById('guided-next');

  if (!q) return;
  q.textContent = GUIDED_QUESTIONS[guidedIndex];
  a.value = guidedAnswers[guidedIndex] || '';
  progress.style.width = ((guidedIndex + 1) / GUIDED_QUESTIONS.length * 100) + '%';
  progressText.textContent = `Question ${guidedIndex + 1} of ${GUIDED_QUESTIONS.length}`;
  prevBtn.style.display = guidedIndex > 0 ? '' : 'none';
  nextBtn.textContent = guidedIndex === GUIDED_QUESTIONS.length - 1 ? 'Finish' : 'Next →';
}

function guidedPrev() {
  guidedAnswers[guidedIndex] = document.getElementById('guided-answer').value;
  guidedIndex--;
  renderGuidedQuestion();
}

async function guidedNext() {
  guidedAnswers[guidedIndex] = document.getElementById('guided-answer').value.trim();
  if (guidedIndex < GUIDED_QUESTIONS.length - 1) {
    guidedIndex++;
    renderGuidedQuestion();
  } else {
    const fullEntry = GUIDED_QUESTIONS.map((q, i) =>
      `Q: ${q}\nA: ${guidedAnswers[i] || '(no answer)'}`
    ).join('\n\n');

    try {
      await apiPost('/api/journals', { entry_type: 'guided', raw_entry: fullEntry });
      document.getElementById('guided-complete').classList.remove('hidden');
      document.getElementById('guided-answer').disabled = true;
      document.getElementById('guided-next').disabled = true;
    } catch (err) {
      alert(err.message || 'Failed to save guided entry.');
    }
  }
}


// ── Medications ───────────────────────────────────────────────────────────────

function initMedications() {
  const addForm = document.getElementById('add-med-form');
  if (addForm) {
    addForm.addEventListener('submit', async e => {
      e.preventDefault();
      const name = document.getElementById('med-name-input').value.trim();
      const dose = document.getElementById('med-dose-input').value.trim();
      const frequency = document.getElementById('med-freq-input').value;
      if (!name || !dose) {
        showAlert('med-error', 'Please enter both a name and dose.');
        return;
      }

      // Get current profile medications, add new one, and update
      try {
        const profileRes = await apiGet('/api/checkins?days=1');
        // We'll use the settings API to update medications
        await apiPost('/api/settings/profile', {
          current_medications: [{ name, dose, frequency }]
        });
        showAlert('med-success', `${name} added to your medication list.`, true);
        addForm.reset();
        setTimeout(() => location.reload(), 1500);
      } catch (err) {
        showAlert('med-error', err.message || 'Failed to add medication.');
      }
    });
  }

  const logForm = document.getElementById('log-dose-form');
  if (logForm) {
    logForm.addEventListener('submit', async e => {
      e.preventDefault();
      const select = document.getElementById('log-med-name');
      const name = select.value;
      const dose = select.selectedOptions[0]?.dataset.dose || '';
      if (!name) return;

      try {
        await apiPost('/api/checkins', {
          date: new Date().toISOString().slice(0, 10),
          time_of_day: 'self-prompted',
          mood_score: 5,
          sleep_hours: 7,
          stress_score: 5,
          medications: [{ name, dose, taken: true }],
          notes: `Logged ${name} ${dose} as taken`,
        });
        showAlert('log-success', `${name} logged as taken.`, true);
      } catch (err) {
        showAlert('med-error', err.message || 'Failed to log dose.');
      }
    });
  }
}

async function lookupMed(name) {
  const panel = document.getElementById('med-info-panel');
  if (!name) {
    panel.classList.add('hidden');
    return;
  }
  try {
    // Call the medication search endpoint
    const data = await apiGet('/api/medications/search?q=' + encodeURIComponent(name));
    // For now, display a basic info card
    panel.innerHTML = `<div class="med-info-card">
      <strong>${name}</strong>
      <p class="text-muted">Consult your provider or pharmacist for detailed information about this medication.</p>
    </div>`;
    panel.classList.remove('hidden');
  } catch (e) {
    panel.classList.add('hidden');
  }
}


// ── Settings ──────────────────────────────────────────────────────────────────

function initSettings() {
  const emergencyForm = document.getElementById('emergency-form');
  if (emergencyForm) {
    emergencyForm.addEventListener('submit', async e => {
      e.preventDefault();
      const contact = document.getElementById('emergency_contact').value.trim();
      try {
        await apiPost('/api/settings/profile', { emergency_contact: contact });
        showAlert('settings-success', 'Emergency contact saved.', true);
      } catch (err) {
        showAlert('settings-error', err.message || 'Failed to save.');
      }
    });
  }

  const passwordForm = document.getElementById('password-form');
  if (passwordForm) {
    passwordForm.addEventListener('submit', async e => {
      e.preventDefault();
      const current = document.getElementById('current_password').value;
      const next = document.getElementById('new_password').value;
      try {
        await apiPost('/api/settings/password', {
          current_password: current, new_password: next });
        showAlert('settings-success', 'Password updated successfully.', true);
        passwordForm.reset();
      } catch (err) {
        showAlert('settings-error', err.message || 'Failed to update password.');
      }
    });
  }
}
