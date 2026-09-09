<!--
Template for pull requests in padmap. Mirrors the structure
PROMPT.md (Step 3) requires for repo-upgrade PRs, so the same
review experience applies to ad-hoc and Claude-driven PRs alike.
-->

## Summary

<!-- One paragraph: what this PR does and why. Keep it tight. -->

## Checklist coverage

<!--
Paste the relevant items from UPGRADE_CHECKLIST.md (or your local
checklist) and mark each:
  ✓ done
  — not applicable (one-line reason)
  ⚠️ deferred (one-line reason)
-->

- [ ] No behavior change unless explicitly noted in the summary above.
- [ ] Docs/README/CLAUDE.md updated where relevant.
- [ ] CI green (or, if CI is not configured for this path, a manual
      verification note appears in **Test plan** below).
- [ ] No secrets, credentials, or unredacted personal data in tracked files.
- [ ] No file added or modified to exceed ~800 lines.

## Refactoring opportunities (not in this PR)

<!--
Bullet list of things noticed but intentionally not done in this PR.
These become future work. Leave the section but write "None" if
there is nothing to flag.
-->

- None

## Test plan

<!--
How to verify this PR doesn't break anything. Examples:
  - "Ran `npm test`; 42/42 passing."
  - "Loaded the deployed preview on iOS Safari and Chrome desktop;
     dark mode toggle still persists across reload."
  - For docs-only PRs: "N/A — documentation only."
  - For CI PRs: "Workflow file is valid YAML; the run on this PR is
     green."
  - For refactoring PRs: full behavior-verification checklist per
     REFACTORING_GUIDE.md.
-->

-

## Behavior-preservation evidence (only if this PR is a refactor)

<!--
Required by PROMPT.md rule 2 for any refactoring PR. Tick each bucket
this refactor touched and state in one line what was verified before/
after. PWA refactors expand Storage and External via the PWA-specific
section below. Delete this section if this PR is not a refactor.
-->

- [ ] **UI** — rendered output, layout, animations, focus order, accessibility tree.
- [ ] **URLs** — deployed domain, route paths, query parameters, deep-link contracts.
- [ ] **Storage** — `localStorage` / `sessionStorage` keys, IndexedDB schema versions, cache names, service-worker registration order.
- [ ] **Deployment shape** — hosting target, asset URLs, build-output paths, redirect rules.
- [ ] **External dependencies** — third-party endpoint shapes, webhook payloads, analytics identifiers, manifest `start_url` / `scope` / `id`, `assetlinks.json` fingerprints.

## PWA-specific verification (only if this repo has a service worker, manifest, or persistent storage)

<!--
Delete this section if not applicable. Otherwise tick each item:
-->

- [ ] Storage keys unchanged (every key from the pre-refactor inventory still exists with the same value).
- [ ] Schema-version constant unchanged; migration code preserved byte-for-byte.
- [ ] Service worker file path unchanged.
- [ ] `CACHE_NAME` bumped if precache list changed.
- [ ] `self.skipWaiting()` and `self.clients.claim()` present.
- [ ] Manifest `start_url`, `scope`, `id` unchanged.
- [ ] `.well-known/assetlinks.json` unchanged (if present).
- [ ] Permission requests still tied to the same user gestures.
