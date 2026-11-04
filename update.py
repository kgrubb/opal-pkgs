#!/usr/bin/env python3
"""Bump ./versions to the newest signed upstream release of each package and print what changed."""
import hashlib
import lzma
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
VERSIONS = ROOT / "versions"
# Page listing upstream releases, a pattern capturing each version on it, and the signature suffix.
# The signer's key is keys/<name>.gpg, or keys/<name>.pub for minisign.
# Zig and musl are pinned on purpose and are not listed.
LATEST = {
    "dropbear": ("https://matt.ucc.asn.au/dropbear/releases/", r"dropbear-(\d+\.\d+)\.tar\.bz2", ".asc"),
    "ethtool": ("https://www.kernel.org/pub/software/network/ethtool/", r"ethtool-([\d.]+)\.tar\.xz", ".sign"),
    "i2c-tools": ("https://www.kernel.org/pub/software/utils/i2c-tools/", r"i2c-tools-([\d.]+)\.tar\.xz", ".sign"),
    "sudo": ("https://www.sudo.ws/dist/", r"sudo-(\d+\.\d+\.\d+(?:p\d+)?)\.tar\.gz", ".sig"),
    "dnscrypt-proxy": ("https://github.com/DNSCrypt/dnscrypt-proxy/releases/latest", r"/releases/tag/(\d+\.\d+\.\d+)\b", ".minisig"),
    # curl.se publishes no signature for cacert.pem, so HTTPS is the only check.
    "cacert": ("https://curl.se/docs/caextract.html", r"cacert-(\d{4}-\d{2}-\d{2})\.pem", None),
}


def get(url):
    if not url.startswith("https://"):
        raise SystemExit(f"refusing non-HTTPS URL: {url}")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "opal-pkgs"}), timeout=120) as r:
        return r.read()


def key(v):
    return tuple(int(n) for n in re.findall(r"\d+", v))


def verify(name, url, data, suffix):
    if suffix == ".sign":  # kernel.org signs the uncompressed tar
        url, data = url.removesuffix(".xz"), lzma.decompress(data)
    with tempfile.TemporaryDirectory() as tmp:
        src, sig = Path(tmp, "src"), Path(tmp, "sig")
        src.write_bytes(data)
        sig.write_bytes(get(url + suffix))
        if suffix == ".minisig":
            cmd = ["minisign", "-Vq", "-p", ROOT / "keys" / f"{name}.pub", "-m", src, "-x", sig]
        else:
            cmd = ["gpgv", "--keyring", ROOT / "keys" / f"{name}.gpg", sig, src]
        if subprocess.run(cmd, capture_output=True).returncode:
            raise SystemExit(f"{name}: {url} failed signature verification")


lines = VERSIONS.read_text().splitlines()
for i, line in enumerate(lines):
    name, current, _, pinned, url = line.split("\t") if not line.startswith("#") else [""] * 5
    if name not in LATEST:
        continue
    page, pattern, suffix = LATEST[name]
    found = re.findall(pattern, get(page).decode())
    if not found:
        raise SystemExit(f"{name}: no versions matched on {page}")
    latest = max(found + [current], key=key)
    data = get(url.replace("{v}", latest))
    if suffix:
        verify(name, url.replace("{v}", latest), data, suffix)
    sha = hashlib.sha256(data).hexdigest()
    if latest == current:
        if sha != pinned:
            raise SystemExit(f"{name}: upstream {current} no longer matches its pinned SHA-256")
        continue
    lines[i] = "\t".join([name, latest, "1", sha, url])
    print(f"- {name} {current} -> {latest}")
VERSIONS.write_text("\n".join(lines) + "\n")
