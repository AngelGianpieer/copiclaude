# CopiClaude

CopiClaude is a small, dependency-free terminal launcher for switching between
[Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) and
[GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli).
It keeps the selected assistant in a user configuration file and gives both
tools a predictable command.

## Features

- POSIX-friendly Bash launcher with no runtime dependencies.
- One command to choose the default assistant.
- Direct launch commands for either assistant.
- Status reporting that detects installed commands.
- Configuration isolated under `${XDG_CONFIG_HOME:-~/.config}/copiclaude`.

## Requirements

- Bash 4+.
- Claude Code and/or GitHub Copilot CLI installed and authenticated if you
  intend to use them.
- `bats` is optional and only needed to run the test suite.

## Installation

### User-local installation

```bash
git clone https://github.com/AngelGianpieer/copiclaude.git
cd copiclaude
make install
export PATH="$HOME/.local/bin:$PATH"
```

### Without cloning

```bash
mkdir -p "$HOME/.local/bin"
curl -fsSL https://raw.githubusercontent.com/AngelGianpieer/copiclaude/main/bin/copiclaude \
  -o "$HOME/.local/bin/copiclaude"
chmod +x "$HOME/.local/bin/copiclaude"
```

## Usage

```bash
copiclaude status
copiclaude use copilot
copiclaude              # launches the selected assistant
copiclaude claude       # launches Claude Code directly
copiclaude copilot      # launches GitHub Copilot CLI directly
copiclaude config
```

CopiClaude does not proxy, modify, or store conversations. It only selects and
executes the installed command. Arguments are intentionally not forwarded by
the first version; invoke the underlying assistant directly when you need
special command-line options.

## Configuration

The configuration file is created on first use:

```text
~/.config/copiclaude/config
```

Set `XDG_CONFIG_HOME` to relocate it. The file contains one supported setting:

```text
assistant=copilot
```

Supported values are `claude` and `copilot`.

## Installing the assistants

Install and authenticate the assistants using their official documentation:

- [Claude Code installation](https://docs.anthropic.com/en/docs/claude-code/overview)
- [GitHub Copilot CLI installation](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli)

Then verify availability with:

```bash
copiclaude status
```

## Development

```bash
git clone https://github.com/AngelGianpieer/copiclaude.git
cd copiclaude
make test
```

Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

Released under the MIT License. See [LICENSE](LICENSE).
