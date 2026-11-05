# Shared libz.so.1 drop-in for the Opal (stock is 1.2.11).
unpack zlib
cd "$WORK/zlib-$(ver zlib)"
if [ ! -f libz.so.1 ]; then
  unset CFLAGS CPPFLAGS LDFLAGS LDLIBS
  # version-script in LDSHARED breaks configure's shared probe (tiny conftest).
  CC=mipsel-musl-so-cc \
    LDSHARED="mipsel-musl-so-cc -shared -Wl,-soname,libz.so.1" \
    CHOST=mipsel-linux \
    ./configure --prefix=/usr --shared || exit 1
  # Our map keeps stock ZLIB_* nodes and hides zig compiler-rt float helpers.
  sed -i.bak "s|^LDSHARED=.*|LDSHARED=mipsel-musl-so-cc -shared -Wl,-soname,libz.so.1,--version-script,$ROOT/pkg/zlib/zlib.map|" Makefile
  make -j"$JOBS" "$(sed -n 's/^SHAREDLIBV=//p' Makefile)" || exit 1
  test -f libz.so.1 || ln -sf "$(sed -n 's/^SHAREDLIBV=//p' Makefile)" libz.so.1
fi
