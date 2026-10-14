# Screen Recording

**▶ https://youtu.be/QSP9_KbvheA** (unlisted on YouTube, so anyone with the link can watch)

Full narrated session recorded on 14 Oct 2026 (IST), with the terminal visible throughout. It covers:

1. Setup: `docker compose up --build`, migrate, seed, initial test run (15 backend / 9 frontend)
2. Part 1: code review (`REVIEW.md`) with live curl proof of the task PATCH authorization bug
3. Part 2: the fix, its tests, and the same curl before (200) and after (403)
4. Part 3c: Airtable export (real base, a second run creating no duplicates, viewer gets 403)
5. Part 3a: append-only task comments, plus making them a protected audit trail
6. Part 3b: activity feed and the rollback decision
7. Final test run: 74 backend / 13 frontend passing

The terminal output for the same session is in [`TERMINAL_LOG.md`](TERMINAL_LOG.md). Design decisions are in [`DESIGN_NOTES.md`](DESIGN_NOTES.md), and how AI tools were used is in [`AI_USAGE.md`](AI_USAGE.md).
