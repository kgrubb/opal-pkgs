unpack dropbear
cd "$WORK/dropbear-$(ver dropbear)"
if [ ! -x dropbearmulti ]; then
  ./configure --host=mipsel-linux-musl CC=$CC \
    --disable-zlib --disable-pam --disable-lastlog \
    --disable-utmp --disable-utmpx --disable-wtmp --disable-wtmpx \
    --disable-pututline --disable-pututxline
  # CFLAGS stays unset on the make line so libtommath keeps its CFLAGS += -I../src.
  # One multi-call binary, like stock OpenWrt: the ssh and scp alternatives point at it.
  make -j"$JOBS" STATIC=1 MULTI=1 PROGRAMS="dropbear dbclient dropbearkey scp" \
    LDFLAGS="-Wl,-z,now -Wl,-z,relro -Wl,--gc-sections"
fi
