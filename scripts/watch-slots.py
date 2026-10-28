"""Poll llama-server /slots and log generation progress.

Progress.log only moves when a crew task finishes, so a long task
looks identical to a dead run. This watchdog makes the difference
visible: every interval it records each slot's processing state and
decoded token count, so a rising n_decoded means generating and a
flat n_decoded means stalled.

Run in a second terminal while the crew runs:
    python scripts/watch-slots.py --log outputs/slots-watch.log
Stop with Ctrl-C. Stdlib only; the server URL and interval are
overridable with --url and --interval.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime


def fetch_slots(url):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.load(resp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080/slots")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--log", default="outputs/slots-watch.log")
    args = parser.parse_args()

    failures = 0
    with open(args.log, "a", encoding="utf-8") as log:
        while True:
            stamp = datetime.now().isoformat(timespec="seconds")
            try:
                slots = fetch_slots(args.url)
                failures = 0
            except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
                failures += 1
                line = f"{stamp} slots fetch failed ({failures}): {exc}"
                print(line, flush=True)
                print(line, file=log, flush=True)
                if failures >= 3:
                    print("server unreachable 3 times in a row, stopping watchdog", flush=True)
                    return 1
                time.sleep(args.interval)
                continue
            parts = []
            for slot in slots:
                nxt = slot.get("next_token", [{}])[0]
                parts.append(
                    f"slot{slot.get('id')} processing={slot.get('is_processing')} "
                    f"prompt={slot.get('n_prompt_tokens')} decoded={nxt.get('n_decoded')} "
                    f"has_next={nxt.get('has_next_token')}"
                )
            line = f"{stamp} " + " | ".join(parts)
            print(line, flush=True)
            print(line, file=log, flush=True)
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
