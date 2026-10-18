// omp port of the Claude Code PreToolUse hook: maps omp `read`/`bash` calls onto the
// Claude payload and lets .claude/hooks/token_guard.py decide, so the rules live in
// one place. Fails open: a missing python or a crashed guard never blocks a tool.
import { type ChildProcess, spawn } from "node:child_process";
import * as path from "node:path";
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

const PYTHON = process.platform === "win32" ? "python" : "python3";
const TIMEOUT_MS = 10_000;

// A bare omp read of these returns an outline or a decoded view, not raw lines.
const OUTLINED = /\.(go|ts|tsx|js|jsx|mjs|cjs|vue|svelte|py|rs|java|kt|cs|c|h|cpp|hpp|rb|php|swift|db|sqlite|zip|jar|tar|gz|tgz|7z|pdf|docx|xlsx|pptx|png|jpe?g|gif|webp|svg|svgz|ipynb|mp4|mov|webm)$/i;
const RANGE = /^[\d,+-]+$/;
const MODIFIER = /^(raw|conflicts|img)$/;

interface ReadArgs {
	file_path: string;
	offset?: number;
	limit?: number;
}

/** Translate an omp read path (`file.md:50-80`, `f:-20`, `f:5-9,40-60:raw`) into Read offset/limit. */
export function readArgs(rawPath: string, cwd: string): ReadArgs | undefined {
	// Internal URIs, URLs and `?q=`/`?limit=` queries do not return whole files.
	if (/^[a-z][a-z0-9+.-]*:\/\//i.test(rawPath) || rawPath.includes("?")) return undefined;
	const segments = rawPath.split(":");
	const ranges: string[] = [];
	while (segments.length > 1) {
		const last = segments[segments.length - 1];
		if (MODIFIER.test(last)) segments.pop();
		else if (last !== "" && RANGE.test(last)) ranges.push(segments.pop()!);
		else break;
	}
	const file = segments.join(":");
	if (!file) return undefined;
	const file_path = path.resolve(cwd, file);
	if (ranges.length === 0) return OUTLINED.test(file) ? undefined : { file_path };

	let limit = 0;
	for (const part of ranges.join(",").split(",")) {
		let m: RegExpMatchArray | null;
		if ((m = part.match(/^(\d+)-(\d+)$/))) limit += Math.max(0, +m[2] - +m[1] + 1);
		else if ((m = part.match(/^\d+\+(\d+)$/))) limit += +m[1];
		else if ((m = part.match(/^-(\d+)$/))) limit += +m[1];
		else if ((m = part.match(/^(\d+)-?$/))) return { file_path, offset: +m[1] - 1 }; // open-ended: to EOF
	}
	return { file_path, limit };
}

/** Run the Python guard; resolves to its deny reason, or undefined to allow. */
function runGuard(script: string, cwd: string, payload: unknown): Promise<string | undefined> {
	const { promise, resolve } = Promise.withResolvers<string | undefined>();
	let child: ChildProcess;
	try {
		child = spawn(PYTHON, [script], { cwd, stdio: ["pipe", "pipe", "ignore"], windowsHide: true });
	} catch {
		resolve(undefined);
		return promise;
	}
	let out = "";
	const timer = setTimeout(() => child.kill(), TIMEOUT_MS);
	child.stdout!.on("data", chunk => (out += chunk));
	child.on("error", () => resolve(undefined));
	child.on("close", () => {
		clearTimeout(timer);
		try {
			const decision = JSON.parse(out)?.hookSpecificOutput;
			resolve(decision?.permissionDecision === "deny" ? String(decision.permissionDecisionReason) : undefined);
		} catch {
			resolve(undefined);
		}
	});
	child.stdin!.on("error", () => {});
	child.stdin!.end(JSON.stringify(payload));
	return promise;
}

export default function tokenGuard(pi: ExtensionAPI): void {
	pi.on("tool_call", async (event, ctx) => {
		const cwd = ctx.cwd;
		const input = event.input as Record<string, unknown>;
		let payload: Record<string, unknown> | undefined;
		if (event.toolName === "read" && typeof input.path === "string") {
			const args = readArgs(input.path, cwd);
			if (args) payload = { tool_name: "Read", tool_input: args, cwd };
		} else if (event.toolName === "bash" && typeof input.command === "string") {
			const dir = typeof input.cwd === "string" ? path.resolve(cwd, input.cwd) : cwd;
			payload = { tool_name: "Bash", tool_input: { command: input.command }, cwd: dir };
		}
		if (!payload) return;
		const reason = await runGuard(path.join(cwd, ".claude", "hooks", "token_guard.py"), cwd, payload);
		if (reason) return { block: true, reason: `${reason} (omp: offset/limit = a \`path:N-M\` selector; \`path:N\` reads to EOF.)` };
	});
}
