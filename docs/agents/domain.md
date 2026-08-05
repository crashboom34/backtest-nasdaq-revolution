# Domain Docs

How Codex and Claude Code should consume this repo's domain documentation when exploring the codebase. Layout: **single-context** (one `CONTEXT.md` at the repo root — this project is one bounded context, the backtest software).

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — the single source of truth for backtest domain terminology (moteur de backtest, stratégie, données historiques, ordre, exécution, position, drawdown, etc.).
- **`docs/adr/`** — read ADRs that touch the area you're about to work in.

If `CONTEXT.md` or `docs/adr/` are missing or incomplete for a term you need, **proceed without blocking**. Don't refuse to work; note the gap so `/domain-modeling` can fill it later, and mark anything you add or infer as `À confirmer` rather than presenting it as settled.

## File structure

```
/
├── CONTEXT.md          ← single-context glossary, root of the repo
├── docs/
│   ├── adr/             ← architecture decision records
│   │   ├── TEMPLATE.md
│   │   └── 0001-shared-skills-for-claude-code-and-codex.md
│   └── agents/           ← this directory: agent-facing config
│       ├── domain.md          (this file)
│       └── issue-tracker.md
└── ...
```

This repo does not use a `CONTEXT-MAP.md` — there is no multi-context split. If the project later grows a second bounded context, that's an architectural decision: raise it as a proposed ADR rather than assuming it.

## Use the glossary's vocabulary

When your output names a domain concept (issue title, refactor proposal, hypothesis, test name), use the term as defined in `CONTEXT.md` — e.g. say "bougie" (or "candle", whichever `CONTEXT.md` settles on) consistently rather than mixing synonyms. Don't drift to a synonym the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider), or there's a real gap (note it for `/domain-modeling`, and mark the term `À confirmer` until a human confirms it).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0001 (shared skills for Claude Code and Codex) — but worth reopening because…_

## Updating `CONTEXT.md` and `docs/adr/`

- `CONTEXT.md` is updated lazily, as terms actually get resolved in conversation — normally through `/domain-modeling` (itself often reached via `/grill-with-docs` or `/improve-codebase-architecture`).
- New ADRs are added under `docs/adr/`, numbered sequentially (`0002-...`, `0003-...`), using the template in `docs/adr/TEMPLATE.md`. Status starts at `Proposé` (Proposed) for anything that still needs human sign-off.
- Never present a guess as a validated decision. If something is uncertain, write `À confirmer` in `CONTEXT.md` rather than inventing a definition.
