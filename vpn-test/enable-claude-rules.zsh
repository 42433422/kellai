#!/bin/zsh
set -euo pipefail

PAC_URL="file:///Users/a4243342/Desktop/%E5%AE%A2%E6%9D%A5%E6%9D%A5/vpn-test/claude-residential.pac"

if command -v tailscale >/dev/null 2>&1; then
  tailscale set --exit-node=
fi

networksetup -listallnetworkservices | sed '1d' | while IFS= read -r service; do
  [[ -z "$service" ]] && continue
  service="${service#*}"
  networksetup -setwebproxystate "$service" off >/dev/null 2>&1 || true
  networksetup -setsecurewebproxystate "$service" off >/dev/null 2>&1 || true
  networksetup -setsocksfirewallproxystate "$service" off >/dev/null 2>&1 || true
  networksetup -setautoproxyurl "$service" "$PAC_URL" >/dev/null 2>&1 || true
  networksetup -setautoproxystate "$service" on >/dev/null 2>&1 || true
done

launchctl setenv TZ America/Los_Angeles
echo "Claude rules enabled: Claude/Anthropic/Google auth via 100.79.230.2:18080, others DIRECT."
