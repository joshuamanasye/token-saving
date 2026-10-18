// After any compaction (manual /compact or automatic, mid-task included), hand the
// agent the live worktree state so uncommitted work is not reconstructed from a
// summary that may predate it. Costs a few hundred tokens once per compaction.
import { execFileSync } from "node:child_process";
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

const MAX_STATUS_LINES = 40;

function git(cwd: string, args: string[]): string {
	try {
		return execFileSync("git", args, { cwd, encoding: "utf8", windowsHide: true, timeout: 5_000 }).trimEnd();
	} catch {
		return "(git failed)";
	}
}

export default function compactionState(pi: ExtensionAPI): void {
	pi.on("session_compact", async (_event, ctx) => {
		const status = git(ctx.cwd, ["status", "--short"]).split("\n");
		const shown = status.slice(0, MAX_STATUS_LINES).join("\n") || "(clean)";
		const more = status.length > MAX_STATUS_LINES ? `\n… ${status.length - MAX_STATUS_LINES} more` : "";
		const content = [
			"Worktree state right after compaction (live git; trust it over the summary where they differ):",
			"```",
			"$ git status --short",
			shown + more,
			"$ git log --oneline -3",
			git(ctx.cwd, ["log", "--oneline", "-3"]),
			"```",
		].join("\n");
		// Idle (manual /compact): append without starting a turn. Mid-run: inject at the next step.
		pi.sendMessage(
			{ customType: "compaction-state", content, display: false },
			{ deliverAs: ctx.isIdle() ? "nextTurn" : "aside" },
		);
	});
}
