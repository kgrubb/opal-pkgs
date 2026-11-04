#!/usr/bin/env python3
"""Bump ./versions to the newest upstream release of each package and print what changed."""
import hashlib
import re
import urllib.request
from pathlib import Path

VERSIONS = Path(__file__).parent / "versions"
# Page listing upstream releases, and a pattern capturing each version on it.
# Zig and musl are pinned on purpose and are not listed.
LATEST = {
    "dropbear": ("https://matt.ucc.asn.au/dropbear/releases/", r"dropbear-(\d+\.\d+)\.tar\.bz2"),
    "ethtool": ("https://www.kernel.org/pub/software/network/ethtool/", r"ethtool-([\d.]+)\.tar\.xz"),
    "i2c-tools": ("https://www.kernel.org/pub/software/utils/i2c-tools/", r"i2c-tools-([\d.]+)\.tar\.xz"),
    "sudo": ("https://www.sudo.ws/dist/", r"sudo-(\d+\.\d+\.\d+(?:p\d+)?)\.tar\.gz"),
    "dnscrypt-proxy": ("https://github.com/DNSCrypt/dnscrypt-proxy/releases/latest", r"/releases/tag/(\d+\.\d+\.\d+)\b"),
    "cacert": ("https://curl.se/docs/caextract.html", r"cacert-(\d{4}-\d{2}-\d{2})\.pem"),
}


def get(url):
    if not url.startswith("https://"):
        raise SystemExit(f"refusing non-HTTPS URL: {url}")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "opal-pkgs"}), timeout=120) as r:
        return r.read()


def key(v):
    return tuple(int(n) for n in re.findall(r"\d+", v))


lines = VERSIONS.read_text().splitlines()
for i, line in enumerate(lines):
    name, current, _, _, url = line.split("\t") if not line.startswith("#") else [""] * 5
    if name not in LATEST:
        continue
    page, pattern = LATEST[name]
    found = re.findall(pattern, get(page).decode())
    if not found:
        raise SystemExit(f"{name}: no versions matched on {page}")
    latest = max(found, key=key)
    if key(latest) > key(current):
        sha = hashlib.sha256(get(url.replace("{v}", latest))).hexdigest()
        lines[i] = "\t".join([name, latest, "1", sha, url])
        print(f"- {name} {current} -> {latest}")
VERSIONS.write_text("\n".join(lines) + "\n")
