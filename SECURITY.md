# Security Policy

## Supported versions

This project is pre-1.0. Only the latest published release receives security fixes.

| Version | Supported |
|---------|-----------|
| `main` (development) | ✅ |
| Latest tagged release | ✅ |
| Older tags | ❌ |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security reports.**

Email `fuzzlightyear@protonmail.com` with:

- A description of the vulnerability and its impact.
- Steps to reproduce — minimal, self-contained, ideally with a Python snippet.
- Affected versions or commits if known.
- Whether a public disclosure timeline has already been arranged elsewhere.

You can expect an acknowledgement within 7 days and a substantive response with a remediation plan within 30 days. Once a fix is available and released, the advisory will be published with credit to the reporter (unless anonymity is requested).

## Scope

This project's threat model centres on the security guarantees the scanner provides — specifically, that recursive enumeration cannot escape the user-supplied root via symbolic links or NTFS directory junctions. Reports relevant to that contract take priority.

Out of scope: vulnerabilities in upstream dependencies (Polars, Rich, Loguru, etc.) — please report those to the respective projects. We will track and uptake fixes as they ship.
