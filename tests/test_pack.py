import gzip
import io
import re
import struct
import tarfile
from pathlib import Path

import pytest

from opal_pkgs import pack


def elf_bytes(machine=8, ph_types=(1,), extra=b""):
    phentsize = 32
    phnum = len(ph_types)
    phoff = 52 if phnum else 0
    buf = bytearray(52 + phentsize * phnum + len(extra))
    buf[0:6] = b"\x7fELF\x01\x01"
    struct.pack_into("<H", buf, 18, machine)
    struct.pack_into("<I", buf, 28, phoff)
    struct.pack_into("<HH", buf, 42, phentsize if phnum else 0, phnum)
    for i, ptype in enumerate(ph_types):
        struct.pack_into("<I", buf, phoff + i * phentsize, ptype)
    buf[52 + phentsize * phnum :] = extra
    return bytes(buf)


def test_settle_bumps_until_the_bytes_match(tmp_path):
    feed = tmp_path
    (feed / "p-1.ipk").write_bytes(b"old")

    rel, data = pack.settle(feed, "1", lambda rel: f"p-{rel}.ipk", lambda rel: b"new")
    assert (rel, data) == ("2", b"new")
    (feed / "p-2.ipk").write_bytes(b"new")
    assert (
        pack.settle(feed, "1", lambda rel: f"p-{rel}.ipk", lambda rel: b"new")[0] == "2"
    )
    assert (
        pack.settle(
            tmp_path / "empty", "1", lambda rel: f"p-{rel}.ipk", lambda rel: b"new"
        )[0]
        == "1"
    )


def test_settle_stops_after_twenty_bumps(tmp_path):
    for i in range(1, 22):
        (tmp_path / f"p-{i}.ipk").write_bytes(b"old")
    with pytest.raises(SystemExit, match="did not settle"):
        pack.settle(tmp_path, "1", lambda rel: f"p-{rel}.ipk", lambda rel: b"new")


def test_elf_accepts_a_static_mips_binary(tmp_path):
    good = tmp_path / "good"
    good.write_bytes(elf_bytes())
    assert pack.elf(good) == good.read_bytes()


@pytest.mark.parametrize(
    ("data", "match"),
    [
        (b"not an elf", "not a 32-bit little-endian MIPS ELF"),
        (elf_bytes(machine=3), "not a 32-bit little-endian MIPS ELF"),
        (elf_bytes(ph_types=(3,)), "dynamically linked"),
        (elf_bytes(extra=b"clock_gettime64"), "time64"),
    ],
)
def test_elf_rejects_a_binary_the_opal_cannot_run(tmp_path, data, match):
    path = tmp_path / "bad"
    path.write_bytes(data)
    with pytest.raises(SystemExit, match=match):
        pack.elf(path)


def test_tgz_and_ipk_roundtrip():
    blob = pack.tgz([("usr/bin/tool", b"hi", 0o755), ("usr/bin/tool-link", "tool")])
    assert blob[4:8] == b"\x00\x00\x00\x00"
    with (
        gzip.GzipFile(fileobj=io.BytesIO(blob)) as gz,
        tarfile.open(fileobj=gz, mode="r") as tf,
    ):
        tool = tf.getmember("./usr/bin/tool")
        link = tf.getmember("./usr/bin/tool-link")
        assert tf.extractfile(tool).read() == b"hi"
        assert tool.mode == 0o755
        assert link.issym() and link.linkname == "tool"
        assert tool.uname == "root"

    raw = pack.ipk([("debian-binary", b"2.0\n"), ("data.tar.gz", blob)])
    assert raw[4:8] == b"\x00\x00\x00\x00"
    with (
        gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz,
        tarfile.open(fileobj=gz, mode="r") as tf,
    ):
        names = {m.name.removeprefix("./") for m in tf.getmembers()}
    assert names == {"debian-binary", "data.tar.gz"}


def test_set_release_rewrites_one_pin(monkeypatch, tmp_path):
    (tmp_path / "versions").write_text(
        "ethtool\t7.2\t1\tabc\thttps://example.test/e-{v}.tar\nkept\t1\t9\tx\thttps://example.test/k\n"
    )
    monkeypatch.setattr(pack, "ROOT", tmp_path)
    monkeypatch.setattr(
        pack,
        "PINS",
        {"ethtool": ["ethtool", "7.2", "1", "abc", "https://example.test/e-{v}.tar"]},
    )
    pack.set_release("ethtool", "4")
    rows = (tmp_path / "versions").read_text().splitlines()
    assert rows[0].split("\t")[2] == "4"
    assert rows[1].split("\t")[2] == "9"
    assert pack.PINS["ethtool"][2] == "4"


def test_tree_uses_the_pinned_version():
    pinned = next(
        line.split("\t")[1]
        for line in (pack.ROOT / "versions").read_text().splitlines()
        if line.startswith("dropbear\t")
    )
    assert pack.tree("dropbear") == pack.WORK / f"dropbear-{pinned}"


def test_load_recipes_skips_a_directory_without_a_recipe(monkeypatch, tmp_path):
    (tmp_path / "pkg" / "notes").mkdir(parents=True)
    demo = tmp_path / "pkg" / "demo"
    demo.mkdir()
    (demo / "pack.py").write_text("LATEST = ('https://example.test/', 'v', None)\n")
    monkeypatch.setattr(pack, "ROOT", tmp_path)
    assert [name for name, _mod in pack.load_recipes()] == ["demo"]


def test_pack_bumps_the_release_and_records_conffiles(monkeypatch, tmp_path):
    feed = tmp_path / "feed"
    feed.mkdir()
    (feed / "p_20200101-1_all.ipk").write_bytes(b"old")
    (tmp_path / "out").mkdir()
    (tmp_path / "versions").write_text(
        "p\t2020-01-01\t1\tab\thttps://example.test/p-{v}.tar\n"
    )
    monkeypatch.setattr(pack, "ROOT", tmp_path)
    monkeypatch.setattr(pack, "OUT", tmp_path / "out")
    monkeypatch.setattr(
        pack,
        "PINS",
        {"p": ["p", "2020-01-01", "1", "ab", "https://example.test/p-{v}.tar"]},
    )
    pack.pack(
        "p",
        "p",
        "all",
        "Description: demo\n",
        [("usr/bin/p", b"hi", 0o755)],
        conffiles=("/etc/config/p",),
    )
    written = tmp_path / "out" / "p_20200101-2_all.ipk"
    assert written.is_file()
    assert (tmp_path / "versions").read_text().split("\t")[2] == "2"
    with (
        gzip.GzipFile(fileobj=io.BytesIO(written.read_bytes())) as gz,
        tarfile.open(fileobj=gz) as tf,
    ):
        member = next(m for m in tf.getmembers() if m.name.endswith("control.tar.gz"))
        raw = tf.extractfile(member).read()
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz, tarfile.open(fileobj=gz) as tf:
        text = {
            m.name.removeprefix("./"): tf.extractfile(m).read()
            for m in tf.getmembers()
            if m.isfile()
        }
    assert b"Installed-Size: 2\n" in text["control"]
    assert text["conffiles"] == b"/etc/config/p\n"


def test_package_files_live_with_the_package():
    root = Path(__file__).parents[1]
    assert not (root / "files").exists()
    for recipe in (root / "pkg").glob("*/pack.py"):
        for name in re.findall(r'FILES / "([^"]+)"', recipe.read_text()):
            assert (recipe.parent / "files" / name).is_file()


def test_main_skips_packages_that_failed(monkeypatch, tmp_path):
    names = [name for name, _mod in pack.load_recipes()]
    (tmp_path / "failed").write_text("\n".join([*names, "ca-certificates"]) + "\n")
    monkeypatch.setattr(pack, "WORK", tmp_path)
    monkeypatch.setattr(pack, "OUT", tmp_path / "out")
    pack.main()
    assert list((tmp_path / "out").glob("*.ipk")) == []


def test_so_accepts_a_known_good_shared_object():
    path = Path(__file__).parent / "fixtures" / "libt.so"
    data = pack.so(path, "libt.so", {"libc.so"}, [], {("foo", "")}, undef_allow=set())
    assert data[:4] == b"\x7fELF"
    assert pack._dyn(path)["soname"] == "libt.so"


def _fake_dyn(**overrides):
    info = {
        "data": b"\x7fELF",
        "e_flags": 0x1005,
        "needed": ["libc.so"],
        "soname": "libt.so",
        "verdef": [],
        "exports": {("foo", "")},
        "undef": [],
        "tags": {0x6FFFFFFB: 1},
        "fp_abi": 1,
        "stack_x": False,
    }
    info.update(overrides)
    return info


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"soname": "wrong.so"}, "SONAME"),
        ({"needed": ["libc.so", "libextra.so"]}, "NEEDED"),
        ({"exports": set()}, "missing exports"),
        ({"undef": [("__clock_gettime64", "libc.so", "")]}, "time64"),
        ({"needed": ["libfoo.so"]}, "libc.so"),
        ({"tags": {0x6FFFFFFB: 1, 15: 1}}, "RPATH"),
        ({"tags": {0x6FFFFFFB: 1, 22: 1}}, "TEXTREL"),
        ({"tags": {0x6FFFFFFB: 0}}, "NOW"),
        ({"stack_x": True}, "PT_GNU_STACK"),
        ({"fp_abi": 3}, "fp_abi"),
        ({"verdef": ["OPENSSL_1_1_0"]}, "verdefs"),
        ({"undef": [("mystery", "libx.so", "")]}, "unresolved"),
    ],
)
def test_so_rejects_a_bad_shared_object(tmp_path, monkeypatch, overrides, match):
    monkeypatch.setattr(pack, "_dyn", lambda path: _fake_dyn(**overrides))
    allow = {"__clock_gettime64"} if "time64" in match else set()
    with pytest.raises(SystemExit, match=match):
        pack.so(
            tmp_path / "x",
            "libt.so",
            {"libc.so"},
            [],
            {("foo", "")},
            undef_allow=allow,
        )


def test_load_exports_and_names(tmp_path):
    path = tmp_path / "e"
    path.write_text("foo\tOPENSSL_1_1_0\nbar\t\n")
    assert pack.load_exports(path) == {("foo", "OPENSSL_1_1_0"), ("bar", "")}
    assert pack.load_names(path) == {"foo", "bar"}


def test_exe_accepts_a_dynamic_mips_binary(tmp_path, monkeypatch):
    path = tmp_path / "openssl"
    path.write_bytes(b"\x7fELF")
    monkeypatch.setattr(
        pack,
        "_dyn",
        lambda path, shared=True: _fake_dyn(
            needed=["libc.so", "libssl.so.1.1", "libcrypto.so.1.1"],
            tags={0x6FFFFFFB: 1, 0x70000011: 10, 0x70000013: 10},
        ),
    )
    assert (
        pack.exe(
            path,
            {"libc.so", "libgcc_s.so.1", "libssl.so.1.1", "libcrypto.so.1.1"},
        )
        == b"\x7fELF"
    )


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"needed": ["libc.so", "libextra.so"]}, "NEEDED"),
        ({"needed": ["libfoo.so"]}, "libc.so"),
        ({"tags": {0x6FFFFFFB: 1, 15: 1}}, "RPATH"),
        ({"stack_x": True}, "PT_GNU_STACK"),
        ({"fp_abi": 3}, "fp_abi"),
        ({"tags": {0x6FFFFFFB: 1, 0x70000013: 1}}, "global GOT"),
        ({"data": b"\x7fELF clock_gettime64"}, "time64"),
    ],
)
def test_exe_rejects_a_bad_binary(tmp_path, monkeypatch, overrides, match):
    monkeypatch.setattr(pack, "_dyn", lambda path, shared=True: _fake_dyn(**overrides))
    with pytest.raises(SystemExit, match=match):
        pack.exe(tmp_path / "x", {"libc.so", "libgcc_s.so.1"})


def test_exe_requires_libgcc_when_the_caller_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(pack, "_dyn", lambda path, shared=True: _fake_dyn())
    with pytest.raises(SystemExit, match="libgcc_s.so.1"):
        pack.exe(
            tmp_path / "x",
            {"libc.so", "libgcc_s.so.1"},
            needed_required=("libgcc_s.so.1",),
        )
