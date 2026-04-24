# Security Policy

## Supported Versions

Only the latest tagged release is supported, which is generally equivalent to the `main` branch. Older releases do not receive security fixes or backports.

## Reporting a Vulnerability

Please use GitHub's private vulnerability reporting rather than opening a public issue. Navigate to the **Security** tab of this repository and click **Report a vulnerability**. This opens a private security advisory where we can collaborate on the details and coordinate a fix before any public disclosure.

If you are unsure whether something qualifies as a vulnerability, report it privately anyway. We would rather triage a non-issue than have something slip through.

## What to Include

A useful report includes:

- A description of the issue and its potential impact
- Steps to reproduce or a proof of concept
- The version or commit you tested against
- Any relevant environment details

## Response

This is a small open source project maintained by volunteers. We will aim to acknowledge reports within a few days and work with you in good faith toward a resolution. We appreciate your patience.

## Scope

ManaScope is a local CLI tool. It makes outbound HTTP requests to [Scryfall](https://scryfall.com/) and [EDHREC](https://edhrec.com/) and reads files from the local filesystem. Relevant areas include:

- Handling of decklist and collection files
- HTTP request behaviour and response handling
- Local SQLite cache handling

TLS certificate verification relies on the CA bundle provided by `requests` / `certifi` in the active `uv` environment. This is intentional for a local `uv run` CLI; packaging the tool as a frozen binary would require revisiting that choice.

The following are generally out of scope:

- Bugs or vulnerabilities in Scryfall, EDHREC, or other third-party services
- Issues in Python itself or the underlying operating system
- Theoretical attacks with no realistic exploitation path against a local CLI tool
- Dependency vulnerabilities

## Disclosure

Once a fix is in place, we will publish the GitHub security advisory for the record.
