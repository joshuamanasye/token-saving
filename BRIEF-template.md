# <ID> — <one-line goal>

Save as a file and start the worker with: "Do the task in <path to this file>."
Keep it self-contained: the worker should not explore to find out what to do.

**Repo / branch:** <path>, <branch>. Never commit or push. Never print secrets.

**Context (3–6 lines):** current state, the decision already made, why.

**Files you may touch:** <list or glob>. Others work in parallel on <their files> — don't edit those.

**Do**
1. <concrete step with file names>
2. <...>

**Size:** expected ~<N> tool calls. Over ~40, stop and report what is left.

**Verify** (exact commands; one-line output each):
- `<gate command>` → ALL GREEN
- `<targeted test command>` → no FAIL

**Report (≤ 15 lines):** files changed, what each verify command printed, anything you could not do,
anything you found that is out of scope (do not fix it).
