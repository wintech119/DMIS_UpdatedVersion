#!/usr/bin/env node
/**
 * PreToolUse hook — gates direct edits to canonical DMIS source-of-truth documents.
 *
 * Wired in `.claude/settings.json` under PreToolUse with the matcher "Write|Edit|MultiEdit".
 * Reads the harness's PreToolUse stdin payload, normalises the file path, and if it matches
 * any gated path returns a JSON `permissionDecision: "ask"` so the harness asks the user for
 * explicit confirmation before the edit runs.
 *
 * Gated paths (sourced from `.agents/skills/system-architecture-review/SKILL.md` and
 * `.claude/CLAUDE.md` "Primary source-of-truth order"):
 *
 * 1. `frontend/src/lib/prompts/generation.ts`
 *      Canonical DMIS component-generation prompt. Drifting it drifts the whole component
 *      library. See `frontend/AGENTS.md:61`.
 *
 * 2. `docs/adr/system_application_architecture.md`
 *      Canonical architecture baseline (CLAUDE.md primary source-of-truth #1).
 *      Architectural decisions need an ADR review before this file changes.
 *
 * 3. `docs/security/**`
 *      Security architecture, threat model, and controls matrix (CLAUDE.md primary
 *      source-of-truth #2-4). Changes should run through the security-review workflow.
 *
 * Behavior:
 * - Match → emit `{ permissionDecision: "ask", permissionDecisionReason: "..." }` so the
 *   harness prompts the user. The user can confirm to proceed if the edit is intentional.
 * - No match → silent (no stdout) → harness allows the tool call normally.
 * - Malformed stdin → silent (fail-open) → never hard-block the team on a buggy hook.
 *
 * Why Node (not jq + bash):
 * - Every Claude Code installation already has Node available.
 * - Many DMIS dev machines (especially Windows git-bash) do not have `jq` installed.
 * - Keeps the hook portable across macOS, Linux, and Windows.
 */

const GATED_PATHS = [
  {
    label: 'frontend/src/lib/prompts/generation.ts',
    pattern: /(^|\/)frontend\/src\/lib\/prompts\/generation\.ts$/,
    reason:
      'frontend/src/lib/prompts/generation.ts is the canonical DMIS component-generation ' +
      'prompt (see frontend/AGENTS.md:61 and .agents/skills/system-architecture-review/SKILL.md). ' +
      'Direct edits drift the whole component library — run through the architecture-review ' +
      'workflow first. Confirm to proceed if this is intentional.',
  },
  {
    label: 'docs/adr/system_application_architecture.md',
    pattern: /(^|\/)docs\/adr\/system_application_architecture\.md$/,
    reason:
      'docs/adr/system_application_architecture.md is the canonical DMIS architecture ' +
      'baseline (CLAUDE.md primary source-of-truth #1). Architecturally significant ' +
      'decisions need an ADR (new or update) before this file changes — see ' +
      '.agents/skills/system-architecture-review/SKILL.md "ADR discipline". Confirm to ' +
      'proceed if this is intentional.',
  },
  {
    label: 'docs/security/**',
    pattern: /(^|\/)docs\/security\/.+/,
    reason:
      'docs/security/** contains the canonical DMIS security architecture, threat model, ' +
      'and controls matrix (CLAUDE.md primary source-of-truth #2–4). Changes here must run ' +
      'through the security-review workflow and update the relevant ASVS / NIST / OWASP ' +
      'controls. Confirm to proceed if this is intentional.',
  },
];

let data = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
  data += chunk;
});
process.stdin.on('end', () => {
  try {
    const input = JSON.parse(data);
    const fp = (input && input.tool_input && input.tool_input.file_path) || '';
    const norm = String(fp).replace(/\\/g, '/');

    for (const gate of GATED_PATHS) {
      if (gate.pattern.test(norm)) {
        process.stdout.write(JSON.stringify({
          hookSpecificOutput: {
            hookEventName: 'PreToolUse',
            permissionDecision: 'ask',
            permissionDecisionReason: gate.reason,
          },
        }));
        return;
      }
    }
    // Non-matching paths: silent (no stdout) — harness allows the tool call normally.
  } catch (_err) {
    // Malformed stdin: do NOT block. Stay silent so the harness allows the call.
    // A broken hook should never become a hard gate on the team.
  }
});
