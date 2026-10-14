# AI Usage

**Tool:** Claude (Anthropic), used as a pair programmer in a chat session linked to this repository folder.
It read files and wrote code into the working tree. I ran every command myself in the recorded terminal:
Docker, migrations, tests, curl, git. Commits that contain AI-written code carry a
`Co-Authored-By: Claude` trailer.

**Why `.ai-conversations/` is empty:** the pre-commit hook copies local tool folders (`.claude/`,
`.cursor/`, …). This conversation lives in the Claude app, not in the repo, so there was nothing for
the hook to capture. The screen recording shows the interaction instead (see README).

## How the work was split

| Step | Me | Claude |
|---|---|---|
| Setup, env, Airtable base | Created the base and table, set the token, ran setup and the initial tests | Spotted that `settings.py` doesn't read `.env` → `env_file` fix |
| Part 1 review | Chose the order by business impact, reproduced the bug with curl | Read the code with me and drafted REVIEW.md |
| Part 2 fix | Captured the curl proof before and after | Wrote the authorization check and regression tests |
| 3c export | Supplied the real base and checked the result in Airtable (screenshot, re-run) | Wrote the exporter, the test double and the tests |
| 3a / 3b | Asked for a full re-read of the assignment doc before moving on | Built the features; the re-read surfaced the audit-trail gap |

## Where I steered or corrected

- **Re-read the brief before going further.** After 3a I asked for the doc to be checked line by line
  against the repo. That surfaced the *"comments are part of the engagement audit trail"* hint: the
  first comments model used `on_delete=CASCADE`, so deleting a task silently erased its comments.
  Fixed in `07a2b19`.
- **Commit and push each part before starting the next**, so the history shows one feature per step.
- **Doc vs repo conflict (npm `airtable` vs `pyairtable`):** went with the repo's README and the Django
  server, and wrote it down in DESIGN_NOTES.md instead of silently ignoring the doc.
- **Checking AI claims against real output:** the frontend `tsc` errors were confirmed to come only
  from `node_modules` typings (`--skipLibCheck` passes with zero errors in `src/`). Two
  `makemigrations` warnings were confirmed to be an upstream index-name mismatch, not the new
  migrations, and that migration was deliberately not generated.
- **A mistake and its recovery:** I ran `reset_audit_trail --yes` by accident, which erased the demo
  comment and allowed a seeded task to be deleted. We restored the task with its original UUID and
  the seed values instead of re-seeding, because re-seeding would have changed every UUID and
  orphaned the Airtable rows. Details are in DESIGN_NOTES.md.
