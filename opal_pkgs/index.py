"""Write the opkg Packages index and a browser page for every ipk in a feed."""

import gzip
import hashlib
import html
import io
import re
import tarfile
from pathlib import Path
from urllib.parse import quote

ARCHES = {"all", "mips_siflower"}


def members(raw):
    """Yield (name, bytes) from an ipk in either ar or tar.gz form."""
    if raw.startswith(b"!<arch>\n"):
        off = 8
        while off + 60 <= len(raw):
            name = raw[off : off + 16].decode().strip().rstrip("/")
            size = int(raw[off + 48 : off + 58])
            yield name, raw[off + 60 : off + 60 + size]
            off += 60 + size + size % 2
    else:
        with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
            for m in tf.getmembers():
                if m.isfile():
                    yield m.name.removeprefix("./"), tf.extractfile(m).read()


def control(raw):
    with tarfile.open(fileobj=io.BytesIO(dict(members(raw))["control.tar.gz"])) as tf:
        member = next(
            m for m in tf.getmembers() if m.name.removeprefix("./") == "control"
        )
        return tf.extractfile(member).read().decode().strip()


def record(ipk):
    raw = ipk.read_bytes()
    text = control(raw)
    fields = dict(
        line.split(": ", 1)
        for line in text.splitlines()
        if ": " in line and not line.startswith(" ")
    )
    for key in ("Package", "Version", "Architecture"):
        if key not in fields:
            raise SystemExit(f"{ipk.name}: control has no {key}")
    if fields["Architecture"] not in ARCHES:
        raise SystemExit(
            f"{ipk.name}: architecture {fields['Architecture']} does not run on the Opal"
        )
    return {
        "text": text,
        "fields": fields,
        "filename": ipk.name,
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def format_row(row):
    return (
        f"{row['text']}\nFilename: {row['filename']}\n"
        f"Size: {row['size']}\nSHA256sum: {row['sha256']}\n"
    )


def stanza(ipk):
    return format_row(record(ipk))


def version_key(version):
    # shortcut: numeric chunks only, no debian epoch. upgrade if a version uses ':'.
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"(\d+)", version)
        if part
    )


def human_size(n):
    value = float(n)
    for unit in ("B", "KiB", "MiB"):
        if value < 1024 or unit == "MiB":
            if unit == "B":
                return f"{int(value)} B"
            text = f"{value:.1f}".rstrip("0").rstrip(".")
            return f"{text} {unit}"
        value /= 1024


def _esc(value):
    return html.escape(str(value), quote=True)


def _meta(fields):
    bits = [
        f"<span>{_esc(key)}: {_esc(fields[key])}</span>"
        for key in ("Depends", "License", "Section", "Installed-Size")
        if fields.get(key)
    ]
    return f'<p class="meta">{"".join(bits)}</p>' if bits else ""


def _version(row, latest_desc):
    fields = row["fields"]
    query = " ".join(
        [
            fields.get("Package", ""),
            fields.get("Version", ""),
            fields.get("Architecture", ""),
            fields.get("Description", ""),
            fields.get("Depends", ""),
            row["filename"],
        ]
    ).lower()
    own = fields.get("Description", "")
    extra = f'<p class="desc">{_esc(own)}</p>' if own and own != latest_desc else ""
    meta = _meta(fields)
    summary = "depends and checksum" if meta else "checksum"
    return (
        f'<li data-q="{_esc(query)}">'
        f'<p class="file"><a href="{_esc(quote(row["filename"]))}">'
        f"{_esc(row['filename'])}</a> "
        f"<span>{_esc(fields['Version'])} · {_esc(fields['Architecture'])} · "
        f"{_esc(human_size(row['size']))}</span></p>"
        f"{extra}"
        f"<details><summary>{summary}</summary>{meta}"
        f'<p class="sha">SHA256 <code>{_esc(row["sha256"])}</code></p></details>'
        "</li>"
    )


def _older(items):
    n = len(items)
    if not n:
        return ""
    label = "1 older version" if n == 1 else f"{n} older versions"
    return (
        f'<li class="more"><details class="older"><summary>{label}</summary>'
        f"<ol>{''.join(items)}</ol></details></li>"
    )


def _package(name, versions):
    latest = versions[0]["fields"].get("Description", "")
    desc = f'<p class="desc">{_esc(latest)}</p>' if latest else ""
    body = _version(versions[0], latest) + _older(
        [_version(row, latest) for row in versions[1:]]
    )
    return f"<article><h2>{_esc(name)}</h2>{desc}<ol>{body}</ol></article>"


def _counts(packages, ipks):
    return (
        f"{packages} package{'' if packages == 1 else 's'}, "
        f"{ipks} ipk{'' if ipks == 1 else 's'}"
    )


PAGE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>opal-pkgs</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #f4f1ea;
    --fg: #1c1917;
    --muted: #57534e;
    --line: #e6e1d8;
    --card: #fffcf7;
    --accent: #0f6b45;
    --chip: #efeae2;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #1a1814;
      --fg: #f5f1e8;
      --muted: #a8a29e;
      --line: #3f3a34;
      --card: #24211c;
      --accent: #6ee7b7;
      --chip: #312d27;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0 auto;
    max-width: 52rem;
    padding: 2rem 1.25rem 4rem;
    background: var(--bg);
    color: var(--fg);
    font: 16px/1.5 ui-sans-serif, system-ui, sans-serif;
  }
  h1 { margin: 0 0 0.25rem; font-size: 1.75rem; letter-spacing: -0.02em; }
  header p, #count, .desc, .meta, .file span, summary { color: var(--muted); }
  header p { margin: 0.25rem 0; }
  pre, input, article { border: 1px solid var(--line); border-radius: 10px; }
  pre, input, article { background: var(--card); }
  pre { margin: 1rem 0; padding: 0.75rem 1rem; overflow: auto; background: var(--chip); }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  label {
    display: block;
    position: sticky;
    top: 0;
    z-index: 2;
    margin: 0.5rem 0 0;
    padding: 0.65rem 0 0.5rem;
    background: var(--bg);
    color: var(--muted);
    font-size: 0.85rem;
  }
  input {
    display: block;
    width: 100%;
    margin-top: 0.35rem;
    padding: 0.65rem 0.75rem;
    color: inherit;
    font: inherit;
  }
  #count { margin: 0.75rem 0 0; font-size: 0.9rem; }
  article { margin: 1rem 0; }
  h2 { margin: 0; padding: 0.9rem 1rem 0; font-size: 1.15rem; }
  article > .desc { margin: 0.15rem 0 0; padding: 0 1rem; }
  ol { margin: 0.75rem 0 0; padding: 0; list-style: none; }
  li { padding: 0.7rem 1rem; border-top: 1px solid var(--line); }
  .more { padding-top: 0.45rem; }
  .more .older { margin: 0; }
  .more ol { margin: 0.35rem 0 0; }
  .more li { padding-right: 0; padding-left: 0; }
  .meta, .sha, li .desc, details { margin: 0.35rem 0 0; }
  .meta { display: flex; flex-wrap: wrap; gap: 0.15rem 0.8rem; }
  .file {
    display: flex;
    flex-wrap: wrap;
    gap: 0.2rem 1rem;
    align-items: baseline;
    margin: 0;
  }
  .file span { margin-left: auto; font-size: 0.9rem; }
  .file a {
    color: var(--accent);
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.92rem;
    font-weight: 600;
    overflow-wrap: anywhere;
    text-underline-offset: 0.25em;
  }
  summary { cursor: pointer; font-size: 0.85rem; }
  .sha code { font-size: 0.78rem; overflow-wrap: anywhere; }
  a:focus-visible, input:focus-visible, summary:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  @media (max-width: 640px) {
    body {
      padding: 1.15rem max(0.85rem, env(safe-area-inset-right)) 2.5rem max(0.85rem, env(safe-area-inset-left));
    }
    h1 { font-size: 1.45rem; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; }
    .file { flex-direction: column; align-items: flex-start; gap: 0.15rem; }
    .file span { margin-left: 0; }
    summary { padding: 0.55rem 0; }
  }
</style>
</head>
<body>
<header>
<h1>opal-pkgs</h1>
<p>Newer upstream releases of the userspace on a GL.iNet Opal (GL-SFT1200) running firmware 4.8.3.</p>
<p>Add this line to <code>/etc/opkg/customfeeds.conf</code>:</p>
<pre><code>src/gz opal https://kgrubb.github.io/opal-pkgs</code></pre>
</header>
<label for="q">Filter packages
<input id="q" type="search" autocomplete="off" placeholder="name, version, or description">
</label>
<p id="count" aria-live="polite"><!--count--></p>
<main>
"""

PAGE_TAIL = """</main>
<script>
const box = document.querySelector("#q");
const count = document.querySelector("#count");
function label(packages, ipks) {
  return packages + " package" + (packages === 1 ? "" : "s") + ", " +
    ipks + " ipk" + (ipks === 1 ? "" : "s");
}
box.addEventListener("input", function () {
  const needle = box.value.trim().toLowerCase();
  let packages = 0;
  let ipks = 0;
  for (const article of document.querySelectorAll("article")) {
    let shown = 0;
    for (const item of article.querySelectorAll("li[data-q]")) {
      const hit = !needle || item.dataset.q.includes(needle);
      item.hidden = !hit;
      shown += hit;
    }
    const older = article.querySelector("details.older");
    if (older) {
      const hits = [...older.querySelectorAll("li")].filter((item) => !item.hidden).length;
      older.parentElement.hidden = hits === 0;
      older.open = needle.length > 0 && hits > 0;
    }
    article.hidden = shown === 0;
    packages += shown > 0;
    ipks += shown;
  }
  count.textContent = label(packages, ipks);
});
</script>
</body>
</html>
"""


def browse(rows):
    groups = {}
    for row in rows:
        groups.setdefault(row["fields"]["Package"], []).append(row)
    body = []
    for name in sorted(groups):
        versions = sorted(
            groups[name],
            key=lambda row: version_key(row["fields"]["Version"]),
            reverse=True,
        )
        body.append(_package(name, versions))
    label = _counts(len(groups), len(rows))
    return PAGE_HEAD.replace("<!--count-->", _esc(label)) + "".join(body) + PAGE_TAIL


def write_index(feed):
    feed = Path(feed)
    ipks = sorted(feed.glob("*.ipk"))
    if not ipks:
        raise SystemExit(f"no ipks in {feed}")
    rows = [record(p) for p in ipks]
    text = "\n".join(format_row(row) for row in rows)
    (feed / "Packages").write_text(text)
    (feed / "Packages.gz").write_bytes(gzip.compress(text.encode(), mtime=0))
    (feed / "index.html").write_text(browse(rows))
