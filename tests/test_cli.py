from pathlib import Path

import pytest

from opal_pkgs import build, cli, index, pack, update

ROOT = Path(__file__).parents[1]


@pytest.fixture
def routed(monkeypatch):
    seen = []
    monkeypatch.setattr(
        build, "build", lambda **kwargs: seen.append(("build", kwargs["versions_base"]))
    )
    monkeypatch.setattr(build, "src", lambda name: seen.append(("src", name)))
    monkeypatch.setattr(build, "unpack", lambda name: seen.append(("unpack", name)))
    monkeypatch.setattr(build, "version", lambda name: seen.append(("ver", name)))
    monkeypatch.setattr(pack, "main", lambda: seen.append(("pack", None)))
    monkeypatch.setattr(update, "main", lambda: seen.append(("update", None)))
    monkeypatch.setattr(index, "write_index", lambda feed: seen.append(("index", feed)))
    return seen


@pytest.mark.parametrize(
    ("argv", "called"),
    [
        (["build"], ("build", "")),
        (["build", "src", "dropbear"], ("src", "dropbear")),
        (["build", "unpack", "dropbear"], ("unpack", "dropbear")),
        (["build", "ver", "dropbear"], ("ver", "dropbear")),
        (["pack"], ("pack", None)),
        (["update"], ("update", None)),
        (["index", "feed"], ("index", "feed")),
    ],
)
def test_cli_routes_each_command(routed, argv, called):
    cli.main(argv)
    assert routed == [called]


@pytest.mark.parametrize("argv", [[], ["build", "nope"], ["index"]])
def test_cli_rejects_incomplete_commands(argv):
    with pytest.raises(SystemExit):
        cli.main(argv)


def test_src_and_ver_print_and_unpack_does_not(capsys, monkeypatch):
    monkeypatch.setattr(build, "src", lambda name: Path("/cache/dropbear.tar.bz2"))
    monkeypatch.setattr(build, "unpack", lambda name: Path("/work/dropbear"))
    cli.main(["build", "src", "dropbear"])
    cli.main(["build", "unpack", "dropbear"])
    cli.main(["build", "ver", "dropbear"])
    pinned = next(
        line.split("\t")[1]
        for line in (ROOT / "versions").read_text().splitlines()
        if line.startswith("dropbear\t")
    )
    assert capsys.readouterr().out.splitlines() == ["/cache/dropbear.tar.bz2", pinned]


def test_build_passes_versions_base(monkeypatch):
    seen = []
    monkeypatch.setattr(
        build, "build", lambda **kwargs: seen.append(kwargs["versions_base"])
    )
    monkeypatch.setenv("VERSIONS_BASE", "/tmp/versions.base")
    cli.main(["build"])
    assert seen == ["/tmp/versions.base"]
