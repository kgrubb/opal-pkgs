import hashlib
import io
import lzma
import subprocess
from pathlib import Path

import pytest

from opal_pkgs import update


def test_apply_bumps_one_package_when_another_lookup_fails():
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
        "dropbear": (
            "https://example.test/db/",
            r"dropbear-(\d+\.\d+)\.tar\.bz2",
            None,
        ),
        "sudo": ("https://www.sudo.ws/dist/", r"sudo-(\d+\.\d+)\.tar\.gz", None),
    }
    out, notes, errors = update.apply(lines, fetch, latest)
    assert out[0].split("\t")[1] == "2.0"
    assert out[0].split("\t")[2] == "1"
    assert out[1] == lines[1]
    assert notes == ["- dropbear 1.0 -> 2.0"]
    assert errors == ["sudo: down"]


def test_apply_picks_the_highest_numeric_version():
    lines = ["dropbear\t1.9\t3\told\thttps://example.test/dropbear-{v}.tar"]

    def fetch(url):
        if url.endswith("1.10.tar"):
            return b"ten"
        return b"dropbear-1.9.tar.bz2 dropbear-1.10.tar.bz2"

    latest = {
        "dropbear": ("https://example.test/db/", r"dropbear-(\d+\.\d+)\.tar\.bz2", None)
    }
    out, notes, errors = update.apply(lines, fetch, latest)
    assert out[0].split("\t")[1] == "1.10"
    assert notes == ["- dropbear 1.9 -> 1.10"]
    assert errors == []


def test_apply_takes_the_release_year_from_the_announcement_page():
    lines = [
        "libsqlite3\t3540100\t1\told\thttps://www.sqlite.org/2026/sqlite-autoconf-{v}.tar.gz"
    ]
    body = b"new-tarball"
    digest = hashlib.sha3_256(body).hexdigest()
    page = (
        "sqlite-autoconf-3550000.tar.gz SHA3-256: "
        + digest
        + " d391('a3','2027/sqlite-autoconf-3550000.tar.gz');"
    )

    def fetch(url):
        if url.endswith("download.html"):
            return page.encode()
        assert url == "https://www.sqlite.org/2027/sqlite-autoconf-3550000.tar.gz"
        return body

    latest = {
        "libsqlite3": (
            "https://www.sqlite.org/download.html",
            r"sqlite-autoconf-(\d+)\.tar\.gz",
            None,
        )
    }
    out, notes, errors = update.apply(lines, fetch, latest)
    cols = out[0].split("\t")
    assert cols[1] == "3550000"
    assert cols[4] == "https://www.sqlite.org/2027/sqlite-autoconf-{v}.tar.gz"
    assert notes == ["- libsqlite3 3540100 -> 3550000"]
    assert errors == []


def test_apply_rejects_a_sqlite_year_move_that_changes_the_same_version():
    lines = [
        "libsqlite3\t3540100\t1\told\thttps://www.sqlite.org/2026/sqlite-autoconf-{v}.tar.gz"
    ]
    body = b"moved-year"
    digest = hashlib.sha3_256(body).hexdigest()
    page = (
        "sqlite-autoconf-3540100.tar.gz SHA3-256: "
        + digest
        + " d391('a3','2027/sqlite-autoconf-3540100.tar.gz');"
    )

    def fetch(url):
        if url.endswith("download.html"):
            return page.encode()
        assert url == "https://www.sqlite.org/2027/sqlite-autoconf-3540100.tar.gz"
        return body

    latest = {
        "libsqlite3": (
            "https://www.sqlite.org/download.html",
            r"sqlite-autoconf-(\d+)\.tar\.gz",
            None,
        )
    }
    out, notes, errors = update.apply(lines, fetch, latest)
    assert out == lines
    assert notes == []
    assert "no longer matches" in errors[0]


def test_apply_rejects_a_sqlite_tarball_that_misses_the_page_sha3():
    lines = [
        "libsqlite3\t3540100\t1\told\thttps://www.sqlite.org/2026/sqlite-autoconf-{v}.tar.gz"
    ]
    page = "sqlite-autoconf-3540100.tar.gz SHA3-256: " + "ab" * 32

    def fetch(url):
        if url.endswith("download.html"):
            return page.encode()
        return b"not-the-file"

    latest = {
        "libsqlite3": (
            "https://www.sqlite.org/download.html",
            r"sqlite-autoconf-(\d+)\.tar\.gz",
            None,
        )
    }
    out, notes, errors = update.apply(lines, fetch, latest)
    assert out == lines
    assert notes == []
    assert "SHA3-256" in errors[0]


def test_apply_keeps_a_comment_and_reports_a_missing_version():
    lines = ["# keep", "dropbear\t1.0\t1\told\thttps://example.test/dropbear-{v}.tar"]
    latest = {
        "dropbear": ("https://example.test/db/", r"dropbear-(\d+\.\d+)\.tar\.bz2", None)
    }
    out, notes, errors = update.apply(lines, lambda url: b"no versions here", latest)
    assert out == lines
    assert notes == []
    assert "no versions matched" in errors[0]


OLD = "9217ab46536353c7c792951b57163063f5ec7a3b"
NEW = "0123456789abcdef0123456789abcdef01234567"
USTREAM = (
    "https://example.test/Makefile",
    r"PKG_SOURCE_DATE:=(\d{4}-\d{2}-\d{2})",
    None,
)


def _ustream_line(commit, sha):
    return (
        "libustream-openssl\t2022-12-08\t3\t"
        + sha
        + f"\thttps://github.com/openwrt/ustream-ssl/archive/{commit}.tar.gz"
    )


def _makefile(date, commit):
    return f"PKG_SOURCE_DATE:={date}\nPKG_SOURCE_VERSION:={commit}\n"


def test_apply_leaves_an_unchanged_ustream_snapshot():
    body = b"same-snapshot"
    sha = hashlib.sha256(body).hexdigest()
    lines = [_ustream_line(OLD, sha)]

    def fetch(url):
        if url.endswith("Makefile"):
            return _makefile("2022-12-08", OLD).encode()
        assert url.endswith(f"{OLD}.tar.gz")
        return body

    out, notes, errors = update.apply(lines, fetch, {"libustream-openssl": USTREAM})
    assert out == lines
    assert notes == []
    assert errors == []


def test_apply_tracks_a_new_ustream_commit_without_a_new_date():
    body = b"new-snapshot"
    lines = [_ustream_line(OLD, "old-sha")]

    def fetch(url):
        if url.endswith("Makefile"):
            return _makefile("2022-12-08", NEW).encode()
        assert url.endswith(f"{NEW}.tar.gz")
        return body

    out, notes, errors = update.apply(lines, fetch, {"libustream-openssl": USTREAM})
    cols = out[0].split("\t")
    assert cols[1] == "2022-12-08"
    assert cols[2] == "3"
    assert cols[3] == hashlib.sha256(body).hexdigest()
    assert cols[4].endswith(f"{NEW}.tar.gz")
    assert notes == ["- libustream-openssl 2022-12-08 new commit"]
    assert errors == []


def test_apply_tracks_a_new_ustream_date_and_commit():
    body = b"dated-snapshot"
    lines = [_ustream_line(OLD, "old-sha")]

    def fetch(url):
        if url.endswith("Makefile"):
            return _makefile("2024-03-01", NEW).encode()
        assert url.endswith(f"{NEW}.tar.gz")
        return body

    out, notes, errors = update.apply(lines, fetch, {"libustream-openssl": USTREAM})
    cols = out[0].split("\t")
    assert cols[1] == "2024-03-01"
    assert cols[2] == "1"
    assert cols[4].endswith(f"{NEW}.tar.gz")
    assert notes == ["- libustream-openssl 2022-12-08 -> 2024-03-01"]
    assert errors == []


def test_apply_rejects_a_makefile_without_a_commit():
    lines = [_ustream_line(OLD, "old-sha")]
    latest = {"libustream-openssl": USTREAM}
    out, notes, errors = update.apply(
        lines, lambda url: b"PKG_SOURCE_DATE:=2024-03-01\n", latest
    )
    assert out == lines
    assert notes == []
    assert "PKG_SOURCE_VERSION" in errors[0]


def test_apply_rejects_a_changed_hash_for_the_same_version():
    lines = ["dropbear\t1.0\t1\told\thttps://example.test/dropbear-{v}.tar"]

    def fetch(url):
        if url.endswith("1.0.tar"):
            return b"different"
        return b"dropbear-1.0.tar.bz2"

    latest = {
        "dropbear": ("https://example.test/db/", r"dropbear-(\d+\.\d+)\.tar\.bz2", None)
    }
    out, notes, errors = update.apply(lines, fetch, latest)
    assert out == lines
    assert notes == []
    assert "no longer matches" in errors[0]


def test_ca_releases_stay_separate():
    old_sha = "ab"
    lines = [
        "ca-bundle\t2020-01-01\t4\t"
        + old_sha
        + "\thttps://example.test/cacert-{v}.pem",
        "ca-certificates\t2020-01-01\t2\t"
        + old_sha
        + "\thttps://example.test/cacert-{v}.pem",
        "sudo\t9.0\t1\told\thttps://example.test/sudo-{v}.tar",
    ]

    def fetch(url):
        if url.endswith("2020-02-02.pem"):
            return b"pem"
        if "caextract" in url or url.endswith("ca/"):
            return b"cacert-2020-02-02.pem"
        raise SystemExit("sudo: down")

    latest = {
        "ca-bundle": (
            "https://example.test/ca/",
            r"cacert-(\d{4}-\d{2}-\d{2})\.pem",
            None,
        ),
        "sudo": ("https://www.sudo.ws/dist/", r"sudo-(\d+\.\d+)\.tar\.gz", None),
    }
    out, notes, errors = update.apply(lines, fetch, latest)
    bundle, certs, sudo = (line.split("\t") for line in out)
    assert bundle[1] == "2020-02-02" and bundle[2] == "1"
    assert certs[1] == bundle[1] and certs[2] == "1" and certs[3] == bundle[3]
    assert sudo[1] == "9.0"
    assert len(errors) == 1
    assert any(note.startswith("- ca-certificates ") for note in notes)

    same = [
        "ca-bundle\t2020-02-02\t4\t"
        + bundle[3]
        + "\thttps://example.test/cacert-{v}.pem",
        "ca-certificates\t2020-02-02\t2\t"
        + bundle[3]
        + "\thttps://example.test/cacert-{v}.pem",
    ]
    out, notes, errors = update.apply(same, fetch, {"ca-bundle": latest["ca-bundle"]})
    assert [line.split("\t")[2] for line in out] == ["4", "2"]
    assert notes == [] and errors == []


def test_libopenssl_bump_moves_the_config_package():
    sha = "ab"
    url = "https://example.test/openssl-{v}.tar.gz"
    lines = [
        f"libopenssl\t1.1.1i\t5\t{sha}\t{url}",
        f"openssl-util\t1.1.1i\t3\t{sha}\t{url}",
        f"libopenssl-conf\t1.1.1i\t1\t{sha}\t{url}",
    ]

    def fetch(page):
        if page.endswith("1.1.1w.tar.gz"):
            return b"openssl"
        return b"openssl-1.1.1w.tar.gz"

    out, _notes, errors = update.apply(
        lines,
        fetch,
        {
            "libopenssl": (
                "https://example.test/openssl/",
                r"openssl-(1\.1\.1w)\.tar\.gz",
                None,
            )
        },
    )
    rows = {line.split("\t")[0]: line.split("\t") for line in out}
    assert errors == []
    assert rows["libopenssl"][1:3] == ["1.1.1w", "1"]
    assert rows["openssl-util"][1:3] == ["1.1.1w", "1"]
    assert rows["libopenssl-conf"][1:3] == ["1.1.1w", "1"]


def test_packages_are_discovered():
    found = update.load_latest()
    dirs = sorted(
        path.name
        for path in Path(__file__).parents[1].joinpath("pkg").iterdir()
        if path.is_dir()
    )
    assert sorted(found) == dirs
    assert found["ca-bundle"][1] == r"cacert-(\d{4}-\d{2}-\d{2})\.pem"
    assert found["ca-bundle"][2] is None


def test_get_refuses_a_non_https_url():
    with pytest.raises(SystemExit, match="non-HTTPS"):
        update.get("http://example.test/file")


def test_get_returns_the_response_body(monkeypatch):
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def urlopen(request, timeout):
        assert request.full_url == "https://example.test/file"
        assert timeout == 120
        return Response(b"body")

    monkeypatch.setattr(update.urllib.request, "urlopen", urlopen)
    assert update.get("https://example.test/file") == b"body"


def test_apply_verifies_a_signed_file(monkeypatch):
    seen = {}

    def verify(name, url, data, suffix, fetch):
        seen.update(name=name, url=url, data=data, suffix=suffix)

    monkeypatch.setattr(update, "verify", verify)
    lines = ["chrony\t4.8\t2\told\thttps://example.test/chrony-{v}.tar.gz"]

    def fetch(url):
        if url.endswith("4.9.tar.gz"):
            return b"tarball"
        return b"chrony-4.9.tar.gz"

    latest = {
        "chrony": (
            "https://example.test/c",
            r"chrony-(\d+\.\d+)\.tar\.gz",
            "https://example.test/chrony-{v}.asc",
        )
    }
    out, notes, errors = update.apply(lines, fetch, latest)
    assert errors == []
    assert notes == ["- chrony 4.8 -> 4.9"]
    assert out[0].split("\t")[2] == "1"
    assert seen["data"] == b"tarball"
    assert seen["suffix"] == "https://example.test/chrony-4.9.asc"


def test_main_writes_versions_and_fails_when_a_package_errors(
    monkeypatch, tmp_path, capsys
):
    versions = tmp_path / "versions"
    versions.write_text("dropbear\t1\t1\told\thttps://example.test/a\n")
    monkeypatch.setattr(update, "VERSIONS", versions)
    monkeypatch.setattr(
        update,
        "apply",
        lambda lines, fetch: (
            ["dropbear\t2\t1\tnew\thttps://example.test/a"],
            ["- dropbear 1 -> 2"],
            ["sudo: down"],
        ),
    )
    monkeypatch.setattr(update, "check_freexian", lambda fetch: [])
    with pytest.raises(SystemExit, match="sudo: down"):
        update.main()
    assert versions.read_text() == "dropbear\t2\t1\tnew\thttps://example.test/a\n"
    assert "- dropbear 1 -> 2" in capsys.readouterr().out


def test_check_freexian_reports_a_newer_pool_revision(monkeypatch):
    class Mod:
        FREEXIAN = (
            "https://example.test/openssl/",
            r"openssl_1\.1\.1w-0(?:\+|%2B)deb11u(\d+)\.debian\.tar\.xz",
            8,
        )

    from opal_pkgs import pack

    monkeypatch.setattr(pack, "load_recipes", lambda: [("libopenssl", Mod())])
    assert update.check_freexian(
        lambda url: b'href="openssl_1.1.1w-0%2Bdeb11u9.debian.tar.xz"'
    ) == ["libopenssl: Freexian deb11u9 available (pinned u8)"]


def test_check_freexian_accepts_the_pinned_revision(monkeypatch):
    class Mod:
        FREEXIAN = (
            "https://example.test/openssl/",
            r"openssl_1\.1\.1w-0(?:\+|%2B)deb11u(\d+)\.debian\.tar\.xz",
            8,
        )

    from opal_pkgs import pack

    monkeypatch.setattr(pack, "load_recipes", lambda: [("libopenssl", Mod())])
    assert (
        update.check_freexian(
            lambda url: b'href="openssl_1.1.1w-0+deb11u8.debian.tar.xz"'
        )
        == []
    )


def test_check_freexian_skips_recipes_without_a_pin(monkeypatch):
    from opal_pkgs import pack

    monkeypatch.setattr(pack, "load_recipes", lambda: [("ethtool", object())])
    assert update.check_freexian(lambda url: b"") == []


def ok(cmd, capture_output=True):
    return subprocess.CompletedProcess(cmd, 0)


@pytest.mark.parametrize(
    ("name", "suffix", "tool", "key"),
    [
        ("dnscrypt-proxy", ".minisig", "minisign", "key.pub"),
        ("dropbear", ".asc", "gpgv", "key.gpg"),
    ],
)
def test_verify_checks_the_package_key(name, suffix, tool, key):
    calls = []

    def run(cmd, capture_output=True):
        calls.append(list(map(str, cmd)))
        return ok(cmd)

    update.verify(
        name,
        "https://example.test/a.tar.gz",
        b"data",
        suffix,
        lambda url: b"sig",
        run=run,
    )
    assert calls[0][0] == tool
    if tool == "minisign":
        assert calls[0][1] == "-Vq"
    assert any(part.endswith(f"pkg/{name}/{key}") for part in calls[0])


def test_verify_checks_the_uncompressed_kernel_tarball():
    payload = b"tar-bytes"
    fetched = []
    checked = []

    def fetch(url):
        fetched.append(url)
        return b"sig"

    def run(cmd, capture_output=True):
        checked.append(Path(cmd[-1]).read_bytes())
        return ok(cmd)

    update.verify(
        "ethtool",
        "https://example.test/ethtool-1.tar.xz",
        lzma.compress(payload),
        ".sign",
        fetch,
        run=run,
    )
    assert fetched == ["https://example.test/ethtool-1.tar.sign"]
    assert checked == [payload]


def test_verify_rejects_a_bad_signature():
    def reject(cmd, capture_output=True):
        return subprocess.CompletedProcess(cmd, 1)

    with pytest.raises(SystemExit, match="failed signature"):
        update.verify(
            "dropbear",
            "https://example.test/a.tar.gz",
            b"data",
            ".asc",
            lambda url: b"sig",
            run=reject,
        )


def test_signer_keys_live_with_the_package():
    assert not (update.ROOT / "keys").exists()
    for name, (_page, _pattern, suffix) in update.load_latest().items():
        if not suffix:
            continue
        assert update.signer(name, suffix).is_file()


def test_verify_fetches_a_full_signature_url():
    seen = []

    def fetch(url):
        seen.append(url)
        return b"sig"

    def run(cmd, capture_output=True):
        return subprocess.CompletedProcess(cmd, 0)

    update.verify(
        "chrony",
        "https://example.test/chrony-4.9.tar.gz",
        b"data",
        "https://example.test/chrony-4.9-tar-gz-asc.txt",
        fetch,
        run=run,
    )
    assert seen == ["https://example.test/chrony-4.9-tar-gz-asc.txt"]
