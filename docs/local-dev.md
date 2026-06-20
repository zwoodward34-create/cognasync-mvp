# Local development loop

Run CognaSync on your Mac so you can click the real UI — log in, open a patient,
generate and print a brief — in seconds, without deploying to production. This is
the loop that turns "push to main and check the live PDF" into "edit, run, click."

> **PHI safety:** local dev must use a **separate dev Supabase project with
> synthetic data only**. Never point `.env.local` at the production project, and
> never load real patient data into a dev environment.

## One-time setup

### 1. Create a dev Supabase project

In the Supabase dashboard, create a **second** project (e.g. `cognasync-dev`).
This is normally free on the free tier, but confirm against your plan and project
count first — see [the cost notes below](#cost). Free projects pause after ~1 week
idle; you click to wake them.

Grab these from the dev project's **Settings > API** and **Settings > Database**:
`SUPABASE_URL`, anon key, service-role key, and the JWT secret.

### 2. Capture the schema and apply it to dev

The production schema currently lives only in the live database (no migration
history). Capture it once:

```bash
scripts/local.sh schema-dump        # prints the exact pg_dump / psql commands
```

Run the printed `pg_dump` against **production** to produce `schema.sql`, then the
printed `psql` against **dev** to apply it. Check `schema.sql` into the repo — a
reproducible schema is independently the highest-value durability win here (today
production exists nowhere else).

### 3. Configure and install

```bash
cp .env.local.example .env.local     # then edit: paste your DEV Supabase keys + ANTHROPIC_API_KEY
chmod +x scripts/local.sh
scripts/local.sh setup               # venv + python deps + vite build of the React client
```

Prerequisites: Python 3.10+, Node 18+ (for the client build), and `pg_dump`/`psql`
(ship with the `postgresql` Homebrew formula) for step 2.

### 4. Seed synthetic data

```bash
scripts/local.sh seed                # creates provider@dev.local / DevPass123! + test data
```

## The loop

```bash
scripts/local.sh run                 # http://localhost:5002
```

Log in as `provider@dev.local` / `DevPass123!`, open a seeded patient, generate a
psychiatry brief, and open the print view. Edit code, `Ctrl-C`, `run` again — or
rely on Flask's debug reload (`FLASK_ENV=development`). After changing anything in
`client/src/`, rebuild the client: `cd client && npm run build`.

To check the brief programmatically (screenshots, asserting the rendered DOM),
point the `gstack` browser tool at `http://localhost:5002`.

## What works locally vs. what's stubbed

| Works | Stubbed (dummy keys — won't send) |
|---|---|
| Login, provider/patient pages, brief generation + print view, charts, the offline test suites | Outbound email (use `seed` to make accounts, which bypasses email), SMS/Twilio, audio transcription (AssemblyAI), cron jobs |

Brief generation makes real Anthropic calls — pennies each on Haiku. Leave
`ANTHROPIC_API_KEY` as a dummy if you only need to click around without generating.

## Cost

- Flask on your Mac, the scaffolding, the offline test suites: **$0**.
- Dev Supabase project: **normally free**, but depends on your plan / project
  count — verify on your billing page before creating it.
- Anthropic calls during dev: **pennies** (Haiku), or **$0** if you stub the key.
- Nothing here touches production or its billing.

## Failure points to watch

- **Schema drift.** Because schema changes are applied by hand (no migration
  runner), dev and prod can silently diverge. If a local boot errors on a missing
  table/column/function, re-dump the schema. The durable fix is adopting the
  Supabase CLI migration workflow — tracked as a follow-on.
- **First boot is the real schema test.** Introspection-based dumps can miss
  triggers, RLS policy bodies, or custom types. If the app errors on first run,
  the capture missed something — patch `schema.sql` and re-apply.
- **Never** copy production patient data into the dev project. Synthetic only.

## Related

- [`docs/superpowers/plans/2026-06-19-server-side-pdf-footer.md`](superpowers/plans/2026-06-19-server-side-pdf-footer.md)
  — the deferred PDF work this loop unblocks (its tripwire was "a verifiable run loop").
