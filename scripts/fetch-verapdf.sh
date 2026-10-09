#!/usr/bin/env bash
# Download the veraPDF validator (GPLv3+/MPLv2+, run as a separate process) into
# vendor/verapdf/lib using Maven. Requires Java 11+ and Maven 3.
# Alternative: install veraPDF from https://verapdf.org and set PDFREM_VERAPDF_CMD=/path/to/verapdf
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p vendor/verapdf
mvn -q -B -f scripts/verapdf-pom.xml dependency:copy-dependencies -DoutputDirectory="$PWD/vendor/verapdf/lib"
echo "veraPDF installed in vendor/verapdf/lib"
