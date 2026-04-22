`CLAUDE.md` written to `/Users/dock108/git/sports/sda/CLAUDE.md`. It covers:

- **Project identity** — monorepo layout with all four packages and their roles
- **Dev setup** — virtualenv, pnpm, migrations, local auth bypass
- **Testing** — how to run the full suite, each package individually, coverage minimum (90%), and the guardrails sync pre-check
- **Style** — Ruff config for Python (100-char lines, rule set), ESLint/strict TS for the web
- **Naming** — tables for Python and TypeScript conventions including Alembic migration naming
- **Git** — Conventional Commits format, branch naming, PR conventions
- **Dependencies** — how to add/pin for both ecosystems, what's banned
- **Important rules** — the five design principles from `DESIGN.md` (three-layer idempotency, club-scoped tenancy, entitlement service, explicit state machines, server-side payment truth) plus the guardrails sync requirement and PYTHONPATH model sharing constraint