#!/usr/bin/env bash
# Start the KOET web UI backend server.
# Installs Flask and distro if missing, then starts koet-server.py.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="$SCRIPT_DIR/koet-server.py"
PORT="${PORT:-5002}"

if [[ ! -f "$SERVER" ]]; then
  echo "ERROR: koet-server.py not found at $SERVER" >&2
  exit 1
fi

# Find Python >= 3.8 (prefer highest version)
PYTHON=""
for minor in 14 13 12 11 10 9 8; do
  for candidate in "python3.$minor" "/usr/bin/python3.$minor" "/usr/local/bin/python3.$minor"; do
    if command -v "$candidate" &>/dev/null 2>&1; then
      PYTHON="$candidate"
      break 2
    fi
  done
done

# Fall back to python3 if it meets the requirement
if [[ -z "$PYTHON" ]]; then
  if python3 -c "import sys; exit(0 if sys.version_info >= (3,8) else 1)" 2>/dev/null; then
    PYTHON="python3"
  fi
fi

if [[ -z "$PYTHON" ]]; then
  echo "ERROR: Python 3.8+ is required but not found." >&2
  echo "Install:   sudo dnf install python3  OR  sudo apt install python3" >&2
  exit 1
fi

echo "Using $PYTHON ($(${PYTHON} --version 2>&1))"

# Ensure Flask and distro are available
for pkg in flask distro; do
  if ! "$PYTHON" -c "import $pkg" 2>/dev/null; then
    echo "$pkg not found — installing..."
    if ! "$PYTHON" -m pip install "$pkg" 2>/dev/null; then
      if command -v curl &>/dev/null; then
        curl -sSL https://bootstrap.pypa.io/get-pip.py | "$PYTHON"
      elif command -v wget &>/dev/null; then
        wget -qO- https://bootstrap.pypa.io/get-pip.py | "$PYTHON"
      else
        echo "ERROR: pip not available and neither curl nor wget found." >&2
        echo "Install pip: sudo dnf install python3-pip  OR  sudo apt install python3-pip" >&2
        exit 1
      fi
      "$PYTHON" -m pip install "$pkg"
    fi
  fi
done

echo ""
echo "KOET Web UI — backend server"
echo "  URL : http://127.0.0.1:$PORT"
echo "  Stop: Ctrl+C"
echo ""

PORT="$PORT" "$PYTHON" "$SERVER"
