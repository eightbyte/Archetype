# Archetype — Backlog

**Status:** Active · **Version:** 1.0 · **Date:** 2026-08-29
**Parent:** [`specs/project-outline.md`](project-outline.md)

Where ideas go so they do not become scope creep (outline § 9). Two kinds live here: **open
questions** that must be answered by a named phase, and **deferred features** that are explicitly
not in 1.0.

Promoting anything from here into a phase means editing the outline first, then the phase plan
(outline § 13).

---

## 1. Open questions — must be settled by the named phase

| ID | Question | Leaning | Settle by |
|---|---|---|---|
| **Q1** | Are snapshots automatic on a timer, on chapter close, or only manual? | Automatic on close, plus a manual "mark version" | Phase 2 |
| **Q2** | Do bible entries need soft-delete/trash, or is revision history enough? | Revision history is enough; `superseded` covers retcons | Phase 3 |
| **Q3** | Should findings expire when the text they cite changes, or be re-checked? | Mark `outdated` when the cited anchor changes, offer a re-run | Phase 7 |
| **Q4** | Does the agent get an external web-search tool? | No for 1.0 — offline story consistency is the product | Phase 6 |
| **Q5** | Multi-tab safety: soft lock, last-write-wins with a warning, or ignore? | **Partly settled by D19** — a version guard returns `409` and the UI warns. Whether a soft lock is also wanted is open | Phase 2 |
| **Q6** | Does the interaction chart get a node-link view alongside the matrix? | Matrix ships first (D14); the writer asked to revisit the design when the phase starts | Phase 8 |

---

## 2. Deferred features — explicitly not 1.0

Recorded so they are decisions rather than oversights. Each would be a real feature; none is
needed to prove the system works end to end.

**Writing surface**
- Continuous-scroll reading mode across chapters (D2 trades this away for editor speed).
- Footnotes, comments, and margin annotations.
- Focus/typewriter mode, writing-session word-count goals.
- Full-text find-and-replace across the manuscript.

**Bible and outline**
- Node-link interaction graph (D14 stretch).
- Map view for places; relationship strength or sentiment on links.
- Bible entry templates per genre.

**AI**
- Automatic background extraction as you write (D13 — plumbing stays scheduler-ready).
- Prompt and model tuning, quality benchmarking, automated evaluation of output quality
  (outline § 2 — a post-1.0 concern by design).
- An external web-search tool (Q4).
- Agent-initiated proactive findings without a user request.

**Platform**
- Multi-user, collaboration, presence, accounts (outline § 2).
- Home-server or internet-facing deployment, HTTPS, auth (D7).
- Mobile and tablet layouts.
- DOCX / EPUB / PDF export (D15).
- Local model hosting inside the app — the app talks to an endpoint; what serves it is the
  writer's business.

---

## 3. Promoted

*Items that left this list for a phase plan. Empty so far.*

| ID | Promoted to | Date |
|---|---|---|
| — | — | — |
