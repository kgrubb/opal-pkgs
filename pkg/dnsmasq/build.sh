# Same compile options as the stock dnsmasq-full: ubus, conntrack, ipset, and DNSSEC through nettle's mini-gmp.
# libubox and libubus are the commits the router's ubusd runs, so the wire protocol matches.
kinc="-idirafter ${ZIG%/*}/lib/libc/include/any-linux-any -idirafter ${ZIG%/*}/lib/libc/include/mips-linux-any"
deps=$WORK/dnsmasq-deps
for p in nettle libmnl libnfnetlink libnetfilter_conntrack libubox ubus dnsmasq; do unpack "$p"; done
if [ ! -f "$deps/lib/libnetfilter_conntrack.a" ]; then
  (
    cd "$WORK/nettle-$(ver nettle)"
    CFLAGS="-Os" ./configure --host=mipsel-linux-musl CC=$CC --prefix="$deps" --libdir="$deps/lib" \
      --disable-shared --enable-mini-gmp --disable-documentation --disable-openssl &&
    make -j"$JOBS" install
  ) || exit 1
  for p in libmnl libnfnetlink libnetfilter_conntrack; do
    (
      cd "$WORK/$p-$(ver "$p")"
      CFLAGS="-Os $kinc" LIBMNL_CFLAGS="-I$deps/include" LIBMNL_LIBS="-L$deps/lib -lmnl" \
        LIBNFNETLINK_CFLAGS="-I$deps/include" LIBNFNETLINK_LIBS="-L$deps/lib -lnfnetlink" \
        ./configure --host=mipsel-linux-musl CC=$CC --prefix="$deps" --disable-shared --enable-static &&
      make -j"$JOBS" install
    ) || exit 1
  done
fi
if [ ! -f "$deps/lib/libubus.a" ]; then
  mkdir -p "$deps/include/libubox"
  (
    cd "$WORK/libubox-$(ver libubox)"
    for f in avl avl-cmp blob blobmsg uloop usock ustream ustream-fd vlist utils safe_list runqueue md5 kvlist ulog base64; do
      $CC -Os -I. $kinc -c -o "$f.o" "$f.c" || exit 1
    done
    cp ./*.h "$deps/include/libubox/" && mipsel-linux-musl-ar rcs "$deps/lib/libubox.a" ./*.o
  ) || exit 1
  (
    cd "$WORK/ubus-$(ver ubus)"
    for f in libubus libubus-io libubus-obj libubus-sub libubus-req libubus-acl; do
      $CC -Os -I. -I"$deps/include" $kinc -DUBUS_UNIX_SOCKET='"/var/run/ubus.sock"' -DUBUS_MAX_MSGLEN=1048576 \
        -c -o "$f.o" "$f.c" || exit 1
    done
    cp libubus.h ubusmsg.h ubus_common.h "$deps/include/" && mipsel-linux-musl-ar rcs "$deps/lib/libubus.a" ./*.o
  ) || exit 1
fi
cd "$WORK/dnsmasq-$(ver dnsmasq)"
if [ ! -x src/dnsmasq ]; then
  make -j"$JOBS" CC=$CC COPTS="-DHAVE_UBUS -DHAVE_CONNTRACK -DHAVE_DNSSEC -DNO_GMP -DNO_ID" \
    CFLAGS="-Os -I$deps/include $kinc" LDFLAGS="-L$deps/lib" \
    ubus_libs="-lubus -lubox" ct_cflags= ct_libs="-lnetfilter_conntrack -lnfnetlink -lmnl" \
    nettle_cflags= nettle_libs="-lhogweed -lnettle" gmp_libs=
fi
