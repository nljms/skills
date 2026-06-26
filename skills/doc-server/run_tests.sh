#!/usr/bin/env bash
# Run all doc-server tests (tests/ has no __init__, so run each file).
cd "$(dirname "$0")"
fail=0
for f in tests/test_*.py; do
  out=$(python3 "$f" 2>&1)
  res=$(echo "$out" | tail -1)
  if [ "$res" != "OK" ]; then
    echo "FAIL: $f"; echo "$out" | tail -20; fail=1
  else
    echo "ok:   $f"
  fi
done
exit $fail
