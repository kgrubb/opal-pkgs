# Paths and user match the stock chrony. libcap is linked in so chronyd still drops root to the chrony user.
unpack libcap
unpack chrony
cap=$WORK/libcap-$(ver libcap)/libcap
if [ ! -f "$cap/libcap.a" ]; then
  # The capability name table is generated with GNU sed syntax. chronyd parses those names to drop root.
  make -C "$cap" CC=$CC BUILD_CC=cc AR=mipsel-linux-musl-ar RANLIB=mipsel-linux-musl-ranlib \
    BUILD_SED="$(command -v gsed || echo sed)" COPTS=-Os GOLANG=no SHARED=no USE_GPERF=no libcap.a || exit 1
  grep -q '^{"cap_chown",0},$' "$cap/cap_names.list.h" || { rm -f "$cap/libcap.a"; exit 1; }
fi
cd "$WORK/chrony-$(ver chrony)"
if [ ! -x chronyd ]; then
  CC=$CC CFLAGS="-Os" CPPFLAGS="-I$cap/include -I$cap/include/uapi" LDFLAGS="-L$cap" ./configure \
    --host-system=Linux --host-release=4.14.90 --host-machine=mips \
    --prefix=/usr --sysconfdir=/etc/chrony --localstatedir=/var --chronyrundir=/var/run/chrony \
    --with-user=chrony --disable-readline --disable-rtc --disable-sechash --disable-nts --without-seccomp &&
  make -j"$JOBS"
fi
