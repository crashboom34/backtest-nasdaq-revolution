# Agent skills — usage patterns

Shared reference for **Claude Code** and **Codex** in this repo. Referenced from `AGENTS.md`
(Codex) and `CLAUDE.md` (Claude Code) so the workflow chains only live in one place.

## Where the skills live

The ten [Matt Pocock engineering skills](https://github.com/mattpocock/skills) installed for
this repo are stored as full skill folders (each with `SKILL.md` plus any companion files —
templates, `agents/openai.yaml`, etc.), copied verbatim from `mattpocock/skills` — not just the
`SKILL.md` file:

- `.claude/skills/<skill-name>/` — Claude Code's project-level skill directory.
- `.agents/skills/<skill-name>/` — Codex's project-level skill directory (same convention used
  by `mattpocock/skills` itself for non-Claude-Code agents).

The two folders currently hold byte-identical content (verified with `diff -rq .claude/skills
.agents/skills`). If you hand-edit a skill, apply the same edit to both copies, or re-sync with
`npx skills@latest update` — see `docs/adr/0001-shared-skills-for-claude-code-and-codex.md` for
why two copies exist instead of one shared/symlinked location.

The ten installed skills: `setup-matt-pocock-skills`, `grill-with-docs`, `domain-modeling`,
`codebase-design`, `improve-codebase-architecture`, `to-spec`, `to-tickets`, `implement`,
`tdd`, `code-review`.

## How each agent should invoke them

- **Claude Code**: use the slash command when one is available for the skill (e.g.
  `/grill-with-docs`, `/to-spec`, `/implement`). Claude Code auto-detects skills under
  `.claude/skills/`.
- **Codex**: no slash-command layer — **name the skill explicitly** in the instruction (e.g.
  "use the `to-tickets` skill to break this spec into tickets"). Codex should look for skills
  under `.agents/skills/`.
- `tdd`, `domain-modeling`, `codebase-design`, and `code-review` may be invoked automatically
  by either agent when the task clearly calls for them, without the user having to name them.
- The other, more user-facing skills (`setup-matt-pocock-skills`, `grill-with-docs`, `to-spec`,
  `to-tickets`, `implement`, `improve-codebase-architecture`) should be invoked explicitly by
  name (or slash command on Claude Code) rather than silently auto-triggered.
- **If a skill isn't detected** (folder missing, harness didn't pick it up, etc.), don't block
  the task — continue without it, but say plainly that the skill wasn't available so the user
  can fix the install if they care.

## Workflow chains

**Nouvelle fonctionnalité importante (new significant feature):**

```
grill-with-docs → domain-modeling → codebase-design → to-spec → to-tickets → implement → tdd → code-review
```

**Amélioration d'architecture (architecture improvement):**

```
improve-codebase-architecture → codebase-design → to-spec → to-tickets → implement → code-review
```

**Correctif complexe (complex bugfix):**

```
domain-modeling (si nécessaire) → tdd → implement → code-review
```

## Related docs

- `CONTEXT.md` (repo root) — the domain glossary / ubiquitous language. See `docs/agents/domain.md`
  for how to read and update it.
- `docs/adr/` — architecture decision records. Template at `docs/adr/TEMPLATE.md`.
- `docs/agents/issue-tracker.md` — GitHub Issues conventions for specs/tickets produced by these skills.
- `docs/agents/domain.md` — how to read/update `CONTEXT.md` and `docs/adr/`.
