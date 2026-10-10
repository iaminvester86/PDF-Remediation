#!/usr/bin/env bash
# Install PDF Remediation with all engines on Linux or macOS.
#
#   scripts/install.sh            # into ./.venv
#   VENV=/opt/pdfrem scripts/install.sh
#
# Installs: the application, Python OCR (RapidOCR), the OpenDataLoader structure
# engine, and the veraPDF validator (downloaded from Maven Central with pinned
# SHA-256 checksums). Java 11+ is needed for the two Java engines; without it the
# application still works with the built-in engine and no veraPDF validation.
set -euo pipefail
cd "$(dirname "$0")/.."
VENV="${VENV:-.venv}"
PYTHON="${PYTHON:-python3}"

"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || { echo "Python 3.11 or newer is required (found $($PYTHON --version 2>&1))." >&2; exit 1; }

echo "==> Creating virtual environment in $VENV"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
echo "==> Installing PDF Remediation with OCR and OpenDataLoader"
"$VENV/bin/python" -m pip install --quiet -e ".[all]"

if command -v java >/dev/null 2>&1; then
  echo "==> Installing the veraPDF validator"
  "$VENV/bin/pdfrem" install-engines
else
  echo "!! Java was not found. Install Java 17 or 21 (for example Eclipse Temurin: https://adoptium.net)," >&2
  echo "!! then run: $VENV/bin/pdfrem install-engines" >&2
fi

echo
"$VENV/bin/pdfrem" doctor
echo
echo "Start the web app with:  $VENV/bin/pdfrem serve"
