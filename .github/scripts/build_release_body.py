#!/usr/bin/env python3
"""
Extract the changelog section for a given version tag and append
standard install instructions, writing the result to /tmp/release_body.md.

Usage (called by the Release workflow):
    VERSION=1.18.0 python3 .github/scripts/build_release_body.py
"""
import os
import re
import sys

tag = os.environ.get("VERSION", "").strip()
if not tag:
    print("ERROR: VERSION env var is required", file=sys.stderr)
    sys.exit(1)

repo = os.environ.get("GITHUB_REPOSITORY", "cdmaestas/SpectrumScale_NETWORK_READINESS")

try:
    with open("CHANGELOG.md") as f:
        text = f.read()
except FileNotFoundError:
    text = ""

pattern = rf"## \[{re.escape(tag)}\][^\n]*\n(.*?)(?=\n## \[|\Z)"
m = re.search(pattern, text, re.DOTALL)
if m:
    body = m.group(1).strip()
else:
    print(f"No changelog entry found for {tag} — using generic body", file=sys.stderr)
    body = f"See [CHANGELOG](https://github.com/{repo}/blob/master/CHANGELOG.md) for details."

rpm_ver = tag.replace("-", ".")
rpm_name = f"koet-{rpm_ver}-1.noarch.rpm"
deb_name = f"koet_{tag}-1_all.deb"

body += f"""

---

### Install on the IBM Storage Scale cluster node

**RHEL / Rocky Linux:**
```bash
# Download both files from the release assets, then:
sudo rpm --import RPM-GPG-KEY-koet
sudo dnf install ./{rpm_name}
```

**Debian / Ubuntu:**
```bash
sudo apt install ./{deb_name}
```

Then start the web UI:
```bash
koet-ui
# or as a service:
sudo systemctl enable --now koet
```

### Connect from your workstation
```bash
ssh -L 5002:127.0.0.1:5002 root@cluster-node
```
Open `http://127.0.0.1:5002` in a local browser.

---
See [README](https://github.com/{repo}/blob/master/README.md) for full documentation."""

out = "/tmp/release_body.md"
with open(out, "w") as f:
    f.write(body)
print(f"Wrote release body to {out}")
