# Token saving for Claude Code projects

A drop-in kit plus the reasoning behind it. Copy what you need into any repository.

## For AI agents: install into the user's repository

You were given this link to apply the kit. Do these steps in the user's project root; each is
safe to re-run. Do not commit unless the user asks.

1. **Fetch** into a temp dir (not the project):
   `git clone --depth 1 https://github.com/joshuamanasye/token-saving.git "$TMPDIR/token-saving"`
   (PowerShell: `$env:TEMP	oken-saving`).
2. **Copy** `.claude/hooks/token_guard.py` and `.claude/hooks/test_token_guard.py` into the
   project's `.claude/hooks/`. Copy `.claude/agents/worker.md` only if no agent named `worker`
   exists; otherwise show the user the difference.
3. **Merge** the `PreToolUse` entry of this repo's `.claude/settings.json` into the project's
   `.claude/settings.json` (create it if missing). Keep every existing hook. The matcher must be
   `Read|Bash|PowerShell` with no `if` field. If `python` is not on PATH but `python3` is, use
   `python3` in the command.
4. **Paste** `CLAUDE-snippet.md` into the project's `CLAUDE.md` (create it if missing) as one
   section, unless a token-discipline section already exists (then merge, don't duplicate).
   Replace `./scripts/gates.sh` with the project's real check command (look in `package.json`,
   `Makefile`, CI config); if there is none, drop that bullet. Drop the browser/database bullets
   if the project has neither.
5. **Verify:** `python .claude/hooks/test_token_guard.py` must print `ok N cases`. If the project
   has a gate/CI script, add that line to it.
6. **Report** to the user in a few lines: files added/changed, the self-check result, and that
   hooks and agents load only at session start, so they must restart the session (or run
   `/compact` / open a new one) before the guard is active.

```
.claude/settings.json        hook wiring (merge into yours)
.claude/hooks/token_guard.py denies the expensive habits (big Read, git show, shell file dumps)
.claude/hooks/test_token_guard.py self-check for the hook (45 cases)
.claude/agents/worker.md     lean Sonnet subagent for delegated mechanical work
CLAUDE-snippet.md            rules to paste into the project's CLAUDE.md
BRIEF-template.md            how to brief a worker
tools/analyze_tokens.py      measure a session (and its subagents) from its transcript
```

## The cost model

**Cost ≈ context size × number of calls.** Every model call re-sends the whole conversation:
system prompt, tool schemas, project instructions, and every tool result so far. So:

- A call never starts at zero. The fixed part (harness + tool schemas + CLAUDE.md) was measured at
  **~60–80k tokens** per call for a full-toolset session.
- A 15k file dump at call 10 is still being paid for at call 90. A tool result costs
  *its size × the calls left in the session*, not its size once.
- Context grows with calls, so a session's cost grows roughly **quadratically** with its length.
- Writing code is a small part of it (~20% in one measurement). Tool *output* nobody reads is the
  largest controllable item.

Cache reads are cheap per token (about 10% of input price), which is why long contexts look
affordable per call — but they are paid on every call, and they dominate long sessions anyway.

## What we measured (one long autonomous run)

| | Calls | Median context | Share of cost |
|---|---:|---:|---:|
| Main session (large model) | 931 | 147k | 55% |
| 28 subagents (cheaper model) | 1,437 | 140–230k | **45%** |

1. **Subagent baseline.** A general-purpose subagent started every call at **57k** tokens, mostly
   tool schemas it never used (browser tools etc.). The same trivial task in an agent restricted to
   6 tools: **15k vs 62k**. The restricted agent still loads CLAUDE.md.
2. **Shell dumps.** Of 4.5 MB subagent tool output, **3.6 MB was `cat` / `sed -n` / `grep -v` of whole
   files**. A hook already blocked whole-file `Read`; the agents simply routed around it.
3. **Worker length.** The 8 most expensive workers each ran 80–108 calls at ~200k median context.
   Splitting a 100-call task into two 50-call tasks saves ~35% (quadratic growth).
4. **Orchestrator doing the work.** The main session read 1.4 MB itself. In an autonomous run
   nobody types `/compact`, so it stayed in context until auto-compaction.

Earlier measurements in the same kind of project:

- One session covering six unrelated tasks averaged ~340k tokens *per call*; output from the first
  task was still being re-sent during the sixth. Compacting after each committed task would have
  cut 27–39%.
- Per-call rules (no verbose test output, targeted reads) held well; the biggest single results
  were whole-file reads of large docs and `git show` reprinting long commit messages. Written rules
  bind decisions, not habits — **habits need a hook**.

## Strategy, in order of impact

### 1. Session boundaries (biggest lever)

- **One task per session. `/compact` (or `/clear`) after each committed task.** Only the user can
  type it; the agent should end its reply with a nudge after a commit and stop, not start the next
  task in the same breath.
- **Long multi-item runs: one fresh session per item.** The orchestrator keeps a short plan and
  reads short reports; it does not carry each item's file reads.

### 2. Delegate to lean subagents

- Use a **restricted-tool agent** (`.claude/agents/worker.md`: Sonnet; Bash, Read, Edit, Write,
  Grep, Glob) instead of general-purpose. ~4× smaller fixed cost on every call.
  Agent files are loaded at session start — restart after adding one.
- **~40 tool calls per worker.** Split big jobs by module / file set. Tell workers to stop and
  report when the task is bigger than briefed.
- **Self-contained brief in a file** (see `BRIEF-template.md`): goal, files allowed, verification
  commands, report length. The worker should not need to explore to find out what to do.
- Parallel workers only on disjoint files; shared resources (test database, build dir) serialize.
- **A worker's report is a claim, not evidence.** The orchestrator re-runs the gates itself.
- Read-only lookups ("where is X used") also go to a lean read-only agent; it returns a short table
  instead of the orchestrator reading the files.

### 3. Don't let output in (hooks enforce; prose only reminds)

- `Grep` before `Read`; read ranges (`offset`/`limit`), not whole files.
- No `cat` of large files, no wide `sed -n` ranges, no `grep -v` file dumps (hook-enforced).
- `git show --format= <hash> -- <path>`; `git log --oneline`.
- One wrapper script for all gates printing **one line per gate**, full output only for failures.
  Tests without verbose flags; filter to failures.
- Database: ask for the one value (`psql -tAc "select count(*) …"`), never `SELECT *` to look.
- Edit a file already read with the `Edit` tool, not `sed`/scripts — a shell edit on a file the
  harness has seen echoes the whole changed file back.
- Browser: use JS evaluation / find / page text for checks, not full accessibility-tree dumps
  (they repeat the whole nav every time). Screenshots only as final proof, scaled down, once —
  every image stays in context for the rest of the session.
- Don't re-verify what already passed with no edits since.

### 4. Keep the fixed part small

- CLAUDE.md is loaded on **every** call of the main session and every subagent. Keep rules there,
  move evidence and history to a separate doc that is read on demand.
- Disable MCP servers / plugins the project doesn't use; each adds tool schemas to every call.

## Measure, then tune

```bash
python tools/analyze_tokens.py ~/.claude/projects/<project-dir>/<session-id>.jsonl
```

Prints calls, median/p90 context, estimated cost (edit `PRICE`), tool output by tool (shell file
dumps split out), the largest single results, and per-subagent cost / starting context / median.
What to look for:

- **Starting context** of subagents well above ~20k → they run with the full toolset.
- **`Bash(file dump)`** large → find which shape got through and add it to the hook. Lower the
  limits only for outputs nobody used: a denied call costs one more round trip at the full
  context (60-80k tokens), so splitting a legitimate 20 KB read into two calls costs more.
- **Median context** over ~150k with many calls → sessions or workers run too long; split.
- One result over ~20 KB → find the habit that produced it and add it to the hook.

## Install

1. Copy `.claude/hooks/token_guard.py` and `.claude/agents/worker.md`; merge
   `.claude/settings.json` into the project's (the matcher `Read|Bash|PowerShell` must have no `if` filter, or
   the shell-dump guard never runs; an `if` like `Bash(git show*)` silently limits it to that one command). Requires `python` on PATH.
2. Paste `CLAUDE-snippet.md` into the project's CLAUDE.md; adjust the gate/test commands.
3. Restart the session so the agent and hook load.
4. Check: `python .claude/hooks/test_token_guard.py` prints `ok`; add it to the project's gate script.
   Then in a session, `cat <some file over 400 lines>` should be denied with a hint.
