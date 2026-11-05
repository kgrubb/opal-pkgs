"""Download, unpack, and run the package recipes. configure and make stay shell."""

import hashlib
import os
import shlex
import shutil
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
    result = subprocess.run(
        ["sh", "-c", recipe_command(script)],
        env=env,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        show(result)
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
    env["PATH"] = str(root / "bin") + os.pathsep + env.get("PATH", "")
    env["PKG_CONFIG_LIBDIR"] = "/nonexistent"
    env["CC"] = "mipsel-musl-cc"
    env["ROOT"] = str(root)
    env["WORK"] = str(root / "work")
    return env


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


def compile_packages(root, env):
    work = root / "work"
    work.mkdir(parents=True, exist_ok=True)
    (work / "failed").write_text("")
    for script in sorted((root / "pkg").glob("*/build.sh")):
        run_pkg(script.parent.name, script, root, env)
    from . import pack

    try:
        pack.main()
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
    return env


def build(
    root=ROOT,
    uname=None,
    jobs=None,
    run=subprocess.run,
    fetch=fetch_url,
    versions_base="",
):
    env = toolchain(
        root,
        host_uname() if uname is None else uname,
        os.cpu_count() or 1 if jobs is None else jobs,
        run,
        fetch,
    )
    if versions_base:
        env["VERSIONS_BASE"] = versions_base
    compile_packages(root, env)
