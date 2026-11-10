"""Download, unpack, and run the package recipes. configure and make stay shell."""

import hashlib
import os
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOSTS = {
    "Linux x86_64": "zig-x86_64-linux",
    "Darwin arm64": "zig-aarch64-macos",
}
TIME_T_C = "#include <time.h>\nint time_t_is_32bit[1/(sizeof(time_t)==4)];\n"


def pins(root=ROOT):
    table = {}
    for line in (root / "versions").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        table[cols[0]] = cols
    return table


def version(name, root=ROOT):
    return pins(root)[name][1]


def sha256(path):
    digest = hashlib.sha256()
    digest.update(Path(path).read_bytes())
    return digest.hexdigest()


SHARED = ("bin/", "opal_pkgs/build.py", "opal_pkgs/cli.py", "opal_pkgs/pack.py")


def needs(root, name):
    """Other recipes whose tree this one unpacks, one per line in pkg/<name>/needs."""
    path = root / "pkg" / name / "needs"
    return set(path.read_text().split()) if path.is_file() else set()


def changed(root, base):
    """Recipes whose pkg/ dir or versions row differs from base. Any other change rebuilds all."""
    recipes = {d.name for d in (root / "pkg").iterdir() if d.is_dir()}
    if not base:
        return recipes

    def git(*args):
        argv = ["git", "-C", str(root), *args]
        return subprocess.run(argv, capture_output=True, text=True, check=True).stdout

    try:
        paths = git("diff", "--name-only", base, "--").split()
        rows = git("diff", "-U0", base, "--", "versions").splitlines()
    except subprocess.CalledProcessError:
        return recipes
    names = {
        r[1:].split("\t")[0]
        for r in rows
        if r.startswith(("+", "-")) and not r.startswith(("+++", "---"))
    }
    if names - recipes:
        return recipes
    for path in paths:
        parts = path.split("/")
        if path.startswith(SHARED) or parts[0] == "pkg" and parts[2:3] == ["abi"]:
            return recipes
        if parts[0] == "pkg":
            names.add(parts[1])
    return (names | {r for r in recipes if needs(root, r) & names}) & recipes


def fetch_url(url, dest):
    if not url.startswith("https://"):
        raise SystemExit(f"refusing non-HTTPS URL: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "opal-pkgs"})
    with (
        urllib.request.urlopen(request, timeout=120) as response,
        Path(dest).open("wb") as out,
    ):
        shutil.copyfileobj(response, out)


def src(name, root=ROOT, fetch=fetch_url):
    """A partial download is deleted. The next call tries again."""
    cols = pins(root)[name]
    url = cols[4].replace("{v}", cols[1])
    cache = root / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / url.rsplit("/", 1)[-1]
    digest = cols[3]
    if dest.is_file() and sha256(dest) != digest:
        dest.unlink()
    if dest.is_file():
        return dest
    if not url.startswith("https://"):
        raise SystemExit(f"refusing non-HTTPS URL: {url}")
    error = None
    for _ in range(3):
        fd, raw = tempfile.mkstemp(prefix=".partial.", dir=cache)
        os.close(fd)
        tmp = Path(raw)
        try:
            fetch(url, tmp)
            if sha256(tmp) != digest:
                raise SystemExit(f"{name}: SHA-256 mismatch")
            tmp.replace(dest)
            return dest
        except SystemExit:
            tmp.unlink(missing_ok=True)
            raise
        except OSError as err:
            tmp.unlink(missing_ok=True)
            error = err
    raise SystemExit(f"{name}: download failed: {error}")


def unpack(name, root=ROOT, fetch=fetch_url):
    """The directory appears only after tar finishes, so a failed extract is not reused."""
    work = root / "work"
    work.mkdir(parents=True, exist_ok=True)
    dest = work / f"{name}-{version(name, root)}"
    if dest.is_dir():
        return dest
    archive = src(name, root, fetch)
    stage = Path(tempfile.mkdtemp(prefix=".partial.", dir=work))
    result = subprocess.run(
        ["tar", "-xf", str(archive), "-C", str(stage), "--strip-components=1"],
        check=False,
    )
    if result.returncode != 0:
        shutil.rmtree(stage)
        raise SystemExit(f"{name}: extract failed")
    stage.rename(dest)
    return dest


def restore(base, current, name):
    old = ""
    for line in base.splitlines():
        if line.split("\t", 1)[0] == name:
            old = line
    lines = []
    for line in current.splitlines():
        key = line.split("\t", 1)[0] if line else ""
        lines.append(old if key == name and old else line)
    text = "\n".join(lines)
    if current.endswith("\n") or text:
        text += "\n"
    return text


def fail(name, root, versions_base=""):
    work = root / "work"
    work.mkdir(parents=True, exist_ok=True)
    with (work / "failed").open("a") as handle:
        handle.write(f"{name}\n")
    print(f"build failed: {name}", file=sys.stderr)
    base = Path(versions_base) if versions_base else None
    if base is not None and base.is_file():
        current = root / "versions"
        current.write_text(restore(base.read_text(), current.read_text(), name))


def recipe_command(script):
    py = shlex.quote(sys.executable)
    # set -e applies inside this shell and not to the Python driver.
    # A recipe that exits does not stop the packages after it.
    helpers = [
        f'{name}() {{ {py} -m opal_pkgs.cli build {name} "$1"; }}'
        for name in ("src", "unpack", "ver")
    ]
    return "\n".join(["set -e", *helpers, f". {shlex.quote(str(script))}"])


def show(result):
    for text, dest in ((result.stdout, sys.stdout), (result.stderr, sys.stderr)):
        if text:
            print(text, end="" if text.endswith("\n") else "\n", file=dest)


def run_pkg(name, script, root, env):
    ci = env.get("GITHUB_ACTIONS") == "true"
    print(f"::group::{name}" if ci else f"building {name}", flush=True)
    result = subprocess.run(
        ["sh", "-c", recipe_command(script)], env=env, cwd=root, check=False
    )
    if ci:
        print("::endgroup::", flush=True)
    if result.returncode != 0:
        base = env.get("VERSIONS_BASE", "")
        fail(name, root, base)
        # ca-certificates is the same download as ca-bundle.
        if name == "ca-bundle":
            fail("ca-certificates", root, base)
        return result.returncode
    print(f"built {name}")
    return 0


def zig_name(uname):
    try:
        return HOSTS[uname]
    except KeyError:
        raise SystemExit(f"unsupported build host: {uname}") from None


def host_uname():
    return f"{os.uname().sysname} {os.uname().machine}"


def build_env(root, zig_bin, base=None):
    env = os.environ.copy() if base is None else dict(base)
    env["ZIG"] = str(zig_bin)
    env["SYSROOT"] = str(root / "work" / "sysroot")
    env["SYSROOT_SO"] = str(root / "work" / "sysroot-so")
    env["PATH"] = str(root / "bin") + os.pathsep + env.get("PATH", "")
    env["PKG_CONFIG_LIBDIR"] = "/nonexistent"
    env["CC"] = "mipsel-musl-cc"
    env["ROOT"] = str(root)
    env["WORK"] = str(root / "work")
    return env


def _libc_a_globals(libc_a):
    """Global defined symbol names in a static musl libc.a (funcs, objects)."""
    data = Path(libc_a).read_bytes()
    if data[:8] != b"!<arch>\n":
        return set(), set()
    funcs, objs, off = set(), set(), 8
    while off + 60 <= len(data):
        hdr = data[off : off + 60]
        if hdr[:1] == b"\n":
            off += 1
            continue
        try:
            size = int(hdr[48:58])
        except ValueError:
            break
        body_off = off + 60
        body = data[body_off : body_off + size]
        off = body_off + size + (size & 1)
        if body[:4] != b"\x7fELF":
            continue
        e_shoff = struct.unpack_from("<I", body, 32)[0]
        e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", body, 46)

        def sh(i, _b=body, _o=e_shoff, _e=e_shentsize):
            return struct.unpack_from("<IIIIIIIIII", _b, _o + i * _e)

        strbase = sh(e_shstrndx)[4]
        symtab = strtab = None
        for i in range(e_shnum):
            s = sh(i)
            name = body[strbase + s[0] :].split(b"\0", 1)[0]
            if name == b".symtab":
                symtab = s
            elif name == b".strtab":
                strtab = s
        if not symtab or not strtab:
            continue
        stro = strtab[4]
        for i in range(symtab[5] // 16):
            st_name, _v, _sz, st_info, _o, st_shndx = struct.unpack_from(
                "<IIIBBH", body, symtab[4] + i * 16
            )
            bind = st_info >> 4
            if not st_name or st_shndx == 0 or bind not in (1, 2):
                continue
            nm = body[stro + st_name :].split(b"\0", 1)[0].decode()
            if not nm.isidentifier():
                continue
            (funcs if (st_info & 0xF) == 2 else objs).add(nm)
    return funcs, objs


def _libc_stub_source(libc_a):
    """C stubs so exe links resolve against NEEDED libc.so (bodies unused at runtime)."""
    funcs, objs = _libc_a_globals(libc_a)
    lines = ["/* generated from musl libc.a; runtime uses the router's libc.so */"]
    lines.extend(f"void {n}(void) {{}}" for n in sorted(funcs))
    lines.extend(f"char {n}[8];" for n in sorted(objs))
    return "\n".join(lines) + "\n"


def ensure_libc_stub(root, env, run=subprocess.run):
    """libc.so with musl exports so dyn executables link; shared recipes also NEEDED it."""
    stub = Path(env["SYSROOT_SO"]) / "lib" / "libc.so"
    marker = Path(env["SYSROOT_SO"]) / "lib" / "libc.so.imports"
    if stub.is_file() and marker.is_file():
        return
    stub.parent.mkdir(parents=True, exist_ok=True)
    source = stub.parent / "empty.c"
    libc_a = Path(env.get("SYSROOT", "")) / "lib" / "libc.a"
    source.write_text(_libc_stub_source(libc_a) if libc_a.is_file() else "\n")
    child = dict(env)
    child["CC"] = "mipsel-cc"
    result = run(
        [
            "mipsel-cc",
            "-shared",
            "-nostdlib",
            "-Wl,-soname,libc.so",
            "-o",
            str(stub),
            str(source),
        ],
        cwd=stub.parent,
        env=child,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        show(result)
        raise SystemExit("libc.so stub failed")
    marker.write_text("imports\n")
    print("built libc.so stub")


def ensure_libgcc_stub(root, env, run=subprocess.run):
    """SONAME libgcc_s.so.1 so dyn executables load the router's soft-div helpers."""
    stub = Path(env["SYSROOT_SO"]) / "lib" / "libgcc_s.so.1"
    if stub.is_file():
        return
    stub.parent.mkdir(parents=True, exist_ok=True)
    source = stub.parent / "libgcc_stub.c"
    source.write_text("void __opal_libgcc_stub(void) {}\n")
    child = dict(env)
    child["CC"] = "mipsel-cc"
    result = run(
        [
            "mipsel-cc",
            "-shared",
            "-nostdlib",
            "-Wl,-soname,libgcc_s.so.1",
            "-o",
            str(stub),
            str(source),
        ],
        cwd=stub.parent,
        env=child,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        show(result)
        raise SystemExit("libgcc_s.so.1 stub failed")
    print("built libgcc_s.so.1 stub")


def check_time_t(cc, work, env, run=subprocess.run):
    source = work / "time_t.c"
    source.write_text(TIME_T_C)
    result = run(
        [cc, "-c", "-o", str(work / "time_t.o"), str(source)],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        show(result)
        raise SystemExit("time_t is not 32-bit")


def ensure_musl(root, jobs, env, run=subprocess.run, fetch=fetch_url):
    """musl 1.1.20 keeps a 32-bit time_t. Newer musl calls time64 syscalls that Linux 4.14 lacks."""
    sysroot = Path(env["SYSROOT"])
    if (sysroot / "lib" / "libc.a").is_file():
        return
    unpack("musl", root, fetch)
    musl = root / "work" / f"musl-{version('musl', root)}"
    child = dict(env)
    child["CC"] = "mipsel-cc"
    commands = [
        [
            "./configure",
            f"--prefix={sysroot}",
            "--target=mipsel",
            "--build=mipsel",
            "--disable-shared",
        ],
        [
            "make",
            f"-j{jobs}",
            "AR=mipsel-linux-musl-ar",
            "RANLIB=mipsel-linux-musl-ranlib",
        ],
        ["make", "install"],
    ]
    for argv in commands:
        result = run(argv, cwd=musl, env=child, capture_output=True, text=True)
        if result.returncode != 0:
            show(result)
            raise SystemExit(f"musl: {' '.join(argv)} failed")
    print("built musl")


def compile_packages(root, env, only):
    work = root / "work"
    work.mkdir(parents=True, exist_ok=True)
    (work / "failed").write_text("")
    needed = only.union(*(needs(root, n) for n in only))
    for script in sorted((root / "pkg").glob("*/build.sh")):
        if script.parent.name in needed:
            run_pkg(script.parent.name, script, root, env)
    from . import pack

    try:
        pack.main(only)
    except SystemExit as err:
        if err.code not in (0, None):
            fail("pack", root, env.get("VERSIONS_BASE", ""))
    base = env.get("VERSIONS_BASE", "")
    if (work / "failed").stat().st_size and not (base and Path(base).is_file()):
        raise SystemExit(1)


def toolchain(root, uname, jobs, run, fetch):
    (root / ".cache").mkdir(parents=True, exist_ok=True)
    (root / "work").mkdir(parents=True, exist_ok=True)
    zig = zig_name(uname)
    unpack(zig, root, fetch)
    zig_bin = root / "work" / f"{zig}-{version(zig, root)}" / "zig"
    env = build_env(root, zig_bin)
    env["JOBS"] = str(jobs)
    ensure_musl(root, jobs, env, run=run, fetch=fetch)
    check_time_t(env["CC"], root / "work", env, run=run)
    ensure_libc_stub(root, env, run=run)
    ensure_libgcc_stub(root, env, run=run)
    return env


def build(
    root=ROOT,
    uname=None,
    jobs=None,
    run=subprocess.run,
    fetch=fetch_url,
    versions_base="",
    base="",
):
    only = changed(root, base)
    print("changed:", " ".join(sorted(only)) or "none")
    env = {}
    if only:
        env = toolchain(
            root,
            host_uname() if uname is None else uname,
            os.cpu_count() or 1 if jobs is None else jobs,
            run,
            fetch,
        )
    if versions_base:
        env["VERSIONS_BASE"] = versions_base
    compile_packages(root, env, only)
