#!/usr/bin/env bash
# Create a stable self-signed code-signing identity for Her.app.
#
# Why: Her.app is built with ad-hoc signing by default (codesign --sign -).
# Ad-hoc means the designated requirement is "this exact CDHash", so every
# rebuild looks like a new app to macOS TCC and re-prompts the user for
# Microphone / Camera / Apple Events / Calendars / Contacts / etc.
#
# Signing with a *self-signed* identity instead anchors the designated
# requirement on the certificate (constant across rebuilds) plus the bundle
# identifier. TCC then treats every future build of Her.app as the same
# app, and grants persist.
#
# Run this script once. After that, ./scripts/build-dmg.sh will pick up
# the identity by name and use it automatically.
#
# Usage:
#   ./scripts/create-signing-identity.sh

set -euo pipefail

IDENTITY_NAME="Her Code Signing"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: this script only runs on macOS." >&2
  exit 1
fi

# ── Idempotency ──────────────────────────────────────────────────────
# No -v: a self-signed cert isn't trust-anchored, so find-identity -v
# hides it. We just want to know if the keychain already has it.
if security find-identity -p codesigning "$KEYCHAIN" 2>/dev/null \
    | grep -q "\"$IDENTITY_NAME\""; then
  echo "Identity '$IDENTITY_NAME' already exists in the login keychain — nothing to do."
  echo "If you want to recreate it, delete it from Keychain Access first."
  exit 0
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

KEY="$TMP/key.pem"
CRT="$TMP/cert.pem"
P12="$TMP/cert.p12"
CFG="$TMP/openssl.cnf"

# OpenSSL config: minimal CN-only cert with the codeSigning EKU. Without
# extendedKeyUsage=codeSigning, codesign won't recognize this as a usable
# signing identity (security find-identity -p codesigning will skip it).
cat > "$CFG" <<EOF
[req]
distinguished_name = dn
prompt = no
x509_extensions = v3

[dn]
CN = $IDENTITY_NAME
O = Her

[v3]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = critical, codeSigning
subjectKeyIdentifier = hash
EOF

echo "==> Generating 10-year self-signed code-signing certificate"
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$KEY" -out "$CRT" \
  -days 3650 \
  -config "$CFG"

echo "==> Packing as PKCS#12"
# -legacy: OpenSSL 3 defaults to AES-256-CBC + PBKDF2 for PKCS#12, which
# macOS's `security` command can't read (it uses the older SecKeychain
# API). Force the legacy 3DES/SHA1 format so the import succeeds.
#
# An empty passphrase confuses some openssl/security combinations during
# MAC verification — use a fixed placeholder; the .p12 file is deleted
# immediately after import, so the password is never persisted.
P12_PASS="her-import-$RANDOM"
openssl pkcs12 -export -legacy -inkey "$KEY" -in "$CRT" \
  -name "$IDENTITY_NAME" \
  -out "$P12" \
  -passout "pass:$P12_PASS"

echo "==> Importing into login keychain"
# -T /usr/bin/codesign lets codesign use the private key without an ACL
# prompt every time it signs.
security import "$P12" \
  -k "$KEYCHAIN" \
  -P "$P12_PASS" \
  -T /usr/bin/codesign \
  -T /usr/bin/security

# Optionally widen the key partition list. The ACL added via -T during
# import already lets codesign use the key without a prompt; this just
# silences edge cases on newer macOS. Requires the login keychain
# password, which we can't supply non-interactively — best-effort.
echo "==> Updating key partition list (may prompt for your macOS password)"
security set-key-partition-list \
  -S apple-tool:,apple:,codesign: \
  -s "$KEYCHAIN" >/dev/null 2>&1 \
  || echo "    (skipped — codesign should still work via the ACL)"

echo
echo "Done. Verify with:"
echo "  security find-identity -v -p codesigning"
echo
echo "Now rebuild:"
echo "  ./scripts/build-dmg.sh --app-only"
echo
echo "macOS will prompt you ONE more time for permissions (the new signature"
echo "means TCC considers this a fresh app). After that, every future rebuild"
echo "keeps the same designated requirement, so the grants persist."
