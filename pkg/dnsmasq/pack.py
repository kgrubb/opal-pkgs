LATEST = ('https://thekelleys.org.uk/dnsmasq/', 'dnsmasq-(\\d+\\.\\d+)\\.tar\\.xz', '.asc')

def pack_pkg():
    if "dnsmasq" not in FAILED:
        pack("dnsmasq-full", "dnsmasq", "mips_siflower", """
    Depends: libc, kmod-ipt-ipset
    Provides: dnsmasq
    Require-User: dnsmasq=453:dnsmasq=453 dnsmasq_vpn=456:dnsmasq=453
    License: GPL-2.0
    Section: net
    Description: Static dnsmasq with DHCP, DNSSEC, ipset, conntrack and ubus for the GL-SFT1200
    """, [
        ("usr/sbin/dnsmasq", elf(tree("dnsmasq") / "src" / "dnsmasq"), 0o755),
        ("etc/init.d/dnsmasq", (FILES / "dnsmasq.init").read_bytes(), 0o755),
        ("etc/config/dhcp", (FILES / "dhcp.config").read_bytes(), 0o600),
        ("etc/dnsmasq.conf", (FILES / "dnsmasq.conf").read_bytes(), 0o600),
        ("etc/hotplug.d/ntp/25-dnsmasqsec", (FILES / "dnsmasq.ntp-hotplug").read_bytes(), 0o600),
        ("lib/netifd/dhcplease", (FILES / "dhcplease").read_bytes(), 0o755),
        ("usr/lib/dnsmasq/dhcp-script.sh", (FILES / "dnsmasq-dhcp-script.sh").read_bytes(), 0o755),
        ("usr/share/acl.d/dnsmasq_acl.json", (FILES / "dnsmasq_acl.json").read_bytes(), 0o644),
        ("usr/share/dnsmasq/dhcpbogushostname.conf", (FILES / "dhcpbogushostname.conf").read_bytes(), 0o600),
        ("usr/share/dnsmasq/rfc6761.conf", (FILES / "rfc6761.conf").read_bytes(), 0o600),
        ("usr/share/dnsmasq/trust-anchors.conf", (tree("dnsmasq") / "trust-anchors.conf").read_bytes(), 0o600),
    ], ["/etc/config/dhcp", "/etc/dnsmasq.conf"])
