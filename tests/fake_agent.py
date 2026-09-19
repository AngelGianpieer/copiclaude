"""A stand-in for `claude` / `copilot` used by the tests.

Usage: fake_agent.py <name> [flags...]   (flags are whatever copiclaude passes)
Type a line and press Enter:
  exit    -> exit with code 7
  limit   -> print a usage-limit message, then stay quiet
  talk    -> print a sentence that merely *mentions* a usage limit, then stay quiet
  modes   -> switch on mouse tracking, bracketed paste and the alternate screen (never undone)
  other   -> echoed
Environment: FAKE_FAIL_ON=<flag> makes it exit(1) immediately if that flag was passed.
"""
import os
import sys
import time

name = sys.argv[1]
print("FAKE-%s READY args=%s" % (name, " ".join(sys.argv[2:])), flush=True)
if os.environ.get("FAKE_FAIL_ON") and os.environ["FAKE_FAIL_ON"] in sys.argv[2:]:
    print("error: refusing %s" % os.environ["FAKE_FAIL_ON"], flush=True)
    sys.exit(1)
while True:
    line = sys.stdin.readline()
    if not line:
        break
    word = line.strip()
    if word == "exit":
        print("bye", flush=True)
        sys.exit(7)
    elif word == "limit":
        print("You've hit your limit - resets 3pm", flush=True)
    elif word == "modes":
        sys.stdout.write("\x1b[?1000h\x1b[?2004h\x1b[?1049h")
        print("modes on", flush=True)
    elif word == "talk":
        print("Here is how to handle a usage limit reached error in your code.", flush=True)
    else:
        print("echo:%s" % word, flush=True)
    time.sleep(0.01)
