#!/usr/bin/env python3
"""Checks for the weekly update: one bad package must not block the rest, and a changed ipk must get a new release."""
import subprocess
import tempfile
from pathlib import Path

import pack
import update


def test_apply():
    lines = [
        "dropbear\t1.0\t1\told\thttps://example.test/dropbear-{v}.tar",
        "sudo\t9.0\t1\told\thttps://example.test/sudo-{v}.tar",
    ]

    def fetch(url):
        if "sudo.ws" in url:
            raise SystemExit("sudo: down")
        if url.endswith("2.0.tar"):
            return b"new"
        return b"dropbear-1.0.tar.bz2 dropbear-2.0.tar.bz2"

    latest = {
        "dropbear": ("https://example.test/db/", r"dropbear-(\d+\.\d+)\.tar\.bz2", None),
        "sudo": ("https://www.sudo.ws/dist/", r"sudo-(\d+\.\d+)\.tar\.gz", None),
    }
    out, notes, errors = update.apply(lines, fetch, latest)
    if out[0].split("\t")[1] != "2.0" or out[1] != lines[1] or len(notes) != 1 or len(errors) != 1:
        raise SystemExit(f"{out}\n{notes}\n{errors}")


def test_settle():
    feed = Path(tempfile.mkdtemp())
    (feed / "p-1.ipk").write_bytes(b"old")

    def name(rel):
        return f"p-{rel}.ipk"

    def blob(_rel):
        return b"new"

    rel, data = pack.settle(feed, "1", name, blob)
    if (rel, data) != ("2", b"new"):
        raise SystemExit((rel, data))
    (feed / "p-2.ipk").write_bytes(b"new")
    if pack.settle(feed, "1", name, blob)[0] != "2":
        raise SystemExit("matching bytes did not keep the bumped release")
    if pack.settle(Path(tempfile.mkdtemp()), "1", name, blob)[0] != "1":
        raise SystemExit("missing feed file should keep the release")


def test_restore():
    base = "dropbear\t1.0\t1\told\thttps://example.test/a\nsudo\t9.0\t1\told\thttps://example.test/b\n"
    cur = "dropbear\t2.0\t1\tnew\thttps://example.test/a\nsudo\t9.1\t1\tnew\thttps://example.test/b\n"
    d = Path(tempfile.mkdtemp())
    (d / "base").write_text(base)
    (d / "versions").write_text(cur)
    out = subprocess.run(
        ["awk", "-F", "\t", "-v", "n=dropbear", "-f", str(Path(__file__).with_name("restore.awk")), str(d / "base"), str(d / "versions")],
        check=True, capture_output=True, text=True,
    ).stdout
    if out != "dropbear\t1.0\t1\told\thttps://example.test/a\nsudo\t9.1\t1\tnew\thttps://example.test/b\n":
        raise SystemExit(out)


if __name__ == "__main__":
    test_apply()
    test_settle()
    test_restore()
    print("ok")
