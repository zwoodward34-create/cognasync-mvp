-- ============================================================
-- CognaSync — AI Feedback table
-- Run in Supabase > SQL Editor (safe to re-run)
-- ============================================================

CREATE TABLE IF NOT EXISTS ai_feedback (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  content_type TEXT NOT NULL CHECK (content_type IN ('checkin', 'journal', 'summary')),
  content_id   TEXT NOT NULL,
  rating       TEXT NOT NULL CHECK (rating IN ('up', 'down')),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (user_id, content_type, content_id)
);

-- Index for provider/admin queries by content type
CREATE INDEX IF NOT EXISTS idx_ai_feedback_type ON ai_feedback (content_type, rating);
