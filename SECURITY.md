# Security Policy

## Supported versions

This project is pre-1.0. Only the latest published release receives security fixes.

| Version | Supported |
|---------|-----------|
| `main` (development) | Yes |
| Latest tagged release | Yes |
| Older tags | No |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security reports.**

Submit a private security advisory via the repository's [Security tab](https://github.com/FuzzLightyear/directory-indexing-util/security/advisories/new). Include:

- A description of the vulnerability and its impact.
- Steps to reproduce: minimal, self-contained, ideally with a Python snippet.
- Affected versions or commits if known.
- Whether a public disclosure timeline has already been arranged elsewhere.

You can expect an acknowledgement within 7 days and a substantive response with a remediation plan within 30 days. Once a fix is available and released, the advisory will be published with credit to the reporter (unless anonymity is requested).

## Scope

This project's threat model centres on the security guarantees the scanner provides, specifically that recursive enumeration cannot escape the user-supplied root via symbolic links or NTFS directory junctions. Reports relevant to that contract take priority.

The CLI also reads saved profiles from per-user TOML files. Those files are parsed with the standard library `tomllib` (which executes no code), validated against a closed five-field schema, and bounded in size and count; the profile name is validated before it becomes a filename, and symlinked or non-regular files in the profiles directory are ignored. The trust boundary is the user's own account: this hardening targets corrupt, oversized, symlinked, or hand-edited files and traversal via a profile name, not an attacker who can already write to the user's configuration directory.

Out of scope: vulnerabilities in upstream dependencies (Polars, Rich, Loguru, etc.).  Please report those to the respective projects. We will track and uptake fixes as they ship.
