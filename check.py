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


def test_ca_releases_stay_separate():
    old_sha = "ab"
    lines = [
        "ca-bundle\t2020-01-01\t4\t" + old_sha + "\thttps://example.test/cacert-{v}.pem",
        "ca-certificates\t2020-01-01\t2\t" + old_sha + "\thttps://example.test/cacert-{v}.pem",
        "sudo\t9.0\t1\told\thttps://example.test/sudo-{v}.tar",
    ]

    def fetch(url):
        if url.endswith("2020-02-02.pem"):
            return b"pem"
        if "caextract" in url or url.endswith("ca/"):
            return b"cacert-2020-02-02.pem"
        raise SystemExit("sudo: down")

    latest = {
        "ca-bundle": ("https://example.test/ca/", r"cacert-(\d{4}-\d{2}-\d{2})\.pem", None),
        "sudo": ("https://www.sudo.ws/dist/", r"sudo-(\d+\.\d+)\.tar\.gz", None),
    }
    out, notes, errors = update.apply(lines, fetch, latest)
    bundle, certs, sudo = (line.split("\t") for line in out)
    if bundle[1] != "2020-02-02" or bundle[2] != "1":
        raise SystemExit(f"bundle pin {bundle}")
    if certs[1] != bundle[1] or certs[2] != "1" or certs[3] != bundle[3]:
        raise SystemExit(f"certs pin did not follow the new file {certs}")
    if sudo[1] != "9.0" or len(errors) != 1:
        raise SystemExit(f"{sudo} {errors}")
    if not any(note.startswith("- ca-certificates ") for note in notes):
        raise SystemExit(notes)

    same = [
        "ca-bundle\t2020-02-02\t4\t" + bundle[3] + "\thttps://example.test/cacert-{v}.pem",
        "ca-certificates\t2020-02-02\t2\t" + bundle[3] + "\thttps://example.test/cacert-{v}.pem",
    ]
    out, notes, errors = update.apply(same, fetch, {"ca-bundle": latest["ca-bundle"]})
    if [line.split("\t")[2] for line in out] != ["4", "2"] or notes or errors:
        raise SystemExit(f"same version changed a release\n{out}\n{notes}\n{errors}")


def test_build_keeps_set_e():
    text = Path(__file__).with_name("build.sh").read_text()
    if "if ! (" in text:
        raise SystemExit("a package build is inside an if test, so set -e does not apply")


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
    test_ca_releases_stay_separate()
    test_build_keeps_set_e()
    test_restore()
    print("ok")
