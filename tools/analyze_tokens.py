"""Token report for one Claude Code session, including its subagents.

Usage: python analyze_tokens.py <session.jsonl>
Session transcripts live in ~/.claude/projects/<project-dir>/<session-id>.jsonl; subagent
transcripts in <session-id>/subagents/*.jsonl next to it.

Context per call = input + cache_read + cache_creation tokens (deduplicated by message id).
Cost uses the PRICE table below (USD per million tokens, input/output); edit it to current prices.
Cache reads are billed at 10% of input, cache writes at 125%.
"""
import collections
import glob
import json
import os
import re
import statistics as st
import sys

PRICE = {"opus": (5, 25), "sonnet": (3, 15), "haiku": (1, 5)}
DUMP = re.compile(r"\bcat |sed -n|grep -v")


def cost(model, u):
    key = next((k for k in PRICE if k in (model or "")), "sonnet")
    i, o = PRICE[key]
    return (u.get("input_tokens", 0) * i + u.get("cache_read_input_tokens", 0) * i * 0.1
            + u.get("cache_creation_input_tokens", 0) * i * 1.25 + u.get("output_tokens", 0) * o) / 1e6


def scan(path):
    msgs, results, uses, first = {}, {}, {}, None
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        m = d.get("message") or {}
        if d.get("type") == "assistant" and isinstance(m, dict):
            if m.get("id") and m.get("usage"):
                msgs[m["id"]] = (m.get("model"), m["usage"])
            for c in m.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    uses[c["id"]] = (c["name"], c.get("input") or {})
        if d.get("type") == "user":
            if isinstance(m.get("content"), list):
                for c in m["content"]:
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        results[c.get("tool_use_id")] = len(json.dumps(c.get("content")))
            elif first is None and isinstance(m.get("content"), str):
                first = m["content"][:60].replace("\n", " ")
    return msgs, results, uses, first


def ctx(u):
    return u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)


def tool_kb(results, uses):
    by = collections.Counter()
    for tid, size in results.items():
        name, inp = uses.get(tid, ("?", {}))
        if name == "Bash" and DUMP.search(inp.get("command", "")):
            name = "Bash(file dump)"
        by[name] += size
    return {k: v // 1024 for k, v in by.most_common(8)}


def main(path):
    msgs, results, uses, _ = scan(path)
    c = [ctx(u) for _, u in msgs.values()]
    main_cost = sum(cost(*v) for v in msgs.values())
    print(f"main: calls={len(c)} median_ctx={st.median(c) / 1e3:.0f}k p90={sorted(c)[int(len(c) * .9)] / 1e3:.0f}k "
          f"min={min(c) / 1e3:.0f}k cost=${main_cost:.1f}")
    print("  tool output KB:", tool_kb(results, uses))
    big = sorted(((s, uses.get(t, ("?", {}))) for t, s in results.items()), key=lambda x: -x[0])[:8]
    for s, (name, inp) in big:
        print(f"   {s // 1024}KB {name} {json.dumps(inp)[:100]}")
    rows, sub_cost, all_res, all_uses = [], 0, {}, {}
    for p in glob.glob(os.path.join(path[:-len(".jsonl")], "subagents", "*.jsonl")):
        m, r, u, first = scan(p)
        if not m:
            continue
        cc = [ctx(x) for _, x in m.values()]
        k = sum(cost(*v) for v in m.values())
        sub_cost += k
        all_res.update(r)
        all_uses.update(u)
        rows.append((k, len(cc), min(cc), st.median(cc), max(cc), first or ""))
    if rows:
        print(f"subagents: {len(rows)} cost=${sub_cost:.1f} ({sub_cost / (sub_cost + main_cost):.0%} of total)")
        print("  tool output KB:", tool_kb(all_res, all_uses))
        print("  cost  calls start  median  max  brief")
        for k, n, lo, med, hi, first in sorted(rows, reverse=True)[:15]:
            print(f"  ${k:5.1f} {n:4d} {lo / 1e3:4.0f}k {med / 1e3:5.0f}k {hi / 1e3:4.0f}k  {first}")


if __name__ == "__main__":
    main(sys.argv[1])
