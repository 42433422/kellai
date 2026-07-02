#!/bin/zsh
set -euo pipefail

networksetup -listallnetworkservices | sed '1d' | while IFS= read -r service; do
  [[ -z "$service" ]] && continue
  service="${service#*}"
  networksetup -setautoproxystate "$service" off >/dev/null 2>&1 || true
  networksetup -setwebproxystate "$service" off >/dev/null 2>&1 || true
  networksetup -setsecurewebproxystate "$service" off >/dev/null 2>&1 || true
  networksetup -setsocksfirewallproxystate "$service" off >/dev/null 2>&1 || true
done

echo "Claude PAC rules disabled."
