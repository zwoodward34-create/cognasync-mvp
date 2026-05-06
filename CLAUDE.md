# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CognaSync is a mental health tracking MVP for patients and their psychiatry providers. Patients do structured daily check-ins (morning / afternoon / evening / on-demand), keep a journal, and track medications. Providers see a patient dashboard with AI-generated pre-appointment summaries. Claude (via the Anthropic API) generates insights after each check-in, journal analysis, and appointment summaries.

## Commands

**Run the Flask server (development):**
```bash
python app.py
```
The server reads `FLASK_PORT` (default 5000). Requires `.env` populated from `.env.example`.

**Build the React check-in app:**
```bash
cd client && npm run build
```
Output goes to `../static/dist/` with fixed filenames (`assets/index.js`, `assets/index.css`). **Always rebuild after editing `client/src/` before committing** — the built files in `static/dist/` are what gets served.

**Run the React dev server (hot-reload, proxied):**
```bash
cd client && npm run dev
```

**Lint the frontend:**
```bash
cd client && npm run lint
```

**Create a provider account** (providers cannot self-register):
```bash
python scripts/create_provider.py
```

**Seed test data:**
```bash
python seed_test_data.py
```

**Apply the Supabase schema migration:**
Run `supabase_migration.sql` in the Supabase SQL Editor. All columns are `ADD IF NOT EXISTS` so it is safe to re-run.

## Architecture

### Backend — Flask + Supabase

`app.py` is the single Flask application file. It has two layers of routes:

- **Page routes** (return rendered HTML): `/`, `/checkin`, `/journal`, `/medication`, `/summary`, `/trends`, `/settings`, `/provider`, `/provider/patient/<id>` — all require session auth.
- **API routes** (return JSON, `/api/*`): consumed by the React SPA and legacy Jinja pages via `fetch`. CORS is restricted to `ALLOWED_ORIGIN`.

`database.py` contains every Supabase query. It imports `supabase_admin` (service-role client, bypasses RLS) for all reads/writes. There is no ORM; all queries use the Supabase Python client's query builder.

`supabase_auth.py` wraps Supabase Auth. Session tokens are Supabase JWTs stored in Flask `session`. The helper `_api_user(required_role)` in `app.py` is the standard auth guard for every API route — it checks the JWT from the Flask session, request body, `X-Session-Token` header, or query param.

`claude_api.py` contains all Anthropic API calls. The model is configurable via `CLAUDE_MODEL` env var (default: `claude-haiku-4-5-20251001`). All Claude calls go through `_call_claude()`. The module enforces crisis detection (`_check_crisis`) and output sanitization (`_sanitize_output`) on every AI response — responses containing diagnostic language are replaced with a safe fallback rather than surfaced raw.

### Frontend — two parallel UI systems

**React SPA** (`client/src/App.jsx` → `static/dist/assets/index.js`):
Used for `/checkin` and `/journal`. A single 1000+ line component. All check-in logic including scoring (`calcScores`), insight generation (`calcInsights`), the multi-step form flow, and cumulative daily caffeine/medication pre-population lives here. The build output is served as a static file; Flask renders a thin HTML shell (`checkin_react.html`, `journal_react.html`) that mounts `<div id="root">`.

**Legacy Jinja + vanilla JS** (`templates/`, `static/js/`):
Used for every other patient and provider page. `static/js/patient-app.js` handles the medication page, settings, and general patient interactions. `static/js/provider-dashboard.js` handles the provider views. `static/js/insight-engine.js` and `static/js/hypothesis-tester.js` power the trends and hypothesis-testing features. These pages fetch the same `/api/*` endpoints using `fetch` with `credentials: 'same-origin'`.

### Data model (key tables)

- `profiles` — users with `role` = `patient` or `provider`
- `checkins` — one row per check-in; `extended_data` (JSONB) holds energy, focus, caffeine breakdown, computed scores, and advanced lifestyle fields
- `medications` — a patient's medication list (reference, not event log)
- `medication_events` — timestamped log of doses taken
- `journals` — free-text entries with AI analysis stored back in the row
- `summaries` — AI-generated pre-appointment summaries; generated on-demand by provider or patient
- `patient_providers` — many-to-many link between patients and providers
- `hypotheses` — stored results from the correlation hypothesis tester

### Deployment

Deployed on Render. Pushing to `main` triggers an auto-deploy. The built React assets (`static/dist/`) are committed to the repo and served directly by Flask — there is no separate static hosting or CDN.

## Key patterns

**`extended_data` JSONB blob**: All check-in fields beyond the legacy columns (mood, stress, sleep) are stored here. When reading, always handle both `dict` and JSON-string forms:
```python
ext = row.get('extended_data') or {}
if isinstance(ext, str):
    ext = json.loads(ext)
```

**Cumulative daily caffeine**: Each check-in's `extended_data.caffeine_breakdown` represents the *running daily total*, not an increment. The React app pre-populates from `GET /api/checkins/today-summary` on mount so afternoon/evening check-ins carry forward the morning's count.

**AI safety gates**: Every call to Claude goes through `_check_crisis` (input and output) and `_sanitize_output`. If crisis keywords are detected the hardcoded `CRISIS_RESPONSE` is returned. If forbidden diagnostic language appears in Claude's output, a safe fallback replaces it. Never bypass these gates.

**Role separation**: Providers can only view patients explicitly linked to them (enforced by `_provider_owns_patient`). Patient self-registration always creates `role = 'patient'` regardless of form input. Provider accounts must be created via `scripts/create_provider.py`.
