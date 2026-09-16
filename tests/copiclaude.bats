#!/usr/bin/env bats

setup() {
  export TEST_HOME="$BATS_TEST_TMPDIR/home"
  export HOME="$TEST_HOME"
  export XDG_CONFIG_HOME="$TEST_HOME/config"
  mkdir -p "$HOME" "$XDG_CONFIG_HOME"
  export PATH="$BATS_TEST_TMPDIR/bin:$PATH"
  mkdir -p "$BATS_TEST_TMPDIR/bin"
  printf '#!/usr/bin/env bash\nprintf "fake %s\\n" "$0"\n' > "$BATS_TEST_TMPDIR/bin/claude"
  printf '#!/usr/bin/env bash\nprintf "fake %s\\n" "$0"\n' > "$BATS_TEST_TMPDIR/bin/copilot"
  chmod +x "$BATS_TEST_TMPDIR/bin/claude" "$BATS_TEST_TMPDIR/bin/copilot"
}

@test "creates a copilot default configuration" {
  run "$BATS_TEST_DIRNAME/../bin/copiclaude" config
  [ "$status" -eq 0 ]
  [ "$output" = "$XDG_CONFIG_HOME/copiclaude/config" ]
  [ "$(cat "$output")" = "assistant=copilot" ]
}

@test "changes the default assistant" {
  run "$BATS_TEST_DIRNAME/../bin/copiclaude" use claude
  [ "$status" -eq 0 ]
  run "$BATS_TEST_DIRNAME/../bin/copiclaude" status
  [[ "$output" == *"Selected assistant: claude"* ]]
}

@test "launches the selected assistant" {
  "$BATS_TEST_DIRNAME/../bin/copiclaude" use claude >/dev/null
  run "$BATS_TEST_DIRNAME/../bin/copiclaude"
  [ "$status" -eq 0 ]
  [[ "$output" == *"fake "* ]]
}

@test "rejects an invalid assistant" {
  run "$BATS_TEST_DIRNAME/../bin/copiclaude" use invalid
  [ "$status" -ne 0 ]
  [[ "$output" == *"assistant must be claude or copilot"* ]]
}
