# Security Policy

## Supported Versions

Security fixes are provided for the latest released version of `plex-tui`.
Install the newest GitHub Release, PyPI package, Homebrew formula, or AUR
package before reporting an issue against an older version.

## Reporting a Vulnerability

Please do not open a public issue with vulnerability details.

Use GitHub's private vulnerability reporting for this repository when it is
available:

https://github.com/so1omon563/plex-tui/security/advisories/new

If GitHub does not offer a private report button, open a public issue asking for
a private maintainer contact path, but do not include exploit details, Plex
tokens, account tokens, debug logs, or local config files.

Useful reports include:

- The affected `plex-tui` version and install method.
- The operating system, Python version, terminal, and `mpv` version when
  relevant.
- A minimal reproduction or clear description of the vulnerable behavior.
- The expected impact, such as token exposure, unsafe command execution, or
  package/release integrity risk.

## Scope

Security-sensitive areas include Plex token handling, config and debug-log
redaction, playback command construction, dependency and packaging updates, and
release publishing automation.

Issues in Plex Media Server, Plex-hosted services, `mpv`, package managers, or
the user's local operating system should be reported to those projects unless
`plex-tui` is directly contributing to the vulnerability.

## Response

Maintainers will triage credible reports privately, prepare a fix, and publish
a release or advisory when appropriate. Public disclosure should wait until a
fix or mitigation is available.
