"""Bump ./versions to the newest signed upstream release of each package and print what changed."""

import hashlib
import lzma
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "versions"


def load_latest():
    from . import pack

    return {name: mod.LATEST for name, mod in pack.load_recipes()}


def check_freexian(fetch):
    """Fail when a recipe's Freexian ELTS pin lags the pool (or is ahead of it)."""
    from . import pack

    errors = []
    for name, mod in pack.load_recipes():
        pin = getattr(mod, "FREEXIAN", None)
        if pin is None:
            continue
        page, pattern, pinned = pin
        found = [int(n) for n in re.findall(pattern, fetch(page).decode())]
        if not found:
            errors.append(f"{name}: no Freexian revisions matched on {page}")
            continue
        newest = max(found)
        if newest > pinned:
            errors.append(
                f"{name}: Freexian deb11u{newest} available (pinned u{pinned})"
            )
        elif newest < pinned:
            errors.append(f"{name}: Freexian pin u{pinned} ahead of pool max u{newest}")
    return errors


# One upstream file, extra packages. A follower keeps its own release until the version changes.
SAME = {
    "ca-bundle": ("ca-certificates",),
    "curl": ("libcurl",),
    "libopenssl": ("openssl-util", "libopenssl-conf"),
}


def get(url):
    if not url.startswith("https://"):
        raise SystemExit(f"refusing non-HTTPS URL: {url}")
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "opal-pkgs"}), timeout=120
    ) as r:
        return r.read()


def key(v):
    return tuple(int(n) for n in re.findall(r"\d+", v))


def signer(name, suffix):
    ext = "pub" if suffix == ".minisig" else "gpg"
    return ROOT / "pkg" / name / f"key.{ext}"


def verify(name, url, data, suffix, fetch, run=subprocess.run):
    if suffix == ".sign":  # kernel.org signs the uncompressed tar
        url, data = url.removesuffix(".xz"), lzma.decompress(data)
    with tempfile.TemporaryDirectory() as tmp:
        src, sig = Path(tmp, "src"), Path(tmp, "sig")
        src.write_bytes(data)
        sig.write_bytes(
            fetch(suffix if suffix.startswith("https://") else url + suffix)
        )
        if suffix == ".minisig":
            cmd = [
                "minisign",
                "-Vq",
                "-p",
                signer(name, suffix),
                "-m",
                src,
                "-x",
                sig,
            ]
        else:
            cmd = ["gpgv", "--keyring", signer(name, suffix), sig, src]
        if run(cmd, capture_output=True).returncode:
            raise SystemExit(f"{name}: {url} failed signature verification")


def apply(lines, fetch, latest=None):
    """Bump each package on its own. One failure leaves the rest of the pins in place."""
    latest = load_latest() if latest is None else latest
    errors, notes = [], []
    out = list(lines)
    for i, line in enumerate(lines):
        name, current, _, pinned, url = (
            line.split("\t") if line and not line.startswith("#") else [""] * 5
        )
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
                verify(
                    name,
                    url.replace("{v}", newest),
                    data,
                    suffix.replace("{v}", newest),
                    fetch,
                )
            sha = hashlib.sha256(data).hexdigest()
            if newest == current:
                if sha != pinned:
                    raise SystemExit(
                        f"{name}: upstream {current} no longer matches its pinned SHA-256"
                    )
                continue
            out[i] = f"{name}\t{newest}\t1\t{sha}\t{url}"
            notes.append(f"- {name} {current} -> {newest}")
            for other in SAME.get(name, ()):
                for j, follower in enumerate(out):
                    cols = (
                        follower.split("\t")
                        if follower and not follower.startswith("#")
                        else []
                    )
                    if cols and cols[0] == other:
                        previous = cols[1]
                        cols[1], cols[2], cols[3] = newest, "1", sha
                        out[j] = "\t".join(cols)
                        notes.append(f"- {other} {previous} -> {newest}")
        except (SystemExit, OSError) as err:
            errors.append(
                err.code
                if isinstance(err, SystemExit) and isinstance(err.code, str)
                else f"{name}: {err}"
            )
    return out, notes, errors


def main(fetch=get):
    lines, notes, errors = apply(VERSIONS.read_text().splitlines(), fetch)
    errors.extend(check_freexian(fetch))
    if notes:
        print("\n".join(notes))
    VERSIONS.write_text("\n".join(lines) + "\n")
    if errors:
        raise SystemExit("\n".join(errors))
