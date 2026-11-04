# libpcap is linked into softflowd. The router's libpcap package stays.
if ! command -v autoreconf >/dev/null || ! command -v flex >/dev/null || ! command -v bison >/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq autoconf automake flex bison
fi
kinc="-idirafter ${ZIG%/*}/lib/libc/include/any-linux-any -idirafter ${ZIG%/*}/lib/libc/include/mips-linux-any"
unpack libpcap
unpack softflowd
pcap=$WORK/libpcap-$(ver libpcap)
if [ ! -f "$pcap/libpcap.a" ]; then
  (
    cd "$pcap"
    CFLAGS="-Os $kinc" ./configure --host=mipsel-linux-musl --disable-shared --without-libnl --with-pcap=linux CC=$CC
    make -j"$JOBS"
  )
fi
cd "$WORK/softflowd-$(ver softflowd)"
if [ ! -x softflowd ]; then
  autoreconf -fi
  # --host=mipsel-linux-musl does not match the linux-gnu* check, so the interface index code is compiled out.
  CFLAGS="-Os -DLINUX $kinc" CPPFLAGS="-I$pcap" LDFLAGS="-L$pcap" \
    ./configure --host=mipsel-linux-musl CC=$CC
  make -j"$JOBS"
fi
