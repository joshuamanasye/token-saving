"""Self-check for token_guard.py: runs the hook as Claude Code does (JSON on stdin)
and asserts deny/allow per command. Run: python .claude/hooks/test_token_guard.py"""
import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token_guard.py")


def denied(tool, tool_input, cwd):
    out = subprocess.run([sys.executable, HOOK], input=json.dumps(
        {"tool_name": tool, "tool_input": tool_input, "cwd": cwd}), capture_output=True, text=True).stdout
    return bool(out) and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def main():
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "sub"))
    for name, n in (("big.txt", 1000), ("small.txt", 50), ("sub/big.txt", 1000)):
        with open(os.path.join(d, name), "w") as fh:
            fh.write("x\n" * n)
    big = os.path.join(d, "big.txt")
    cases = [
        # (tool, command or input, expect deny)
        ("Bash", "cat big.txt", True),
        ("Bash", "cat small.txt", False),
        ("Bash", "cat big.txt 2>/dev/null", True),
        ("Bash", "cat big.txt > copy.txt", False),
        ("Bash", "cat big.txt | head -50", False),
        ("Bash", "cat big.txt | wc -l", False),
        ("Bash", "cd sub && cat big.txt", True),
        ("Bash", "cat > out.txt <<'EOF'\ncat big.txt\nEOF", False),
        ("Bash", "cat > out.txt <<'EOF'\nhello\nEOF\ncat big.txt", True),
        ("Bash", "sed -n 1,500p big.txt", True),
        ("Bash", "sed -n 1,200p big.txt", False),
        ("Bash", "sed -n '100,$p' big.txt", True),
        ("Bash", "sed -n '900,$p' big.txt", False),
        ("Bash", "head -n 5000 big.txt", True),
        ("Bash", "head -n 100 big.txt", False),
        ("Bash", "head big.txt", False),
        ("Bash", "tail -n +2 big.txt", True),
        ("Bash", "tail -n 30 big.txt", False),
        ("Bash", "grep -v foo big.txt", True),
        ("Bash", "grep -v foo big.txt | head", False),
        ("Bash", "grep foo big.txt", False),
        ("Bash", "git log --oneline -5", False),
        ("Bash", "git log -p", True),
        ("Bash", "git log -p -2 -- x.go", False),
        ("Bash", "git show abc123", True),
        ("Bash", "git show --format= abc123 -- x.go", False),
        ("Bash", "git show HEAD:go.mod", False),
        ("Bash", "python - <<'EOF'\nprint('git log -p and git show abc')\nEOF", False),
        ("PowerShell", "Get-Content big.txt", True),
        ("PowerShell", f"Get-Content \"{big}\"", True),
        ("PowerShell", "Get-Content big.txt -TotalCount 50", False),
        ("PowerShell", "Get-Content big.txt | Select-Object -First 20", False),
        ("PowerShell", "type big.txt", True),
        ("PowerShell", "Set-Location sub; gc big.txt", True),
        ("Read", {"file_path": big}, True),
        ("Read", {"file_path": big, "offset": 10, "limit": 100}, False),
        ("Read", {"file_path": big, "limit": 5000}, True),
        ("Read", {"file_path": os.path.join(d, "small.txt")}, False),
    ]
    bad = []
    for tool, inp, want in cases:
        ti = inp if isinstance(inp, dict) else {"command": inp}
        if denied(tool, ti, d) != want:
            bad.append(f"{tool} {inp!r}: want {'deny' if want else 'allow'}")
    print("\n".join(bad) or f"ok {len(cases)} cases")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
