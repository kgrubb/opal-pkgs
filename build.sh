#!/bin/sh
# Build every package pinned in ./versions into out/.
set -eu
cd "$(dirname "$0")"
ROOT=$(pwd)
CACHE=$ROOT/.cache
WORK=$ROOT/work
JOBS=$(getconf _NPROCESSORS_ONLN)
mkdir -p "$CACHE" "$WORK"

field() { awk -F '\t' -v n="$1" -v f="$2" '$1 == n { print $f }' versions; }
ver() { field "$1" 2; }

# Download a pinned source once, verify it, and print its path.
# A partial file is removed. The next call downloads it again.
src() {
  url=$(field "$1" 5 | sed "s/{v}/$(ver "$1")/g")
  file=$CACHE/${url##*/}
  sum=$(field "$1" 4)
  if [ -f "$file" ]; then
    echo "$sum  $file" | shasum -a 256 -c - >&2 || rm -f "$file"
  fi
  if [ ! -f "$file" ]; then
    tmp=$(mktemp "$CACHE/.partial.XXXXXX")
    if ! curl -fsSL --retry 3 -o "$tmp" "$url"; then
      rm -f "$tmp"
      return 1
    fi
    if ! echo "$sum  $tmp" | shasum -a 256 -c - >&2; then
      rm -f "$tmp"
      return 1
    fi
    mv "$tmp" "$file"
  fi
  echo "$file"
}

# Extract a pinned tarball into work/<name>-<version> once.
# The directory appears only after tar finishes, so a killed extract is not reused.
unpack() {
  dir=$WORK/$1-$(ver "$1")
  if [ -d "$dir" ]; then
    return 0
  fi
  file=$(src "$1")
  stage=$(mktemp -d "$WORK/.partial.XXXXXX")
  if ! tar -xf "$file" -C "$stage" --strip-components=1; then
    rm -rf "$stage"
    return 1
  fi
  mv "$stage" "$dir"
}

# A failed package is recorded and its pin put back, so the others still publish.
fail() {
  printf '%s\n' "$1" >> "$WORK/failed"
  echo "build failed: $1" >&2
  base=${VERSIONS_BASE:-}
  if [ -f "$base" ]; then
    awk -F '\t' -v n="$1" -f "$ROOT/restore.awk" "$base" versions > "$WORK/versions.new" && mv "$WORK/versions.new" versions
  fi
}

# Do not call this from if or ||. That turns set -e off inside the recipe.
run_pkg() {
  name=$1
  script=$2
  set +e
  (
    set -e
    . "$script"
  )
  status=$?
  set -e
  [ "$status" -eq 0 ] || fail "$name"
  # ca-certificates is the same download as ca-bundle.
  [ "$status" -eq 0 ] || [ "$name" != ca-bundle ] || fail ca-certificates
}

if [ "${1:-}" = "--test-runner" ]; then
  WORK=$(mktemp -d)
  : > "$WORK/failed"
  run_pkg probe "$2"
  cat "$WORK/failed"
  rm -rf "$WORK"
  exit 0
fi

case $(uname -sm) in
  "Linux x86_64") zig=zig-x86_64-linux ;;
  "Darwin arm64") zig=zig-aarch64-macos ;;
  *) echo "unsupported build host: $(uname -sm)" >&2; exit 1 ;;
esac
unpack "$zig"
export ZIG="$WORK/$zig-$(ver "$zig")/zig"
export SYSROOT="$WORK/sysroot"
export PATH="$ROOT/bin:$PATH"
# Keep host libraries out of cross builds.
export PKG_CONFIG_LIBDIR=/nonexistent
CC=mipsel-musl-cc

# musl 1.1.20 keeps a 32-bit time_t. Newer musl calls time64 syscalls that Linux 4.14 lacks.
if [ ! -f "$SYSROOT/lib/libc.a" ]; then
  unpack musl
  (
    cd "$WORK/musl-$(ver musl)"
    CC=mipsel-cc ./configure --prefix="$SYSROOT" --target=mipsel --build=mipsel --disable-shared
    make -j"$JOBS" AR=mipsel-linux-musl-ar RANLIB=mipsel-linux-musl-ranlib
    make install
  )
fi
printf '%s\n' '#include <time.h>' 'int time_t_is_32bit[1/(sizeof(time_t)==4)];' > "$WORK/time_t.c"
$CC -c -o "$WORK/time_t.o" "$WORK/time_t.c"

: > "$WORK/failed"
# pkg/<pin>/build.sh is one package. Libraries it links are unpacked from versions inside that file.
for script in "$ROOT"/pkg/*/build.sh; do
  run_pkg "$(basename "$(dirname "$script")")" "$script"
done

python3 pack.py || fail pack
if [ -s "$WORK/failed" ] && [ ! -f "${VERSIONS_BASE:-}" ]; then
  exit 1
fi
