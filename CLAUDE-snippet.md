## Token discipline

Cost = context size × call count. Every call re-sends everything read so far; a call starts at
~60–80k tokens before any work. Evidence: keep it in a separate doc, not here.

- **`/compact` after each committed task.** After a commit, end the reply with a `/compact` nudge
  and stop; don't start the next task. Only the user can type it.
- **Gates through one script** (`./scripts/gates.sh` or equivalent), one line per gate. Tests
  without verbose flags unless one fails; filter output to failures.
- **Grep before Read**; read ranges with `offset`/`limit` unless about to edit heavily.
- **Edit a file you already Read** with `Edit`, not shell edits (they echo the whole file back).
- **Database:** `psql -tAc` for one value, `-tA` for rows; never `SELECT *` to look.
- **Browser:** JS evaluation / find / page text for checks; screenshots are final proof only,
  one at the end, scaled ≤ 0.5. Never re-read an unchanged page. Don't re-verify what passed.
- **Delegation:** mechanical work goes to `subagent_type: "worker"` (`.claude/agents/worker.md`,
  6 tools, ~15k start vs ~60k for general-purpose). Brief in a file; ~40 tool calls per worker,
  split bigger tasks; disjoint files for parallel workers. Re-run the gates yourself — a worker's
  report is a claim, not evidence.
- **Long multi-item runs:** one fresh session per item; the orchestrator reads reports, not files.
- **Hook-enforced** (`.claude/hooks/token_guard.py`, Bash and PowerShell): `Read` over 800 lines
  without a range, `git show` without `--format=`, `git log -p` without a count, any shell command
  printing over 400 lines of a file (`cat`/`Get-Content`, `grep -v`, `sed`, `head`/`tail`, `awk 1`,
  `nl`, `less`, also behind `X=1`, `env`, `( )`, `bash -c` or a wide `| head`) or over 800 lines in
  one call. Prefix a command with `TOKEN_GUARD=off` for the rare case the full output is needed.
  Extend the hook and its test, not this list, when a habit keeps drifting.

## Design → test → review (non-trivial features)

1. **Rules first.** Before code, write 5–15 lines: who may do what, state transitions, money or
   other irreversible effects, and where each rule is enforced. Server-side always; a client check
   is UX only. Put them in the plan (plan mode) and keep them for step 3.
2. **One test per rule**, including the refusal (wrong role, wrong state, client check skipped).
3. **Independent review for risky changes** (authorization, money, deletes, migrations, the
   project's core domain): `subagent_type: "reviewer"` (`.claude/agents/reviewer.md`: Opus,
   read-only, fresh context). Brief = diff range + the rules + ONE lens (`security`, `data`,
   `domain`, `ui`); never your summary of the work. Run 2–3 lenses in parallel for the riskiest.
   Small or cosmetic changes skip this.
4. **Verify each finding** against code or data before fixing; reviewers report false positives too.
5. **Every real bug leaves a regression test.** Same bug class twice → make it a mechanical check
   (architecture test, hook, lint), not another prose line. Done = no HIGH findings, every rule tested.
