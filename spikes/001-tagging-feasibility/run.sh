#!/usr/bin/env bash
# Reproduce spike 001. Requires: Python 3.11+, Java 11+, Maven 3, DejaVu fonts
# (/usr/share/fonts/truetype/dejavu). Writes everything under ./out.
set -euo pipefail
cd "$(dirname "$0")"
OUT="$PWD/out"; mkdir -p "$OUT"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q "pikepdf==10.16.0" "reportlab==5.0.1" "opendataloader-pdf==2.5.12"
fi
PY=".venv/bin/python -I"

if [ ! -d lib ]; then
  mvn -q -B dependency:copy-dependencies -DoutputDirectory=lib
fi
vera() { java -cp "lib/*" org.verapdf.apps.GreenfieldCliWrapper "$@" 2>/dev/null; }
check() {  # $1=flavour $2=file
  vera -f "$1" --format json "$2" > "$2.$1.json" || true
  printf '%-28s %-4s %s\n' "$(basename "$2")" "$1" "$(vera -f "$1" --format text "$2" | cut -d' ' -f1)"
  $PY report.py "$2.$1.json"
}

echo "== Experiment A: hand-written pikepdf tagger"
$PY spike.py "$OUT" noembed
$PY spike.py "$OUT" embed
$PY spike.py "$OUT" embed --wrong-semantics
check ua1 "$OUT/untagged_embed.pdf"
check ua1 "$OUT/tagged_noembed.pdf"
check ua1 "$OUT/tagged_embed.pdf"
check ua2 "$OUT/tagged_embed.pdf"
check ua1 "$OUT/wrong_embed.pdf"

echo "== Experiment B: OpenDataLoader auto-tag + finisher"
$PY make_sample.py "$OUT/sample.pdf"
.venv/bin/opendataloader-pdf -q -f tagged-pdf -o "$OUT" "$OUT/sample.pdf"
check ua1 "$OUT/sample_tagged.pdf"
$PY dumptree.py "$OUT/sample_tagged.pdf"
$PY finish.py "$OUT/sample_tagged.pdf" "$OUT/sample_finished.pdf" "Budget Summary for Fiscal Year 2026"
check ua1 "$OUT/sample_finished.pdf"
$PY strip_empty_bt.py "$OUT/sample_finished.pdf" "$OUT/sample_final.pdf"
check ua1 "$OUT/sample_final.pdf"
