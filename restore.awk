NR == FNR { if ($1 == n) old = $0; next }
$1 == n && old != "" { print old; next }
{ print }
