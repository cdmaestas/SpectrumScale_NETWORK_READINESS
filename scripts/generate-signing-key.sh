#!/usr/bin/env bash
# Generate a GPG signing key for KOET RPM packages, export the public key
# to packaging/RPM-GPG-KEY-koet, and upload the private key to GitHub
# Actions secrets so the release workflow can sign packages automatically.
#
# Run once from the repo root:
#   bash scripts/generate-signing-key.sh
#
# Requirements: gpg, gh (GitHub CLI, already authenticated)

set -euo pipefail

REPO="cdmaestas/SpectrumScale_NETWORK_READINESS"
KEY_NAME="KOET RPM Signing"
KEY_EMAIL="cdmaestas@gmail.com"
KEY_FILE="packaging/RPM-GPG-KEY-koet"

cd "$(git rev-parse --show-toplevel)"

echo "==> Generating GPG key for $KEY_NAME <$KEY_EMAIL>..."
gpg --batch --gen-key <<EOF
%no-protection
Key-Type: RSA
Key-Length: 4096
Key-Usage: sign
Name-Real: $KEY_NAME
Name-Email: $KEY_EMAIL
Expire-Date: 0
%commit
EOF

# Get the fingerprint of the key we just created (match by name+email)
FINGERPRINT=$(gpg --list-secret-keys --keyid-format LONG \
    --with-colons 2>/dev/null \
  | awk -F: -v name="$KEY_NAME" '
      /^uid/ && $10 ~ name { found=1 }
      /^sec/ { key=$5; found=0 }
      found && key { print key; found=0 }
    ' | head -1)
if [[ -z "$FINGERPRINT" ]]; then
  FINGERPRINT=$(gpg --list-secret-keys --keyid-format LONG 2>/dev/null \
    | grep -A2 "$KEY_NAME" | grep "^sec" | awk '{print $2}' | cut -d'/' -f2)
fi

echo "==> Key fingerprint: $FINGERPRINT"

echo "==> Exporting public key to $KEY_FILE..."
gpg --armor --export "$FINGERPRINT" > "$KEY_FILE"
echo "    Written: $KEY_FILE"

echo "==> Uploading private key to GitHub Actions secret GPG_PRIVATE_KEY..."
gpg --armor --export-secret-keys "$FINGERPRINT" \
  | gh secret set GPG_PRIVATE_KEY --repo "$REPO"
echo "    Secret set."

echo ""
echo "==> Committing public key..."
git add "$KEY_FILE"
git commit -m "Add KOET RPM signing public key"
git push fork master

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Done. The release workflow will now sign RPMs"
echo "  automatically on every v*.*.* tag."
echo ""
echo "  To verify a signed RPM locally:"
echo "    rpm --import $KEY_FILE"
echo "    rpm --checksig dist/*.rpm"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
