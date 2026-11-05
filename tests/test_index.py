import gzip
import hashlib
import io
import tarfile

import pytest

from opal_pkgs import index, pack

CONTROL = b"Package: demo\nVersion: 1.0\nArchitecture: all\nDescription: demo\n"


def ipk_bytes():
    return pack.ipk(
        [
            ("debian-binary", b"2.0\n"),
            ("data.tar.gz", pack.tgz([("usr/bin/demo", b"hi", 0o755)])),
            ("control.tar.gz", pack.tgz([("control", CONTROL, 0o644)])),
        ]
    )


def ar_archive(members):
    raw = bytearray(b"!<arch>\n")
    for name, data in members:
        header = (
            f"{name:<16}{0:<12}{0:<6}{0:<6}{0o100644:<8}{len(data):<10}`\n".encode()
        )
        assert len(header) == 60
        raw += header + data
        if len(data) % 2:
            raw += b"\n"
    return bytes(raw)


def test_stanza_lists_the_file_size_and_hash(tmp_path):
    raw = ipk_bytes()
    path = tmp_path / "demo.ipk"
    path.write_bytes(raw)
    text = index.stanza(path)
    assert "Package: demo" in text
    assert f"Filename: {path.name}" in text
    assert f"Size: {len(raw)}" in text
    assert f"SHA256sum: {hashlib.sha256(raw).hexdigest()}" in text


def test_members_read_an_ar_archive_with_odd_padding():
    control = pack.tgz([("control", CONTROL, 0o644)])
    raw = ar_archive([("control.tar.gz", control), ("debian-binary", b"2")])
    found = dict(index.members(raw))
    assert found["debian-binary"] == b"2"
    assert index.control(raw) == CONTROL.decode().strip()


def test_write_index_rejects_a_bad_control_or_an_empty_feed(tmp_path):
    missing = tmp_path / "missing.ipk"
    missing.write_bytes(
        pack.ipk(
            [
                ("debian-binary", b"2.0\n"),
                (
                    "control.tar.gz",
                    pack.tgz(
                        [("control", b"Package: demo\nArchitecture: all\n", 0o644)]
                    ),
                ),
            ]
        )
    )
    with pytest.raises(SystemExit, match="no Version"):
        index.stanza(missing)

    arm = tmp_path / "arm.ipk"
    arm.write_bytes(
        pack.ipk(
            [
                ("debian-binary", b"2.0\n"),
                (
                    "control.tar.gz",
                    pack.tgz([("control", CONTROL.replace(b"all", b"arm"), 0o644)]),
                ),
            ]
        )
    )
    with pytest.raises(SystemExit, match="does not run on the Opal"):
        index.stanza(arm)

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SystemExit, match="no ipks"):
        index.write_index(empty)


def test_version_key_and_human_size():
    assert index.version_key("1.9-1") < index.version_key("1.10-1")
    assert index.version_key("1.2-9") < index.version_key("1.2-10")
    assert index.human_size(512) == "512 B"
    assert index.human_size(1536) == "1.5 KiB"
    assert index.human_size(1024 * 1024) == "1 MiB"


def test_write_index_writes_a_package_browser(tmp_path):
    feed = tmp_path / "feed"
    feed.mkdir()

    def put(name, package, version, description=None, extra=b""):
        lines = [f"Package: {package}", f"Version: {version}", "Architecture: all"]
        if description is not None:
            lines.append(f"Description: {description}")
        (feed / name).write_bytes(
            pack.ipk(
                [
                    ("debian-binary", b"2.0\n"),
                    ("data.tar.gz", pack.tgz([("usr/bin/demo", b"hi", 0o755)])),
                    (
                        "control.tar.gz",
                        pack.tgz(
                            [
                                (
                                    "control",
                                    ("\n".join(lines) + "\n").encode() + extra,
                                    0o644,
                                )
                            ]
                        ),
                    ),
                ]
            )
        )

    put("aaa_1.0-1_all.ipk", "aaa", "1.0-1")
    put("demo_1.9-1_all.ipk", "demo", "1.9-1", "old tool")
    put(
        "demo_1.10-1_all.ipk",
        "demo",
        "1.10-1",
        'a <b>bold</b> "tool"',
        b"Depends: libc\nLicense: GPL-2.0\nSection: net\nInstalled-Size: 12\n",
    )
    index.write_index(feed)
    page = (feed / "index.html").read_text()
    assert "2 packages, 3 ipks" in page
    assert page.index("<h2>aaa</h2>") < page.index("<h2>demo</h2>")
    assert page.index("1.10-1") < page.index("1.9-1")
    assert "<b>" not in page
    assert "&lt;b&gt;bold&lt;/b&gt; &quot;tool&quot;" in page
    assert "Depends: libc" in page
    assert "License: GPL-2.0" in page
    assert 'href="demo_1.10-1_all.ipk"' in page
    assert (
        hashlib.sha256((feed / "demo_1.10-1_all.ipk").read_bytes()).hexdigest() in page
    )
    assert "old tool" in page
    assert '<details class="older"><summary>1 older version</summary>' in page
    assert page.count("older version") == 1
    assert ">checksum</summary>" in page
    assert ">depends and checksum</summary>" in page
    assert 'id="q"' in page
    assert "src/gz opal https://kgrubb.github.io/opal-pkgs" in page
    assert "location.href" not in page


def test_write_index_writes_packages_and_a_zero_mtime_gzip(tmp_path):
    feed = tmp_path / "feed"
    feed.mkdir()
    (feed / "demo.ipk").write_bytes(ipk_bytes())
    index.write_index(feed)
    text = (feed / "Packages").read_text()
    assert text.startswith("Package: demo\n")
    assert (feed / "Packages.gz").read_bytes()[4:8] == b"\x00\x00\x00\x00"
    assert gzip.decompress((feed / "Packages.gz").read_bytes()).decode() == text


def test_tar_member_directories_are_skipped():
    buf = io.BytesIO()
    with (
        gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz,
        tarfile.open(fileobj=gz, mode="w") as tf,
    ):
        info = tarfile.TarInfo("./dir")
        info.type = tarfile.DIRTYPE
        tf.addfile(info)
        payload = b"hi"
        file_info = tarfile.TarInfo("./file")
        file_info.size = len(payload)
        tf.addfile(file_info, io.BytesIO(payload))
    found = dict(index.members(buf.getvalue()))
    assert found == {"file": b"hi"}
