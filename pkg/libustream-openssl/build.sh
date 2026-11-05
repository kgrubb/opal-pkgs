# Drop-in /lib/libustream-ssl.so linked to libopenssl 1.1.1w.
# Headers from the same libubox pin dnsmasq uses so the ustream layout matches the router.
unpack libubox
unpack libopenssl
unpack libustream-openssl
ubox=$WORK/libubox-$(ver libubox)
ssl=$WORK/libopenssl-$(ver libopenssl)
src=$WORK/libustream-openssl-$(ver libustream-openssl)
so=$src/libustream-ssl.so
if [ ! -f "$so" ]; then
  # Stub so the link records NEEDED libubox.so; real symbols resolve on the router.
  printf 'void __opal_libubox_stub(void){}\n' >"$src/libubox_stub.c"
  mipsel-musl-so-cc -shared -o "$src/libubox.so" "$src/libubox_stub.c" \
    -Wl,-soname,libubox.so || exit 1
  # Sources include <libubox/ustream.h>; headers live at the libubox tree root.
  mkdir -p "$src/include" && ln -sfn "$ubox" "$src/include/libubox"
  kinc="-idirafter ${ZIG%/*}/lib/libc/include/any-linux-any -idirafter ${ZIG%/*}/lib/libc/include/mips-linux-any"
  for f in ustream-ssl ustream-io-openssl ustream-openssl; do
    mipsel-musl-so-cc -Os -fPIC -I"$src" -I"$src/include" -I"$ssl/include" $kinc \
      -c -o "$src/$f.o" "$src/$f.c" || exit 1
  done
  mipsel-musl-so-cc -shared -o "$so" "$src"/ustream-ssl.o "$src"/ustream-io-openssl.o \
    "$src"/ustream-openssl.o -L"$ssl" -L"$src" -lssl -lcrypto -lubox \
    -Wl,--allow-shlib-undefined -Wl,-soname,libustream-ssl.so || exit 1
fi
