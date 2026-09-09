# Security policy

## Reporting a vulnerability

Please **do not** open a public issue for vulnerabilities.

Use one of the private channels below:

1. **GitHub private vulnerability reporting** (preferred, and the only private channel configured today): [open a draft advisory](../../security/advisories/new).

> **Maintainer note:** an email fallback was deliberately left unset rather than
> publishing a personal address in a public repo. Add one here if you want a
> second channel.

Include in the report:

- A summary of the issue.
- Steps to reproduce.
- The version / commit SHA you tested against.
- Your assessment of impact (data exposure, account takeover, denial of service, etc.).
- Optional: a proposed fix.

You can expect:

- An acknowledgement within **3 business days**.
- A triage decision (accepted / needs more info / not a vulnerability) within **10 business days**.
- A coordinated disclosure window once a fix is identified — typically 30–90 days, longer for complex issues.

## Supported versions

| Version | Supported |
| --- | --- |
| Latest `main` | ✅ |
| Latest tagged release | ✅ |
| Older tagged releases | ⚠️ Best-effort backports only |
| Forks | ❌ Out of scope |

## Out of scope

- Vulnerabilities in third-party dependencies that have not yet been patched upstream — please report those to the upstream project first. Once an upstream fix exists, a report here is welcome to track our adoption.
- Social engineering, phishing, or physical attacks against contributors.
- Issues that require an attacker to already control the user's device or network at a level that bypasses normal browser/OS sandboxing.

## What padmap's threat model actually is

padmap synthesises keyboard and mouse input on the machine it runs on. It has no
network code, no server, no telemetry, and handles no credentials — there is
nothing for it to leak. The security-relevant surface is narrower and more
specific:

- **Profiles are executable intent, not data.** A profile can bind a key combo
  or type a literal string. Running a profile you did not write is equivalent to
  letting its author type on your keyboard. Read a profile before you run it —
  they are small, plain JSON, and `padmap validate <file>` prints every binding
  in full precisely so you can.
- **Stuck input is a security bug, not just a papercut.** A modifier left held
  down (`ctrl`, `cmd`, `alt`) changes how every subsequent keystroke is
  interpreted. Any path that can leave a key down is treated as a real
  vulnerability here, not a papercut — report it.
- **padmap does not evade anti-cheat**, and reports asking for that are out of
  scope, not vulnerabilities.

See [`CLAUDE.md`](../CLAUDE.md) for the full security model.
