# Server-side PDF (headless Chromium) — the real footer fix

**Status:** Deferred (blocked on a verifiable run loop — see Tripwire).
**Created:** 2026-06-19
**Priority:** Low (cosmetic / compliance hygiene — see "Why this is low priority").

---

## Problem

The provider clinical summary print view (`/provider/patient/<id>/summary/print`) is turned
into a PDF by the browser's "Print to PDF." The browser injects its own header/footer into
the page margins — including the **full URL**, which contains the patient UUID and brief_id.
That puts internal record identifiers into a saved/shared artifact stamped "Confidential —
PHI."

This is **not** in `templates/provider/summary_print.html` — it's browser print chrome, so
it can't be removed by CSS or template changes alone.

## Why this is low priority

The document body already shows the patient's full name, email, medication list, and
clinical narrative. The footer UUID adds little incremental identifiability on top of that.
Its real value is (a) not exposing an internal record ID in a shareable artifact
(enumeration/IDOR hygiene) and (b) compliance optics. Do not let this jump the queue ahead
of clinical-accuracy work.

## Interim mitigation (zero code, in place)

Disable "Headers and footers" in the browser print dialog (set as the default). This removes
the **entire** footer — URL, date, title — which is strictly more complete than the token
route below. This is the current stopgap.

## Already built (banked, tested, unused)

A signed, opaque, expiring token primitive is implemented and unit-tested offline — it has
**no callers yet**:

- `supabase_auth.generate_brief_token(patient_id, brief_id, days, secret)` →
  `verify_brief_token(token, secret)`. HMAC-SHA256 (mirrors `generate_reset_token`),
  base64-wrapped payload so the UUIDs never appear in the URL, 1-hour TTL, non-bearer.
- `tests/test_brief_token.py` — 7 offline tests: round-trip, opacity (no UUID in token),
  tamper rejection, wrong-secret, expiry, missing brief_id, garbage input.

## Remaining work (build + verify together, behind the tripwire)

The token route was deferred because wiring it is a ~5-surface change to a flow that can't
be verified from the dev sandbox (no Flask/browser). Do it as ONE reviewed, click-through-
tested change:

1. **Route refactor** — extract the body of `provider_summary_print` (app.py ~1083–1257)
   into `_summary_print_response(user, patient_id, days, brief_id)`; the existing route
   parses `request.args` (only `days` @ ~1098 and `brief_id` @ ~1116) and calls it.
2. **Token route** — `GET /provider/brief/<token>`: `_require_provider()` →
   `auth_module.verify_brief_token(token, app.secret_key)` → `_provider_owns_patient()` →
   `_summary_print_response(...)`. Still enforces login + ownership; token is privacy only.
3. **Mint endpoint** — small JSON route returning `{url: '/provider/brief/<token>'}` for a
   given patient_id + brief_id + days (provider-auth + ownership), because the hub builds the
   print URL in client JS and JS can't sign.
4. **Repoint hub JS** — `templates/provider/patient_hub.html` ~2715–2717 currently builds
   `/provider/patient/<id>/summary/print?...` then `window.open`s it. **GOTCHA:** calling
   `window.open` AFTER an `await fetch` loses the user-gesture context and triggers pop-up
   blockers. Mitigate: open the tab synchronously on click (`const w = window.open('about:blank')`)
   then set `w.location = url` once the mint returns — or render a fresh token URL into the
   page on brief load so no async hop is needed at click time.
5. **Repoint patient_detail links** — `templates/provider/patient_detail.html` lines 694 &
   698 ("Print Brief" / "Create Brief") are static `url_for('provider_summary_print', ...)`
   links with no brief_id; to tokenize, their rendering route must mint and pass a token.
   (Secondary — the printed artifact comes from the hub path; these are navigation.)

## The real fix (preferred end state)

Server-side PDF generation via headless Chromium (Playwright) with
`page.pdf({displayHeaderFooter: false})` — or a controlled custom footer with no PHI. This
is the only approach that (a) removes the footer deterministically and (b) preserves the
Chart.js charts (WeasyPrint/wkhtmltopdf don't execute JS → blank charts). Cost: Chromium in
the Render build (~300MB + system deps), a render route, and render-timing logic
(`animation:false` is already set; wait for charts before capture). The token route becomes
a component of this rather than a standalone change. This also unlocks emailing/storing/
auditing briefs as immutable PDFs.

## Tripwire (what flips this from "defer" to "do")

A staging environment OR a local Flask + headless-render loop — i.e., the ability to click
the Print button and inspect the result before a provider does. The blocker was never the
merit; it's that the brief flow is currently maintained without a verifiable click-through.
Once that exists, do the full server-side-PDF fix (token route included) properly.
