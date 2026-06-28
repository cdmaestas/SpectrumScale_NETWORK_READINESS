Name:           koet
Version:        1.18.0
Release:        1%{?dist}
Summary:        IBM Storage Scale Network Readiness Tool with Web UI
License:        Apache-2.0
URL:            https://github.com/cdmaestas/SpectrumScale_NETWORK_READINESS
BuildArch:      noarch

Requires:       (python3 >= 3.8 or python3.8 or python3.9 or python3.11 or python3.12)
Requires:       fping
Requires:       gcc-c++
Requires:       psmisc
Requires:       iproute

%description
KOET (Keep On Executing Tests) validates IBM Storage Scale network readiness
by running fping latency tests and nsdperf throughput tests across all cluster
nodes, then comparing results against IBM KPIs.

This package includes a web UI (koet-ui) that provides a browser-based
interface for configuring tests, watching live output, and reviewing results.

Start the web UI:
  koet-ui                  # then open http://127.0.0.1:5002
  ssh -L 5002:127.0.0.1:5002 root@this-node   # tunnel from workstation

Or run the CLI directly:
  koet.py --hosts 10.0.0.1,10.0.0.2

%prep
# Nothing to prep — sources are copied in by build-pkg.sh

%install
install -d %{buildroot}/usr/lib/koet
install -d %{buildroot}/usr/bin
install -d %{buildroot}/usr/lib/systemd/system

install -m 0755 %{_sourcedir}/koet.py          %{buildroot}/usr/lib/koet/koet.py
install -m 0755 %{_sourcedir}/koet-server.py   %{buildroot}/usr/lib/koet/koet-server.py
install -m 0644 %{_sourcedir}/koet-ui.html     %{buildroot}/usr/lib/koet/koet-ui.html
install -m 0644 %{_sourcedir}/supported_OS.json %{buildroot}/usr/lib/koet/supported_OS.json
install -m 0644 %{_sourcedir}/packages.json    %{buildroot}/usr/lib/koet/packages.json
install -m 0644 %{_sourcedir}/packages_rdma_rh7.json %{buildroot}/usr/lib/koet/packages_rdma_rh7.json
install -m 0644 %{_sourcedir}/packages_rdma_rh8.json %{buildroot}/usr/lib/koet/packages_rdma_rh8.json
install -m 0755 %{_sourcedir}/koet-wrapper     %{buildroot}/usr/bin/koet-ui
install -m 0644 %{_sourcedir}/koet.service     %{buildroot}/usr/lib/systemd/system/koet.service

%post
VENV=/usr/lib/koet/venv

PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3.9 python3.8; do
    if command -v "$candidate" &>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done
if [[ -z "$PYTHON" ]]; then
    if python3 -c "import sys; exit(0 if sys.version_info >= (3,8) else 1)" 2>/dev/null; then
        PYTHON="python3"
    else
        echo "WARNING: Python 3.8+ not found — web UI dependencies will not be installed."
        exit 0
    fi
fi

echo "koet: creating virtual environment with $PYTHON..."
"$PYTHON" -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet "flask>=3.0,<4" distro
echo "koet: installed. Start web UI with: koet-ui"
echo "koet: to run as a service: sudo systemctl enable --now koet"

%preun
if [ $1 -eq 0 ]; then
    systemctl stop koet 2>/dev/null || true
    systemctl disable koet 2>/dev/null || true
fi

%postun
if [ $1 -eq 0 ]; then
    rm -rf /usr/lib/koet/venv
fi

%files
/usr/lib/koet/koet.py
/usr/lib/koet/koet-server.py
/usr/lib/koet/koet-ui.html
/usr/lib/koet/supported_OS.json
/usr/lib/koet/packages.json
/usr/lib/koet/packages_rdma_rh7.json
/usr/lib/koet/packages_rdma_rh8.json
/usr/bin/koet-ui
/usr/lib/systemd/system/koet.service
