import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import CognaSyncJournalCrisisDetection from './components/journal-crisis-detection.jsx'

const checkinRoot = document.getElementById('checkin-root')
const journalRoot = document.getElementById('journal-root')

if (checkinRoot) {
  createRoot(checkinRoot).render(<StrictMode><App /></StrictMode>)
}
if (journalRoot) {
  createRoot(journalRoot).render(<StrictMode><CognaSyncJournalCrisisDetection /></StrictMode>)
}
