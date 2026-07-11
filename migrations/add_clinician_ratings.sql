-- 60-second clinician check-in (spec §27, decision 2026-07-10).
--
-- One JSONB column on the existing appointment record. Validated shape
-- (database.validate_clinician_ratings):
--   { "severity": 1-7,            -- CGI-S, required
--     "improvement": 1-7 | null,  -- CGI-I; null = first visit / not rated
--     "speech": { ... },          -- optional, §24 constrained values only
--     "note": "≤200 chars",       -- optional
--     "rated_at": iso, "version": 1 }
--
-- Idempotent. Run in dev (mvekchhbyvyhbdilulfx) first, then prod.
-- provider_appointments already carries the standard grants; a new column
-- inherits them (no GRANT needed).

ALTER TABLE provider_appointments
  ADD COLUMN IF NOT EXISTS clinician_ratings jsonb;
