# Go 1.27 keeps 32-bit time syscalls on Linux before 5.1. The Opal kernel is 4.14.
# SF19A28 reports FPU V0.0, so hardfloat SIGILLs.
# This compiler stays on the build machine. The ipk is only the static binary.
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)
    go_host=linux-amd64
    go_sha=65efbc80fdc1fa2cd2631cad5b481777a68e8725f34e89f50fc6ac714e379b40
    ;;
  Darwin-arm64)
    go_host=darwin-arm64
    go_sha=dd3908cf20959d798c1e06ebe5b72213f0505ce01373b40ce3110975a6cd99c2
    ;;
  *)
    echo "tailscale: no Go toolchain for $(uname -s)-$(uname -m)" >&2
    exit 1
    ;;
esac
go_ver=1.27.3
go="$WORK/go-$go_ver-$go_host/bin/go"
if [ ! -x "$go" ]; then
  mkdir -p "$ROOT/.cache"
  archive="$ROOT/.cache/go$go_ver.$go_host.tar.gz"
  if [ ! -f "$archive" ]; then
    tmp=$(mktemp "$ROOT/.cache/.partial.XXXXXX")
    curl -fsSL --retry 3 -o "$tmp" "https://go.dev/dl/go$go_ver.$go_host.tar.gz" || {
      rm -f "$tmp"
      exit 1
    }
    mv "$tmp" "$archive"
  fi
  got=$(openssl dgst -sha256 "$archive" | awk '{print $NF}')
  if [ "$got" != "$go_sha" ]; then
    rm -f "$archive"
    echo "tailscale: Go $go_ver SHA-256 mismatch" >&2
    exit 1
  fi
  mkdir -p "$WORK/go-$go_ver-$go_host"
  tar -xf "$archive" -C "$WORK/go-$go_ver-$go_host" --strip-components=1
fi
unpack tailscale
cd "$WORK/tailscale-$(ver tailscale)"
if [ ! -x tailscaled ]; then
  export GOTOOLCHAIN=local CGO_ENABLED=0
  tags=$(GOOS= GOARCH= "$go" run ./cmd/featuretags --min --add=cli,ipnbus,osrouter,advertiseroutes,nattraversal,portmapper,iptables,useroutes,dns)
  # An unknown name is not omitted, so the omit check cannot see a rename.
  known=$(GOOS= GOARCH= "$go" run ./cmd/featuretags --list)
  for need in cli ipnbus osrouter advertiseroutes nattraversal portmapper iptables useroutes dns; do
    printf '%s\n' "$known" | grep -q "^ *$need:" || {
      echo "tailscale: featuretags has no $need" >&2
      exit 1
    }
  done
  case ",$tags," in
    *,ts_include_cli,*) ;;
    *)
      echo "tailscale: build tags left out the cli" >&2
      exit 1
      ;;
  esac
  for gone in ipnbus osrouter advertiseroutes nattraversal portmapper iptables useroutes dns; do
    case ",$tags," in
      *",ts_omit_$gone,"*)
        echo "tailscale: build tags omitted $gone" >&2
        exit 1
        ;;
    esac
  done
  # One binary. argv[0] selects tailscaled or the cli.
  GOOS=linux GOARCH=mipsle GOMIPS=softfloat \
    "$go" build -o tailscaled -trimpath -tags "$tags" \
    -ldflags "-s -w -X tailscale.com/version.shortStamp=$(ver tailscale) -X tailscale.com/version.longStamp=$(ver tailscale)" \
    ./cmd/tailscaled
fi
