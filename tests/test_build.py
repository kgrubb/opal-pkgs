import hashlib
import io
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from opal_pkgs import build, pack

ROOT = Path(__file__).parents[1]


def archive(name, payload):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo(f"top/{name}")
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def pin(root, name, version, digest, url):
    path = root / "versions"
    line = f"{name}\t{version}\t1\t{digest}\t{url}\n"
    path.write_text(path.read_text() + line if path.exists() else line)


def pin_bytes(root, name, version, blob, url):
    pin(root, name, version, hashlib.sha256(blob).hexdigest(), url)


def sysroot(root):
    path = root / "work" / "sysroot"
    (path / "lib").mkdir(parents=True)
    (path / "lib" / "libc.a").write_bytes(b"have")
    return path


def ready_zig(root):
    blob = archive("zig", b"compiler")
    pin_bytes(
        root, "zig-x86_64-linux", "0.14.1", blob, "https://example.test/zig-{v}.tar"
    )
    sysroot(root)
    return blob


def fetch_of(blob):
    def fetch(url, dest):
        Path(dest).write_bytes(blob)

    return fetch


def ok(argv, cwd=None, env=None, **kwargs):
    return subprocess.CompletedProcess(argv, 0)


def test_restore_puts_one_pin_back():
    base = "dropbear\t1.0\t1\told\thttps://example.test/a\nsudo\t9.0\t1\told\thttps://example.test/b\n"
    current = "dropbear\t2.0\t1\tnew\thttps://example.test/a\nsudo\t9.1\t1\tnew\thttps://example.test/b\n"
    assert build.restore(base, current, "dropbear") == (
        "dropbear\t1.0\t1\told\thttps://example.test/a\nsudo\t9.1\t1\tnew\thttps://example.test/b\n"
    )


def test_src_verifies_caches_and_retries(tmp_path):
    blob = b"source"
    digest = hashlib.sha256(blob).hexdigest()
    pin(tmp_path, "demo", "1", digest, "https://example.test/demo-{v}.tar")
    calls = []

    def fetch(url, dest):
        calls.append(url)
        if len(calls) == 1:
            raise OSError("reset")
        Path(dest).write_bytes(blob)

    path = build.src("demo", tmp_path, fetch)
    assert path.read_bytes() == blob
    assert calls == [
        "https://example.test/demo-1.tar",
        "https://example.test/demo-1.tar",
    ]
    assert list((tmp_path / ".cache").glob(".partial.*")) == []
    assert build.src("demo", tmp_path, fetch) == path
    assert len(calls) == 2

    (tmp_path / ".cache" / "demo-1.tar").write_bytes(b"stale")
    assert build.src("demo", tmp_path, fetch).read_bytes() == blob


def test_src_refuses_a_non_https_url(tmp_path):
    pin(tmp_path, "bad", "1", "00", "http://example.test/bad-{v}.tar")
    with pytest.raises(SystemExit, match="non-HTTPS"):
        build.src("bad", tmp_path, fetch_of(b"nope"))


def test_src_rejects_a_hash_mismatch_and_leaves_no_partial(tmp_path):
    pin(tmp_path, "mismatch", "1", "00", "https://example.test/mismatch-{v}.tar")
    with pytest.raises(SystemExit, match="SHA-256"):
        build.src("mismatch", tmp_path, fetch_of(b"nope"))
    assert list((tmp_path / ".cache").glob(".partial.*")) == []


def test_fetch_url_writes_the_response_body(monkeypatch, tmp_path):
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def urlopen(request, timeout):
        assert request.get_header("User-agent") == "opal-pkgs"
        assert timeout == 120
        return Response(b"body")

    monkeypatch.setattr(build.urllib.request, "urlopen", urlopen)
    dest = tmp_path / "file"
    build.fetch_url("https://example.test/file", dest)
    assert dest.read_bytes() == b"body"
    with pytest.raises(SystemExit, match="non-HTTPS"):
        build.fetch_url("http://example.test/file", dest)


def test_src_gives_up_after_three_download_errors(tmp_path):
    pin(tmp_path, "demo", "1", "ab", "https://example.test/demo-{v}.tar")

    def fetch(url, dest):
        raise OSError("down")

    with pytest.raises(SystemExit, match="download failed"):
        build.src("demo", tmp_path, fetch)
    assert list((tmp_path / ".cache").glob(".partial.*")) == []


def test_unpack_strips_the_top_directory_and_keeps_it(tmp_path):
    blob = archive("zig", b"compiler")
    pin_bytes(
        tmp_path, "zig-x86_64-linux", "0.14.1", blob, "https://example.test/zig-{v}.tar"
    )
    dest = build.unpack("zig-x86_64-linux", tmp_path, fetch_of(blob))
    assert (dest / "zig").read_bytes() == b"compiler"
    assert build.unpack("zig-x86_64-linux", tmp_path, fetch_of(b"unused")) == dest


def test_failed_extract_leaves_no_directory(tmp_path):
    blob = b"not a tar"
    pin_bytes(tmp_path, "demo", "1", blob, "https://example.test/demo-{v}.tar")
    with pytest.raises(SystemExit, match="extract failed"):
        build.unpack("demo", tmp_path, fetch_of(blob))
    assert list((tmp_path / "work").iterdir()) == []


def test_a_passing_recipe_prints_one_line(tmp_path, capfd):
    script = tmp_path / "ok.sh"
    script.write_text("echo configure noise\n")
    status = build.run_pkg("demo", script, tmp_path, os.environ.copy())
    out, err = capfd.readouterr()
    assert status == 0
    assert out.splitlines() == ["built demo"]
    assert err == ""


def test_recipe_stops_after_a_failing_command(tmp_path, capfd):
    script = tmp_path / "bad.sh"
    script.write_text("echo start\nfalse\necho survived\n")
    status = build.run_pkg("probe", script, tmp_path, os.environ.copy())
    out, err = capfd.readouterr()
    assert status != 0
    assert out.splitlines() == ["start"]
    assert "survived" not in out and "survived" not in err
    assert (tmp_path / "work" / "failed").read_text().splitlines() == ["probe"]
    assert "build failed: probe" in err


def test_ca_bundle_failure_also_fails_ca_certificates(tmp_path):
    script = tmp_path / "bad.sh"
    script.write_text("exit 1\n")
    base = tmp_path / "base"
    base.write_text(
        "ca-bundle\t1\t4\told\thttps://example.test/a\n"
        "ca-certificates\t1\t2\told\thttps://example.test/a\n"
        "sudo\t9\t1\told\thttps://example.test/b\n"
    )
    (tmp_path / "versions").write_text(
        "ca-bundle\t2\t1\tnew\thttps://example.test/a\n"
        "ca-certificates\t2\t1\tnew\thttps://example.test/a\n"
        "sudo\t9.1\t1\tnew\thttps://example.test/b\n"
    )
    env = os.environ.copy()
    env["VERSIONS_BASE"] = str(base)
    build.run_pkg("ca-bundle", script, tmp_path, env)
    assert (tmp_path / "work" / "failed").read_text().splitlines() == [
        "ca-bundle",
        "ca-certificates",
    ]
    rows = {
        line.split("\t")[0]: line.split("\t")[1]
        for line in (tmp_path / "versions").read_text().splitlines()
    }
    assert rows == {"ca-bundle": "1", "ca-certificates": "1", "sudo": "9.1"}


def test_package_scripts_are_not_wrapped_in_an_if():
    for path in (ROOT / "pkg").glob("*/build.sh"):
        assert "if ! (" not in path.read_text()


@pytest.mark.parametrize(
    ("uname", "zig"),
    [
        ("Linux x86_64", "zig-x86_64-linux"),
        ("Darwin arm64", "zig-aarch64-macos"),
    ],
)
def test_zig_name_for_a_supported_host(uname, zig):
    assert build.zig_name(uname) == zig


def test_this_machine_has_a_supported_zig():
    assert build.zig_name(build.host_uname())


def test_zig_name_rejects_an_unknown_host():
    with pytest.raises(SystemExit, match="unsupported build host: Linux aarch64"):
        build.zig_name("Linux aarch64")


def test_musl_is_configured_for_a_32_bit_sysroot_and_skipped_when_present(tmp_path):
    blob = archive("libc", b"a")
    pin_bytes(tmp_path, "musl", "1.1.20", blob, "https://example.test/musl-{v}.tar.gz")
    root = sysroot(tmp_path)
    calls = []

    def run(argv, cwd=None, env=None, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    env = {"SYSROOT": str(root), "CC": "mipsel-musl-cc", "PATH": os.environ["PATH"]}
    build.ensure_musl(tmp_path, 4, env, run=run, fetch=fetch_of(blob))
    assert calls == []

    (root / "lib" / "libc.a").unlink()
    build.ensure_musl(tmp_path, 4, env, run=run, fetch=fetch_of(blob))
    musl = tmp_path / "work" / "musl-1.1.20"
    assert calls[0] == [
        "./configure",
        f"--prefix={root}",
        "--target=mipsel",
        "--build=mipsel",
        "--disable-shared",
    ]
    assert calls[1] == [
        "make",
        "-j4",
        "AR=mipsel-linux-musl-ar",
        "RANLIB=mipsel-linux-musl-ranlib",
    ]
    assert calls[2] == ["make", "install"]

    def fail(argv, cwd=None, env=None, **kwargs):
        assert env["CC"] == "mipsel-cc"
        assert cwd == musl
        return subprocess.CompletedProcess(argv, 1)

    with pytest.raises(SystemExit, match="musl: ./configure"):
        build.ensure_musl(tmp_path, 4, env, run=fail, fetch=fetch_of(blob))


def test_libc_stub_is_built_once_and_skipped_when_present(tmp_path):
    env = {
        "SYSROOT_SO": str(tmp_path / "sysroot-so"),
        "PATH": os.environ["PATH"],
        "ZIG": "/zig",
    }
    calls = []

    def run(argv, cwd=None, env=None, **kwargs):
        calls.append(argv)
        Path(argv[argv.index("-o") + 1]).write_bytes(b"stub")
        return subprocess.CompletedProcess(argv, 0)

    build.ensure_libc_stub(tmp_path, env, run=run)
    assert calls[0][:3] == ["mipsel-cc", "-shared", "-nostdlib"]
    assert "-Wl,-soname,libc.so" in calls[0]
    assert (tmp_path / "sysroot-so" / "lib" / "libc.so").is_file()
    build.ensure_libc_stub(tmp_path, env, run=run)
    assert len(calls) == 1

    def fail(argv, cwd=None, env=None, **kwargs):
        return subprocess.CompletedProcess(argv, 1)

    (tmp_path / "sysroot-so" / "lib" / "libc.so").unlink()
    with pytest.raises(SystemExit, match="libc.so stub"):
        build.ensure_libc_stub(tmp_path, env, run=fail)


def test_time_t_check_compiles_the_32_bit_assertion(tmp_path):
    seen = []
    env = {"PATH": str(tmp_path / "bin"), "ZIG": "/zig", "SYSROOT": "/sysroot"}

    def run(argv, cwd=None, env=None, **kwargs):
        seen.append((argv, env))
        assert Path(argv[-1]).read_text() == build.TIME_T_C
        return subprocess.CompletedProcess(argv, 0)

    build.check_time_t("mipsel-musl-cc", tmp_path, env, run=run)
    assert seen[0][0][0] == "mipsel-musl-cc"
    assert seen[0][0][1:3] == ["-c", "-o"]
    assert seen[0][1] is env

    def reject(argv, cwd=None, env=None, **kwargs):
        return subprocess.CompletedProcess(argv, 1)

    with pytest.raises(SystemExit, match="32-bit"):
        build.check_time_t("mipsel-musl-cc", tmp_path, env, run=reject)


def test_build_compiles_packages_after_the_toolchain(tmp_path, monkeypatch):
    blob = ready_zig(tmp_path)
    pkg = tmp_path / "pkg" / "demo"
    pkg.mkdir(parents=True)
    (pkg / "build.sh").write_text('echo "$JOBS" > "$WORK/jobs"\n')
    monkeypatch.setattr(pack, "main", lambda: None)
    calls = []

    def run(argv, cwd=None, env=None, **kwargs):
        calls.append((argv, env))
        return subprocess.CompletedProcess(argv, 0)

    build.build(tmp_path, uname="Linux x86_64", jobs=2, run=run, fetch=fetch_of(blob))
    assert (tmp_path / "work" / "jobs").read_text().strip() == "2"
    assert calls[0][0][0] == "mipsel-musl-cc"
    assert str(tmp_path / "bin") in calls[0][1]["PATH"].split(os.pathsep)
    assert (tmp_path / "work" / "failed").read_text() == ""


def test_a_failed_package_stops_a_push_and_not_a_monday_run(tmp_path, monkeypatch):
    blob = ready_zig(tmp_path)
    pkg = tmp_path / "pkg" / "demo"
    pkg.mkdir(parents=True)
    (pkg / "build.sh").write_text("exit 1\n")
    monkeypatch.setattr(pack, "main", lambda: None)

    with pytest.raises(SystemExit):
        build.build(
            tmp_path, uname="Linux x86_64", jobs=1, run=ok, fetch=fetch_of(blob)
        )
    assert (tmp_path / "work" / "failed").read_text().splitlines() == ["demo"]

    base = tmp_path / "base"
    base.write_text((tmp_path / "versions").read_text())
    build.build(
        tmp_path,
        uname="Linux x86_64",
        jobs=1,
        run=ok,
        fetch=fetch_of(blob),
        versions_base=str(base),
    )


def test_pack_failure_is_recorded(tmp_path, monkeypatch):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "work").mkdir()

    def boom():
        raise SystemExit("pack broke")

    monkeypatch.setattr(pack, "main", boom)
    with pytest.raises(SystemExit):
        build.compile_packages(tmp_path, {})
    assert (tmp_path / "work" / "failed").read_text().splitlines() == ["pack"]
