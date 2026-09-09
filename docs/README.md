# `docs/`

Longer-form documentation for **padmap**. The root [`README.md`](../README.md) covers what padmap is, how to install it, and the profile reference you need day to day. This folder is for the things that would bloat it.

| Document | What's in it |
| --- | --- |
| [`troubleshooting.md`](./troubleshooting.md) | "It doesn't work" — no controller found, no input reaching apps, wrong buttons, drifting sticks, stuck keys. |

For architecture, conventions and CI, see [`CLAUDE.md`](../CLAUDE.md) at the repo root — that is the source of truth, and it wins over anything here if the two disagree.

## Publishing

These files render natively on GitHub and that is deliberate: padmap has a handful of documents, no search requirement and no versioned docs. If the folder grows past ~10 files or starts needing search, the next step is GitHub Pages with a Jekyll theme, and only after that a dedicated site (VitePress or MkDocs Material). Don't pre-emptively pick a static-site generator for a project that doesn't have a site's worth of content.
