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
    # The GitHub tag archive has no maintainer signature, so HTTPS is the only check.
    "wireguard-tools": ("https://github.com/WireGuard/wireguard-tools/tags", r"v(1\.0\.\d+)", None),
    # The tag archive has no maintainer signature. libpcap is pinned in versions and linked in.
    "softflowd": ("https://github.com/irino/softflowd/tags", r"softflowd-v(\d+\.\d+\.\d+)", None),
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


def verify(name, url, data, suffix, fetch):
    if suffix == ".sign":  # kernel.org signs the uncompressed tar
        url, data = url.removesuffix(".xz"), lzma.decompress(data)
    with tempfile.TemporaryDirectory() as tmp:
        src, sig = Path(tmp, "src"), Path(tmp, "sig")
        src.write_bytes(data)
        sig.write_bytes(fetch(url + suffix))
        if suffix == ".minisig":
            cmd = ["minisign", "-Vq", "-p", ROOT / "keys" / f"{name}.pub", "-m", src, "-x", sig]
        else:
            cmd = ["gpgv", "--keyring", ROOT / "keys" / f"{name}.gpg", sig, src]
        if subprocess.run(cmd, capture_output=True).returncode:
            raise SystemExit(f"{name}: {url} failed signature verification")


def apply(lines, fetch, latest=None):
    """Bump each package on its own. One failure leaves the rest of the pins in place."""
    latest = LATEST if latest is None else latest
    errors, notes = [], []
    out = list(lines)
    for i, line in enumerate(lines):
        name, current, _, pinned, url = line.split("\t") if line and not line.startswith("#") else [""] * 5
        if name not in latest:
            continue
        try:
            page, pattern, suffix = latest[name]
            found = re.findall(pattern, fetch(page).decode())
            if not found:
                raise SystemExit(f"{name}: no versions matched on {page}")
            newest = max(found + [current], key=key)
            data = fetch(url.replace("{v}", newest))
            if suffix:
                verify(name, url.replace("{v}", newest), data, suffix, fetch)
            sha = hashlib.sha256(data).hexdigest()
            if newest == current:
                if sha != pinned:
                    raise SystemExit(f"{name}: upstream {current} no longer matches its pinned SHA-256")
                continue
            out[i] = "\t".join([name, newest, "1", sha, url])
            notes.append(f"- {name} {current} -> {newest}")
        except (SystemExit, OSError) as err:
            errors.append(err.code if isinstance(err, SystemExit) and isinstance(err.code, str) else f"{name}: {err}")
    return out, notes, errors


if __name__ == "__main__":
    lines, notes, errors = apply(VERSIONS.read_text().splitlines(), get)
    if notes:
        print("\n".join(notes))
    VERSIONS.write_text("\n".join(lines) + "\n")
    if errors:
        raise SystemExit("\n".join(errors))
