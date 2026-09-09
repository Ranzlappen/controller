# Contributing to padmap

Thanks for considering a contribution. This document is short on purpose — anything not covered here lives in [`CLAUDE.md`](../CLAUDE.md) (architecture, build commands, conventions) or in the [`README.md`](../README.md) (user-facing docs).

## Quick links

- [Open issues](../../issues) — bug reports and feature ideas.
- [Pull requests](../../pulls) — submit changes for review.
- [Code of Conduct](./CODE_OF_CONDUCT.md) — how we treat each other.
- [Governance](./GOVERNANCE.md) — roles, decision-making, branch-protection rules.
- [Security policy](./SECURITY.md) — how to report vulnerabilities privately.

## How to propose a change

1. **Open an issue first** for anything beyond a typo fix. Aligning on the *what* before you write the *how* avoids wasted work.
2. **Branch from `main`** with a short, descriptive name: `fix/trigger-deadzone`, `feat/scroll-acceleration`, `docs/clarify-wayland`.
3. **Keep PRs small.** One focused change per PR. If your PR description has more than one "and", consider splitting.
4. **Match the existing style.** Linting and formatting are run in CI; running them locally first saves a round trip.
5. **Update docs in the same PR** — README, CLAUDE.md, or inline comments — when behavior or commands change.

## Conventional commits

This project uses [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). Short summary:

- `feat: …` — a new user-visible capability.
- `fix: …` — a bug fix.
- `docs: …` — documentation only.
- `refactor: …` — code change that doesn't add features or fix bugs.
- `test: …` — adding or fixing tests.
- `chore: …` — build, deps, tooling, anything not user-visible.
- `ci: …` — changes to CI configuration.
- `perf: …` — performance improvement.
- `style: …` — formatting only, no behavior change.
- `revert: …` — reverts a previous commit.

Optional scope in parentheses (`feat(timer): …`). Breaking changes get a `!` (e.g. `feat!: …`) and a `BREAKING CHANGE:` footer in the commit body.

## Pull request checklist

The PR template surfaces these automatically. Repeated here for reference:

- [ ] No behavior change unless the PR explicitly says otherwise.
- [ ] Docs updated where relevant.
- [ ] CI green.
- [ ] No secrets, credentials, or unredacted personal data committed.
- [ ] Conventional commit message on the merge commit (or rebase the branch first).

## Reviewing

Maintainers aim to triage within a week. If a PR sits longer than that without a response, ping the issue or the PR — you're not being ignored, just lost in noise.

## Community standards

Because this project is hosted on GitHub, contributions are governed by **three** community standards in addition to this repo's own [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md):

1. The [GitHub Community Guidelines](https://docs.github.com/en/site-policy/github-terms/github-community-guidelines) — what's expected of all GitHub users.
2. The [GitHub Acceptable Use Policies](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies) — what GitHub disallows on its platform (spam, harassment, illegal content, malware, doxxing, etc.).
3. This repo's [Code of Conduct](./CODE_OF_CONDUCT.md) and (if applicable) [Governance](./GOVERNANCE.md).

Maintainers will close, hide, or report contributions that violate any of the three. Reporting routes: CoC concerns to the contact in `CODE_OF_CONDUCT.md`; platform-policy concerns to GitHub Trust & Safety via [github.com/contact/report-content](https://github.com/contact/report-content).

## License

By contributing, you agree that your contributions will be licensed under this repository's [LICENSE](../LICENSE).
