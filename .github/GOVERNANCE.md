# Governance

How **padmap** is run. Short on purpose — anything not covered here lives in [`CONTRIBUTING.md`](./CONTRIBUTING.md), [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md), or [`SECURITY.md`](./SECURITY.md).

This document follows the [`repo-standards`](https://github.com/Ranzlappen/repo-standards) v2.1 governance template. The default is "lazy consensus, transparent decisions, branch protection backs the rules so the rules aren't the only line of defence".

## Roles

The repo recognises three roles:

- **Maintainers** — listed in [`CODEOWNERS`](./CODEOWNERS). Can merge PRs, cut releases, edit branch protection. Default: the repo owner. Add maintainers by PR (one PR per addition, requires approval from an existing maintainer).
- **Contributors** — anyone who has ever opened a PR or issue. No special permissions; reviews are welcome and weighed but non-binding.
- **Users** — everyone else. Bug reports and feature requests via [issue templates](./ISSUE_TEMPLATE/).

Roles are descriptive, not hierarchical. A contributor with sustained, quality contributions becomes a maintainer; a maintainer who steps away does so by PR (remove themselves from CODEOWNERS), no ceremony.

## Decision-making

**Lazy consensus.** Most decisions are made in PR review. If a maintainer opens a PR and no other maintainer objects within a reasonable window (default: 72 hours for non-urgent changes, immediate for security fixes), the change ships.

**Disagreement.** If two maintainers disagree on a substantive change:

1. The PR author drafts the change with the rationale in the PR description.
2. Other maintainers comment with concrete blocking concerns (not "I don't like it" — name what specifically would break or regress).
3. If consensus isn't reached in 7 days, the repo owner has the tiebreaker. Document the tiebreak in the PR thread so future contributors see the reasoning.

**No bikeshedding budget.** Trivial style preferences (where a comment goes, naming taste) are deferred to the existing linters and the existing patterns. If the linter doesn't catch it and there's no existing pattern, the PR author's choice stands.

## Contribution lifecycle

1. **Issue first** for non-trivial changes — see [`CONTRIBUTING.md`](./CONTRIBUTING.md). Avoids wasted work.
2. **Branch from `main`** with a Conventional Commits–friendly name (`feat/csv-export`, `fix/swipe-flicker`, `docs/clarify-storage-keys`).
3. **PR is the conversation.** Use the [PR template](./PULL_REQUEST_TEMPLATE.md). Keep the PR small and reviewable in one sitting.
4. **CI must be green** before review. Maintainers don't review red CI; they ask the author to fix it first.
5. **Squash-merge** is the default. The PR title becomes the merge commit subject (so it must conform to Conventional Commits).
6. **The author closes the loop** — replies to review comments, links to the merged PR from the originating issue, and ticks the issue closed if the PR resolves it.

## Recommended branch-protection rules (`main`)

Configure under **Settings → Branches → Branch protection rules → Add rule** with pattern `main`. The repo's `self-validate.yml` and `security-scan.yml` workflows assume these rules are in place; without them the gates are advisory only.

- ✅ **Require a pull request before merging.**
  - ✅ Require approvals: **1** (more for multi-maintainer repos).
  - ✅ Dismiss stale pull request approvals when new commits are pushed.
  - ✅ Require review from Code Owners (uses [`CODEOWNERS`](./CODEOWNERS)).
- ✅ **Require status checks to pass before merging.**
  - ✅ Require branches to be up to date before merging.
  - Required checks (mark each as required after its first successful run):
    - `actionlint (workflows)`
    - `lychee (offline link check)`
    - `VERSION is semver` (if the repo ships a `VERSION` file)
    - `uses-line SHA-pinning lint`
    - Project-specific lint / test jobs (e.g. `ci / lint`, `ci / test`)
    - `CodeQL` (per language matrix in `security-scan.yml`)
    - `Gitleaks secret scan`
- ✅ **Require conversation resolution before merging.**
- ✅ **Require signed commits.** Recommended; flip on once all maintainers have a signing key configured.
- ✅ **Require linear history.** Enforces squash- or rebase-merge; matches the lifecycle rule above.
- ✅ **Do not allow bypassing the above settings.** Including for administrators — the rules exist precisely so the rare slip doesn't ship.
- ✅ **Restrict who can push to matching branches.** Maintainers only.
- ✅ **Allow force pushes**: ❌ disabled. **Allow deletions**: ❌ disabled.

For tag patterns (`v*`), add a second rule that mirrors the above plus restricts who can push tags. `auto-tag.yml` and `tag-release.yml` only run from `main`, so tag pushes are still gated.

## Supply-chain governance

The repo's supply-chain primitives — SHA-pinning, Scorecard, dependency review, signed releases — are policy-bound, not best-effort. The matrix in [`SECURITY.md`](./SECURITY.md) "Supply-chain commitments" is the source of truth; this section is the maintainer-facing policy that pins the floor.

- **OpenSSF Scorecard floor: 7.0.** A score below 7.0 (read from [securityscorecards.dev](https://securityscorecards.dev/) or the SARIF in the Security tab) is treated as a regression. Open a `security` PR to remediate within 30 days. If 30 days pass without a fix, record an explicit waiver in [`SECURITY.md`](./SECURITY.md) under the relevant primitive's row, with the reason and the next review date — never silently fall under floor.
- **`dependency-review.yml` is required on every PR to `main`.** Branch protection's required-status-checks list includes the dependency-review job. A PR that introduces a `high`-or-above CVE blocks merge until the CVE is resolved upstream (preferred), pinned to a patched range (acceptable), or explicitly waived in the PR description with a CVE-ID and a justification (last resort).
- **CodeQL is required on every language present in the repo.** Matrix in `templates/.github/workflows/security-scan.yml` matches the languages actually checked in. Adding a new language is a `security` PR that updates the matrix in the same commit as the first source file.
- **Signed releases via sigstore / cosign.** Once the publishing OIDC trust is configured (npm package settings, PyPI publishing account, or GHCR token scope per `release-please.yml` header), every tagged release artifact carries a `.sig`. Releases without a signature are flagged on the release page and should be re-cut after the signing step lands.
- **Dependabot's role.** Dependabot opens the PRs; `dependency-review.yml` gates them; a maintainer reviews and merges. Dependabot **does not** auto-merge in this repo (or in downstream repos using these templates by default) — auto-merge bypasses the human "is this minor pin actually safe" check.
- **Waivers are public.** Any time a primitive is bypassed, the bypass lives in `SECURITY.md` with the reason and the review date. Private waivers create surprises; public waivers create accountability.

A regression on any of the **live** primitives above is a security finding; route it through [`SECURITY.md`](./SECURITY.md)'s private-reporting channel rather than opening a public issue.

## Triage and release rhythm

- **Triage cadence**: Maintainers aim to acknowledge new issues within 7 days. "Acknowledge" means triage label + a one-line response, not a fix.
- **Release cadence**: Driven by Conventional Commits via `release-please.yml` if enabled (see the workflow's header comment). For repos without release-please, releases are cut manually via `tag-release.yml` when a maintainer judges enough has accumulated.
- **Security fixes** ship out-of-band on their own PR, fast-tracked through review. See [`SECURITY.md`](./SECURITY.md) for private disclosure.

## Automated triage

Triage scales with labels. The recommended baseline below is small on purpose — every label has to be applied by a human or a bot at some point, so 30 labels nobody applies are worse than 8 labels everyone does.

**Recommended default labels** (adopt as-is unless a project has a strong reason to diverge):

| Label | Meaning | Applied by |
| --- | --- | --- |
| `bug` | Something broken in shipped behavior. | Triager / template |
| `feature` | New behavior request. | Triager / template |
| `question` | Use Discussions instead — close + redirect. | Triager / template |
| `dependencies` | Dependabot / dependency-review-related. | Dependabot, `dependency-review.yml` |
| `security` | Routes through `SECURITY.md` private channel; never opens publicly. | Maintainer |
| `triage` | New issue, not yet reviewed. | Default on new issues |
| `from-claude` | Filed by Claude Code (rule 13). | `gh issue create --label` |
| `out-of-scope` | Surfaced by an upgrade pass but unrelated; opt-out via `DISABLE_OUT_OF_SCOPE_ISSUES=true`. | `gh issue create --label` (rule 13) |
| `good-first-issue` | Curated low-friction starter issue. | Maintainer |

**Triage rhythm.**

- **New issues land with `triage`.** Maintainers acknowledge within **7 days** — "acknowledge" means triage label removed, replaced by one of `bug` / `feature` / `question`, plus a one-line response explaining the call. Acknowledgement is not a promise to fix.
- **`question` issues are redirected to Discussions** (when Discussions is enabled — see [`README.md`](../README.md) "GitHub Discussions"). Close the issue with a one-line link rather than answering inline; that keeps the issue tracker for tracked work.
- **`from-claude` and `out-of-scope` issues are first-class.** They land via `gh issue create` from inside an upgrade pass per `PROMPT.md` rule 13. Treat them like any other triage queue item — they're already structured (title, body, label) so the human cost is minutes per issue.
- **`security` issues never open publicly.** If one slips in, close immediately, redirect the reporter to the private channels in [`SECURITY.md`](./SECURITY.md), and treat the disclosure as the live one.
- **Stale handling is opt-in.** `templates/.github/workflows/stale.yml` ships gated on `STALE_ENABLED=true`; defaults are issues 60d → 7d, PRs 90d → 14d. Exempt labels include `pinned`, `security`, `keep-open`, `dependencies` (PRs only), milestoned, and assigned.

**Workflow-summary integration (added in v3).** When `templates/.github/workflows/workflow-summary.yml` is wired into the per-repo CI workflow, its sticky PR comment surfaces lint/test annotations alongside the diff — the comment is the **single source of CI truth** for a PR. Triagers can read the sticky comment instead of clicking through to the workflow run; AI agents can parse the comment's committed-shape Markdown without ad-hoc heuristics.

## Conflict resolution

Code-of-conduct concerns route to the contact in [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md). Repo-process concerns (this document, branch protection, lifecycle) route to the maintainer list in [`CODEOWNERS`](./CODEOWNERS) via a private email or issue tagged `governance`.

If something here is broken or missing, open a PR against this file — governance changes follow the same lifecycle as code changes.
