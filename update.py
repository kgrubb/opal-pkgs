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


def load_latest():
    """(announcement page, version regex, signature suffix) from each pkg/<name>/pack.py."""
    import pack
    return {name: mod.LATEST for name, mod in pack.load_recipes()}

# One upstream file, two packages. The follower keeps its own release until the version changes.
SAME = {"ca-bundle": "ca-certificates"}


def get(url):
    if not url.startswith("https://"):
        raise SystemExit(f"refusing non-HTTPS URL: {url}")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "opal-pkgs"}), timeout=120) as r:
        return r.read()


def key(v):
    return tuple(int(n) for n in re.findall(r"\d+", v))


# The signer's key is keys/<name>.gpg, or keys/<name>.pub for minisign.
def verify(name, url, data, suffix, fetch):
    if suffix == ".sign":  # kernel.org signs the uncompressed tar
        url, data = url.removesuffix(".xz"), lzma.decompress(data)
    with tempfile.TemporaryDirectory() as tmp:
        src, sig = Path(tmp, "src"), Path(tmp, "sig")
        src.write_bytes(data)
        sig.write_bytes(fetch(suffix if suffix.startswith("https://") else url + suffix))
        if suffix == ".minisig":
            cmd = ["minisign", "-Vq", "-p", ROOT / "keys" / f"{name}.pub", "-m", src, "-x", sig]
        else:
            cmd = ["gpgv", "--keyring", ROOT / "keys" / f"{name}.gpg", sig, src]
        if subprocess.run(cmd, capture_output=True).returncode:
            raise SystemExit(f"{name}: {url} failed signature verification")


def apply(lines, fetch, latest=None):
    """Bump each package on its own. One failure leaves the rest of the pins in place."""
    latest = load_latest() if latest is None else latest
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
                verify(name, url.replace("{v}", newest), data, suffix.replace("{v}", newest), fetch)
            sha = hashlib.sha256(data).hexdigest()
            if newest == current:
                if sha != pinned:
                    raise SystemExit(f"{name}: upstream {current} no longer matches its pinned SHA-256")
                continue
            out[i] = "\t".join([name, newest, "1", sha, url])
            notes.append(f"- {name} {current} -> {newest}")
            other = SAME.get(name)
            if other:
                for j, follower in enumerate(out):
                    cols = follower.split("\t") if follower and not follower.startswith("#") else []
                    if cols and cols[0] == other:
                        previous = cols[1]
                        cols[1], cols[2], cols[3] = newest, "1", sha
                        out[j] = "\t".join(cols)
                        notes.append(f"- {other} {previous} -> {newest}")
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
