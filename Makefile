.PHONY: test install uninstall

test:
	@command -v bats >/dev/null || { echo "bats is required: https://bats-core.readthedocs.io/"; exit 1; }
	bats tests

install:
	install -Dm755 bin/copiclaude "$(HOME)/.local/bin/copiclaude"

uninstall:
	rm -f "$(HOME)/.local/bin/copiclaude"
