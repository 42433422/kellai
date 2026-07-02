function FindProxyForURL(url, host) {
  host = host.toLowerCase();

  if (
    host == "claude.ai" ||
    dnsDomainIs(host, ".claude.ai") ||
    host == "anthropic.com" ||
    dnsDomainIs(host, ".anthropic.com") ||
    host == "accounts.google.com" ||
    host == "google.com" ||
    dnsDomainIs(host, ".google.com") ||
    host == "gstatic.com" ||
    dnsDomainIs(host, ".gstatic.com") ||
    host == "googleusercontent.com" ||
    dnsDomainIs(host, ".googleusercontent.com") ||
    host == "googleapis.com" ||
    dnsDomainIs(host, ".googleapis.com") ||
    host == "challenges.cloudflare.com"
  ) {
    return "PROXY 100.79.230.2:18080";
  }

  return "DIRECT";
}
