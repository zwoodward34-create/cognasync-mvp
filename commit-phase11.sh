#!/bin/bash
set -e

echo "=== Phase 11: Patient homepage redesign ==="

cd "$(dirname "$0")"

git add \
  templates/patient/home.html

git commit -m "Phase 11: Patient homepage redesign — two-column layout, compact insights, markdown rendering

Layout restructure:
- Replace single-column full-width stack with a two-column grid (1fr 320px)
- Left column 'Today': check-in hero card + medication widget
- Right column 'Intelligence': compact insight rows, next appointment, summary preview
- Bottom navigation strip: all 7 destinations in a single compact row grid
- Responsive: collapses to single column at ≤860px, naturally stacked in DOM order

Check-in hero card:
- Large prominent CTA card replaces the old 'quick-card' for check-in
- Clear done/not-done state (green fill + checkmark icon when logged)
- Button label changes: 'Start →' → 'View →' when already logged today
- Also marks the check-in nav item done when logged

Proactive insights — compact rows:
- Replace dense paragraph blocks with scannable 2-line rows
- Badge label + 2-line truncated text + dismiss button per row
- Grouped in a bordered list container with section label 'Patterns'
- Dismiss animation and API call preserved (targets .insight-row)

Summary preview — markdown rendering:
- Raw markdown (# headings, **bold**, - bullets) now rendered as HTML
- Line-by-line parser handles consecutive bullets → <ul>, headings → <h3>
- Prevents raw ## and ** from displaying to users

Design improvements:
- Inline date display below greeting (rendered by JS)
- Smaller streak badge (1.75rem vs 2rem)
- Section labels above intelligence components for scanability
- Next appointment rendered as compact card with days-away badge
- 7-item bottom nav replaces the old 3-column quick-cards grid
  (eliminates the orphaned 7th card in the previous 3-col layout)"

echo "✓ Committed phase 11"
