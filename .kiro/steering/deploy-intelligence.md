# DeployIntelligence - global rules (apply to every task)

Product: DeployIntelligence - "Deployment analysis that learns from every outcome." Hindsight memory is the core differentiator.

HARD RULES
- Do not invent functionality. Do not fabricate data. Do not hardcode values that must come from the backend or Hindsight (counts, ids, dates, outcomes, similarity, lessons, patterns, root causes, fixes).
- Do not replace working backend logic (src/matching.py scoring, src/memory.py retain/recall) unnecessarily. Do not perform unrelated refactors. Do not add unnecessary dependencies (no router library, no icon library, no UI kit).
- Do not redesign the UI away from the attached reference image. Sidebar has EXACTLY three items in this order: New Analysis, Organisational Memory, Deployments. Never add Overview, Incidents, Settings, Profile, Analytics, Dashboard, team switcher.
- Do not create fake demo states. Every UI state must come from a real backend operation. If Hindsight fails, show an explicit visible warning - never silently fall back to canned text.
- Preserve existing architecture unless there is a concrete technical reason; state the reason if you deviate.
- Windows user: existing scripts use `py -3`. Provide commands for the user's shell.
- Credits are limited: do not re-explore after the listed files are read, do not regenerate working files, do not run unrelated verify_*.py scripts, stop at each phase's STOP point and report.

CANONICAL DATA MODEL (ledger record)
deployment_id, service, migration_type, connection_pool_change, change_type, dependencies_changed, timestamp (ISO), outcome ("success"|"incident"|"pending"), root_cause, resolution, recovery_time_minutes, notes, source ("seed"|"feedback"|"analysis"), retained_in_hindsight (bool), recorded_at.
"pending" = analyzed, no outcome yet; pending records are NEVER used for matching, patterns, or memory counts.

SIGNALS (must be explained in UI): similarity = matched signals out of 5: service, migration_type, connection_pool_change, change_type, dependencies_changed. A historical deployment is "similar" at >= 2 matches. Computed by src/matching.py.

DESIGN TOKENS (from reference)
bg #0A0E14; sidebar #0C1118; card #0F151C; card-border #1F2A37; text #E6EDF3; text-muted #9AA7B5 (must stay >= 4.5:1 contrast);
CYAN #22D3EE = Hindsight/memory/learning ONLY; RED #EF4444 = incident; GREEN #22C55E = success; AMBER #F59E0B = moderate risk / warnings; BLUE #2563EB = buttons + active nav.
No purple/indigo gradients. Body text 15-16px, metadata never below 13px, key moments 24-32px. Must be legible on a projector.