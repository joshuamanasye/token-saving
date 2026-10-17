"""PreToolUse guard against the habits that fill an agent's context with text nobody reads.

Written rules bind an agent at decision points but not habits, so these are enforced:
- `Read` of a big file without a range (or with a huge `limit`);
- `git show` without `--format=` (reprints the whole commit message above every diff), and
  `git log -p` without a count;
- whole-file dumps through the shell, Bash or PowerShell (`cat`/`type`/`Get-Content`, `grep -v`,
  wide `sed -n` ranges, `head`/`tail` with large counts). Once `Read` is guarded, agents route
  around it this way; measured, these were ~80% of subagent tool output.

Everything read stays in context and is re-sent on every later call, so one dump costs its size
times the number of calls left in the session. Deny, never ask: the cheap form becomes the only form.
Commands are normalised first (`X=1`/`env` prefixes, `( )`, `bash -c '...'`, every `| && ;` segment)
so `X=1 cat f` or `cat f | head -n 900` is judged like `cat f`. `TOKEN_GUARD=off` skips shell checks.
One call may print MAX_DUMP lines per statement and MAX_LINES in total (`cat a; cat b; cat c`).
The caps stay high on purpose: a denied call costs one more round trip at the full context
(60-80k tokens), so splitting a legitimate 20 KB read is a net loss. Tune the limits per project. Self-check: python .claude/hooks/test_token_guard.py
"""
import json
import os
import re
import shlex
import sys

MAX_LINES = 800      # Read without a range
MAX_DUMP = 400       # lines a shell command may print from files
READERS = {"cat", "type", "get-content", "gc", "nl", "less", "more", "tac", "bat"}
CD = {"cd", "set-location", "sl", "pushd", "chdir"}
# `bash -c '...'` / `sh -lc "..."` is judged by what it runs
SHELL_C = re.compile(r"\b(?:ba|z)?sh\s+-l?c\s+(['\"])(.*?)\1", re.S)


def deny(reason):
    json.dump({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}, sys.stdout)
    sys.exit(0)


def count_lines(cwd, name):
    """Line count of a file named on a command line; 0 when it is not a readable file."""
    name = name.strip("'\"")
    m = re.match(r"^/([a-zA-Z])/(.*)", name)  # Git Bash /e/x -> E:/x
    if m:
        name = f"{m.group(1).upper()}:/{m.group(2)}"
    path = name if os.path.isabs(name) or re.match(r"^[A-Za-z]:", name) else os.path.join(cwd, name)
    try:
        with open(path, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def guard_read(tool_input):
    path = tool_input.get("file_path") or ""
    limit = tool_input.get("limit") or 0
    if limit and limit <= MAX_LINES:
        return
    # offset alone reads up to 2000 lines from there
    lines = count_lines(os.getcwd(), path) - (tool_input.get("offset") or 0)
    if lines > MAX_LINES:
        deny(
            f"{path} is {lines} lines; a whole-file read stays in context for the rest of the "
            f"session. Grep for the section you need, or Read with offset/limit (limit <= {MAX_LINES})."
        )


def guard_git(cmd):
    # Only `git` in command position: `grep "git show" f` merely mentions it.
    if re.search(r"(^|[;&|({\n]\s*)git show\b", cmd) and "--format=" not in cmd and "--oneline" not in cmd \
            and not re.search(r"git show \S+:\S", cmd):
        deny(
            "`git show` reprints the whole commit message above the diff. "
            "Use `git show --format= <hash> -- <path>` "
            "for the diff alone; `git log -1 <hash>` when you actually want the message."
        )
    if re.search(r"(^|[;&|({\n]\s*)git log\b[^|;&]*\s(-p|--patch)\b", cmd) \
            and not re.search(r"\s(-\d+|-n\s*\d+|--max-count[= ]\d+)", cmd):
        deny("`git log -p` without a count prints every diff in history. Add `-1`/`-n N` and a `-- <path>`.")


def strip_heredocs(cmd):
    """Drop heredoc bodies: `cat > f <<EOF ... EOF` is a write, and its body is not a command."""
    return re.sub(r"<<-?\s*(['\"]?)(\w+)\1([^\n]*)\n.*?\n\s*\2\s*(?=\n|$)", r"\3", cmd, flags=re.S)


def stdout_redirected(stage):
    # `> f`, `>> f`, `&> f`, `| Out-File`; not `2>` / `2>&1`, which still print stdout.
    return bool(re.search(r"(^|[^0-9&])>{1,2}\s*[^&\s]|&>|\bout-file\b|\bset-content\b", stage, re.I))


def words_of(stage):
    """Words of one pipeline stage, without ( ) { } wrappers, VAR=value prefixes or `env`."""
    try:
        words = [w.strip("'\"") for w in shlex.split(re.sub(r"^[\s({]+|[\s)}]+$", "", stage), posix=False)]
    except ValueError:
        return []
    while words:
        if re.match(r"[A-Za-z_]\w*=", words[0]):
            words = words[1:]
        elif words[0] == "env":
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[2 if words[0] == "-u" else 1:]
        else:
            break
    return words


def num_after(words, flags):
    for i, w in enumerate(words):
        lw = w.lower()
        for f in flags:
            if lw == f and i + 1 < len(words) and re.fullmatch(r"\+?\d+", words[i + 1]):
                return words[i + 1]
            if lw.startswith(f) and re.fullmatch(r"\+?\d+", w[len(f):].lstrip("=")):
                return w[len(f):].lstrip("=")
    return None


def head_count(args):
    """Lines head/tail keep: "N", or "+K" for tail from line K to the end."""
    n = num_after(args, ("-n", "--lines"))
    if n is None:
        m = next((w for w in args if re.fullmatch(r"-\d+", w)), None)
        n = m[1:] if m else "10"
    return n


def bound(words):
    """Lines a later pipeline stage lets through, or None when it passes everything on."""
    cmd = words[0].lower()
    if cmd in ("head", "tail"):
        n = head_count(words[1:])
        return None if n.startswith("+") else int(n)
    if cmd in ("wc", "measure-object", "measure") or (cmd == "grep" and "-c" in words):
        return 0
    if cmd in ("select-object", "select"):
        n = num_after(words[1:], ("-first", "-last"))
        return int(n) if n else None
    return None


def awk_files(args):
    """Files awk prints whole (program `1` or an unconditional `{print ...}`), else None."""
    if any(w.startswith("-f") for w in args):
        return None
    pos, skip = [], False
    for w in args:
        if skip or w.startswith("-"):
            skip = w in ("-F", "-v")
            continue
        pos.append(w)
    prog = pos[0] if pos else ""
    if re.fullmatch(r"1|\{\s*print\b[^}]*\}", prog) and not re.search(r"\b(if|exit|next)\b", prog):
        return pos[1:]
    return None


def dump_size(words, cwd):
    """Lines a single command would print from files, or 0 if it is not a file dump."""
    cmd = words[0].lower()
    args = words[1:]
    files = lambda ws: sum(count_lines(cwd, w) for w in ws if not w.startswith("-"))
    if cmd == "bat" and any(w.startswith(("-r", "--line-range")) for w in args):
        return 0
    if cmd in READERS:
        n = num_after(args, ("-totalcount", "-head", "-first", "-tail", "-last"))
        return int(n) if n else files(args)
    if cmd == "awk":
        return files(awk_files(args) or [])
    if cmd in ("head", "tail"):
        n = head_count(args)
        total = files(args)
        if n.startswith("+"):  # tail -n +K: from line K to the end
            return max(total - int(n) + 1, 0)
        return min(int(n), total) if total else 0
    if cmd == "sed" and "-n" in args:
        stage = " ".join(args)
        total = files([w for w in args if not re.search(r"\d+,", w)])
        worst = 0
        for a, b in re.findall(r"(\d+),(\d+|\$)p", stage):
            worst = max(worst, (total if b == "$" else int(b)) - int(a) + 1)
        return worst
    if cmd == "sed" and not any(w.startswith("-i") or w == "--in-place" for w in args):
        return files(args)  # a substitution without -n/-i prints the whole file
    if cmd == "grep" and any(w in ("--invert-match",) or re.fullmatch(r"-[a-zA-Z]*v[a-zA-Z]*", w) for w in args):
        rest = [w for w in args if not w.startswith("-")]
        return files(rest[1:])  # first non-flag word is the pattern
    return 0


def guard_dump(cmd, cwd):
    total = 0
    for stmt in re.split(r"&&|\|\||;|\n", SHELL_C.sub(r"\2", strip_heredocs(cmd))):
        stages = [s.strip() for s in stmt.split("|")]
        words = words_of(stages[0])
        if not words:
            continue
        if words[0].lower() in CD and len(words) > 1:
            target = words[1]
            cwd = target if os.path.isabs(target) or re.match(r"^([A-Za-z]:|/)", target) else os.path.join(cwd, target)
            m = re.match(r"^/([a-zA-Z])/(.*)", cwd)
            if m:
                cwd = f"{m.group(1).upper()}:/{m.group(2)}"
            continue
        if any(stdout_redirected(s) for s in stages):
            continue
        n = dump_size(words, cwd)
        for w in map(words_of, stages[1:]):
            if w:
                b = bound(w)
                n = n + dump_size(w, cwd) if b is None else min(n, b)
        if n > MAX_DUMP:
            deny(f"`{stages[0][:60]}` would print ~{n} lines into context, re-sent on every later call. "
                 f"Grep for what you need, or print a range of at most {MAX_DUMP} lines "
                 f"(`sed -n A,Bp`, Read with offset/limit).")
        total += n
    if total > MAX_LINES:
        deny(f"This call would print ~{total} lines across its statements, more than one Read may "
             f"({MAX_LINES}). Read only the files you are about to change, or grep the rest.")


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    if tool == "Read":
        guard_read(tool_input)
    elif tool in ("Bash", "PowerShell"):
        cmd = strip_heredocs(tool_input.get("command") or "")
        if re.search(r"\bTOKEN_GUARD=off\b", cmd):
            return  # explicit escape hatch, for the rare call whose full output is needed
        guard_git(cmd)
        guard_dump(cmd, payload.get("cwd") or os.getcwd())


if __name__ == "__main__":
    main()
