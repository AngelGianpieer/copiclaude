# Architecture

CopiClaude is intentionally a thin launcher:

1. `bin/copiclaude` resolves the configuration directory.
2. It reads `assistant=claude` or `assistant=copilot`.
3. It verifies the matching executable exists in `PATH`.
4. It replaces itself with that executable using `exec`.

There is no daemon, network service, telemetry, credential storage, or
conversation proxy. This keeps the tool auditable and makes failures visible in
the terminal.
