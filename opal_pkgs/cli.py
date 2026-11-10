import argparse
import os


def main(argv=None):
    parser = argparse.ArgumentParser(prog="opal-pkgs")
    commands = parser.add_subparsers(dest="command", required=True)

    build_cmd = commands.add_parser("build", help="download, unpack, and compile")
    actions = build_cmd.add_subparsers(dest="action")
    for action in ("src", "unpack", "ver"):
        command = actions.add_parser(action, help=f"run the {action} helper")
        command.add_argument("name")

    commands.add_parser("pack", help="pack the built trees into ipks")
    commands.add_parser("update", help="bump versions to the newest signed release")
    index_cmd = commands.add_parser(
        "index", help="write Packages, Packages.gz, and index.html"
    )
    index_cmd.add_argument("feed")

    args = parser.parse_args(argv)
    if args.command == "build":
        from . import build

        if args.action == "src":
            print(build.src(args.name))
        elif args.action == "unpack":
            build.unpack(args.name)
        elif args.action == "ver":
            print(build.version(args.name))
        else:
            build.build(
                versions_base=os.environ.get("VERSIONS_BASE", ""),
                base=os.environ.get("BUILD_BASE", ""),
            )
    elif args.command == "pack":
        from . import pack

        pack.main()
    elif args.command == "update":
        from . import update

        update.main()
    else:
        from . import index

        index.write_index(args.feed)


if __name__ == "__main__":
    main()
