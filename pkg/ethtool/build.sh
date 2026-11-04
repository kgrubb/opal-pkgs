# Netlink ethtool needs Linux 5.6, so this build uses the ioctl interface.
unpack ethtool
cd "$WORK/ethtool-$(ver ethtool)"
if [ ! -x ethtool ]; then
  ./configure --host=mipsel-linux-musl --disable-netlink CC=$CC CFLAGS="-Os -I$ROOT/kheaders"
  make -j"$JOBS"
fi
