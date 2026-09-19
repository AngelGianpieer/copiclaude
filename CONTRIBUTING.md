# Contributing

Thanks for helping improve CopiClaude.

## Local setup

```bash
git clone https://github.com/AngelGianpieer/copiclaude
cd copiclaude
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[test]"
pytest
```

The suite includes end-to-end tests that run copiclaude in a pseudo-terminal
against stand-in agents (`tests/fake_agent.py`); they take about 20 seconds and
never touch your real Claude or Copilot sessions (tests isolate `HOME`).

## Guidelines

- Keep it dependency-free apart from `pywinpty` on Windows. Support Python 3.9+.
- Anything that reads another tool's files must degrade to "nothing found", never raise.
- Never write into an agent's terminal on the user's behalf.
- Add a test for behaviour changes; update README, CHANGELOG and both READMEs' shared claims.
- Windows behaviour can only be checked in CI or on Windows: say which you did.

## Pull requests

Describe the problem, the solution, and the commands used to test it. Avoid
including credentials, local configuration files, or terminal transcripts that
contain sensitive data.
