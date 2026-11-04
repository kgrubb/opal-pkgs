# Agent modules and transports match OpenWrt's nossl net-snmp, including its 802.11 MIB.
# dlmod is left out because a static snmpd cannot load modules.
kinc="-idirafter ${ZIG%/*}/lib/libc/include/any-linux-any -idirafter ${ZIG%/*}/lib/libc/include/mips-linux-any"
unpack net-snmp
wifi=$(src net-snmp-wifi-mib)
# The 802.11 MIB uses the BSD list macros, which musl does not ship. Only that one header is borrowed.
mkdir -p "$WORK/compat/sys"
cp "${ZIG%/*}/lib/libc/include/generic-glibc/sys/queue.h" "$WORK/compat/sys/queue.h"
cd "$WORK/net-snmp-$(ver net-snmp)"
if [ ! -x agent/snmpd ]; then
  [ -f agent/mibgroup/ieee802dot11.c ] || patch -p1 < "$wifi" || exit 1
  CFLAGS="-Os $kinc" CPPFLAGS="-idirafter $WORK/compat" ./configure --host=mipsel-linux-musl CC=$CC \
    --prefix=/usr --sysconfdir=/etc --localstatedir=/var \
    --disable-shared --enable-static --enable-mfd-rewrites --enable-ipv6 \
    --with-endianness=little --with-persistent-directory=/usr/lib/snmp/ --with-mnttab=/etc/mtab \
    --with-default-snmp-version=1 --with-sys-contact=root@localhost --with-sys-location=Unknown \
    --disable-applications --disable-manuals --disable-scripts --disable-mibs --disable-mib-loading \
    --disable-debugging --disable-embedded-perl --without-perl-modules --disable-perl-cc-checks \
    --without-openssl --without-libwrap --without-mysql --without-rpm --without-zlib --without-pcre \
    --with-transports="Callback UDP Unix UDPIPv6" --with-out-transports="TCP TCPIPv6" \
    --with-out-mib-modules="agent_mibs disman/event disman/schedule hardware host if-mib ip-mib mibII notification notification-log-mib snmpv3mibs target tcp-mib ucd_snmp udp-mib utilities" \
    --with-mib-modules="agent/extend agentx host/hr_device host/hr_disk host/hr_filesys host/hr_network host/hr_partition host/hr_proc host/hr_storage host/hr_system ieee802dot11 if-mib/ifXTable ip-mib/ipAddressTable ip-mib/inetNetToMediaTable ip-forward-mib/inetCidrRouteTable ip-forward-mib/ipCidrRouteTable mibII/at mibII/icmp mibII/ifTable mibII/ip mibII/snmp_mib mibII/sysORTable mibII/system_mib mibII/tcp mibII/udp mibII/vacm_context mibII/vacm_vars snmpv3/snmpEngine snmpv3/snmpMPDStats snmpv3/usmConf snmpv3/usmStats snmpv3/usmUser tunnel ucd-snmp/disk_hw ucd-snmp/extensible ucd-snmp/loadave ucd-snmp/memory ucd-snmp/pass ucd-snmp/pass_persist ucd-snmp/proc ucd-snmp/vmstat util_funcs utilities/execute" &&
  make -j"$JOBS"
fi
