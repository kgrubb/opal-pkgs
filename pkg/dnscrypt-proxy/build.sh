unpack dnscrypt-proxy
# Unpinned because the lists change daily. dnscrypt-proxy checks each minisig before use.
lists=$WORK/dnscrypt-lists
mkdir -p "$lists"
for f in public-resolvers.md relays.md odoh-servers.md; do
  for g in "$f" "$f.minisig"; do
    tmp=$(mktemp "$lists/.partial.XXXXXX")
    curl -fsSL --retry 3 -o "$tmp" "https://download.dnscrypt.info/resolvers-list/v3/$g" || { rm -f "$tmp"; exit 1; }
    mv "$tmp" "$lists/$g"
  done
done
