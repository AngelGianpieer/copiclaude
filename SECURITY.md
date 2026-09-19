# Security Policy

## Supported versions

Only the latest release on the default branch is supported.

## Reporting a vulnerability

Do not open a public issue for a suspected security vulnerability. Use GitHub's
private vulnerability reporting for this repository, or contact the owner
privately through GitHub.

## What CopiClaude touches

CopiClaude makes no network requests and never reads credentials. It launches
`claude` / `copilot` as your user, forwards your keystrokes, and reads those
tools' local session files to build `.copiclaude/HANDOFF.md`, which quotes your
recent prompts. That folder is git-ignored by its own `.gitignore`; treat it as
private. Never include tokens, API keys or private transcripts in a report.
