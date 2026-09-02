# Archetype — Backlog

**Status:** Active · **Version:** 1.3 · **Date:** 2026-09-01
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
| **Q2** | Do bible entries need soft-delete/trash, or is revision history enough? | Revision history is enough; `superseded` covers retcons | Phase 3 |
| **Q3** | Should findings expire when the text they cite changes, or be re-checked? | Mark `outdated` when the cited anchor changes, offer a re-run | Phase 7 |
| **Q4** | Does the agent get an external web-search tool? | No for 1.0 — offline story consistency is the product | Phase 6 |
| **Q6** | Does the interaction chart get a node-link view alongside the matrix? | Matrix ships first (D14); the writer asked to revisit the design when the phase starts | Phase 8 |
| **Q7** | Should H1 be reserved for chapter titles, leaving the editor levels 2 and 3? | Probably yes. A chapter already has a title *field*, so an H1 in its body duplicates it, and the ambiguity that made phase-2 `D15` necessary would be gone at the source rather than papered over in one exporter. Against it: a closed-schema change (D1) that fails a test on both sides of the wire by design, a migration for every H1 already written, and a heading control that offers two levels where the writer expects three. Raised by the phase-2 § 8 acceptance run, 2026-09-01 | Phase 3 |

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
- DOCX / EPUB / PDF export, and the full project bundle (D15; Markdown per chapter and
  combined shipped in Phase 2, P2-13).
- A round-trip promise for the **combined** Markdown export ([phase-2-plan](phase-2-plan.md)
  § 2, ruling 4) — it needs a chapter boundary the schema has no node for, and inventing one
  would be a private format wearing Markdown's clothes.
- Import **replacing** a chapter's text rather than appending one (ruling 5). The `pre-import`
  snapshot reason exists for the phase that adds it; import-then-delete does the job today.
- Local model hosting inside the app — the app talks to an endpoint; what serves it is the
  writer's business.

---

## 3. Promoted

*Items that left this list for a phase plan.*

| ID | Promoted to | Date | Ruling |
|---|---|---|---|
| **Q1** | Phase 2 — [D23](development-phases.md) | 2026-08-30 | **Settled as its leaning, and further.** Snapshots are taken on handover, on demand with a label, and before anything destructive (`pre-restore`, `pre-delete`, `pre-import`). A timer was rejected: it duplicates autosave's job while producing snapshots at moments that mean nothing. Only the automatic `handover` snapshots are deduplicated and pruned; deliberate ones are always written and kept. `pre-import` is registered but has no writer yet: import **creates** chapters and never replaces one, so nothing an import does can destroy text ([phase-2-plan](phase-2-plan.md) § 7, `D1`). |
| **Q5** | Phase 2 — [D24](development-phases.md) | 2026-08-30 | **Settled as no lock.** D19's version guard plus the P1-10 conflict surface are the whole answer, and snapshots make even a clobber recoverable. A soft lock was rejected as introducing a failure mode strictly worse than the one it prevents: a crashed tab holding a lock on a single-user machine, with no second party to release it. |
