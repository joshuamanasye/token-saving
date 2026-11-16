# Workflow: pick → work → review → PR → merge gate

Two variants of the same loop. Pick one per run; paste it into the project's `AGENTS.md` (or
`CLAUDE.md`) and replace `<integration>` (the branch PRs target, e.g. `dev`), the tracker, gate and
test commands with the project's own.

| | **Lite** | **Full** |
|---|---|---|
| Tasks per run | 1 | 3 to 5 in parallel |
| Branches | 1 | one per independent task (worktrees) |
| Workers | optional, 1 or more on disjoint files | one per task |
| Reviewer | 1, after the work | 1 for all branches, after every worker |
| Merge gate | you, or one merge agent | one merge agent, PRs one at a time |
| Use when | a single item, small context, tight budget | several independent items in the backlog |

Each phase starts when the user asks for it. The orchestrator does not chain into the next phase
unasked.

## Rules for every agent in both variants

- **No attribution.** Commit messages and PR bodies never carry `Co-Authored-By:`, "Generated with
  Claude Code" or any other AI attribution, even when a harness reminder asks for it; the project's
  rule wins. Every brief to a sub-agent that may commit, open or merge a PR repeats this line.
  Already pushed: rewrite the messages (`git filter-branch --msg-filter` in a bare clone, compare the
  trees) and force-push with `--force-with-lease` only on the user's yes.
- Workers never commit or push; the orchestrator (or the merge agent) commits.
- A sub-agent's report is a claim. Re-run gates and tests yourself before you rely on it.
- Branches start from `origin/<integration>`; PRs target `<integration>`.

## Lite: one task

1. **Pick.** Compare the backlog with the tracker, fix drift, take the top item. Tracker to In
   Progress.
2. **Work.** One branch from `origin/<integration>`. Write the rules (5–15 lines) first. Do it
   yourself, or brief one or more `worker`s on disjoint files (`BRIEF-template.md`).
   Gates + tests from the rules; commit with the rules in the body.
3. **Review** (risky changes only). One `reviewer`: diff range + rules + lenses. Verify each
   finding, fix, then `SendMessage` the same reviewer to re-check the fix commits. Repeat until it
   reports no gap. A HIGH still open after 2 re-checks: stop and report to the user.
4. **PR.** Docs per the project's definition of done, push, open the PR (rules, checklist, what is
   not verified; no attribution). Tracker comment with the link.
5. **Merge.** On the user's word: CI green, merge (merge commit unless the project squashes),
   tracker Done, tick the backlog, `/compact`.

## Full: several tasks at once

1. **Pick.** Compare the backlog with the tracker and fix drift in whichever side is wrong (the
   repo is the status of record). Propose 3 to 5 tasks that can run in parallel: disjoint files, no
   task needs another's result, no two migrations on the same version number. The user chooses.
   Note the start: `git rev-parse origin/<integration>` (used at Close).
2. **Split and brief.** The orchestrator decides the split: one branch per independent task,
   joined only when they touch the same files. Per branch: `git worktree add ../<repo>-<slug> -b
   <branch> origin/<integration>`, copy any gitignored env file the tests need, its own scratch
   test database (and the env var that points the tests at it, written into the brief), tracker In Progress. Briefs in files: one
   common brief (repo rules, docs to update, no attribution, do not commit) plus one per task
   (worktree, scratch DB, rules to test, files allowed).
3. **Workers.** One `worker` per task, all launched in one message. A stalled worker is resumed
   with `SendMessage`, not replaced. When each finishes: re-run its gates and tests, check that the
   test fails with only the fix reverted, commit on its branch with the rules in the body.
4. **One reviewer for all branches**, after every worker is done (`model` override if the user
   names one). Diff ranges of every branch + rules + lenses. Verify → fix → same reviewer re-checks
   → repeat until no gap (HIGH open after 2 re-checks: stop and report). Then docs, push, one PR per branch, tracker comment.
5. **Merge gate.** One `general-purpose` agent (strongest model) with a brief file:
   - For each PR in turn: `git fetch origin`, merge `origin/<integration>` into it (no rebase, no force push; resolve
     changelog and status docs by keeping every entry), review `git diff origin/<integration>...HEAD` against
     the code, gates + tests on the scratch DB.
   - Wrong → brief a `worker` to fix (no commit), check the fix, review again.
   - Clean → commit, push, wait until the PR shows the new CI run, then `gh pr checks <n> --watch`, `gh pr merge <n> --merge`,
     tracker Done + PR comment, next PR.
   - Stop and report instead of merging on: a HIGH finding not fixed in 2 rounds, CI red for a
     reason outside the PR, or a product decision.
   - The brief repeats the no-attribution rule for its own commits and for its workers' briefs.
6. **Close** (the orchestrator, from the real state, not the report): every PR merged,
   `git fetch origin && git log <start>..origin/<integration> --format=%B | grep -ciE
   'co-authored|generated with'` is 0, tracker
   matches (do any transition the agent was refused), tick the backlog and push it, apply new migrations
   locally, remove worktrees and scratch databases, report what stays open, `/compact`.

## Why the cost stays bounded

- Workers start at ~15k tokens instead of ~60k; the orchestrator reads reports, not files.
- One reviewer per run, and its re-checks keep its context: each round reads only the fix commits.
- The merge agent carries the PR context so the orchestrator never loads the diffs.
- `/compact` after the close: the next run starts small.
