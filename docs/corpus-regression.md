# Real-world corpus regressions

The repository does not redistribute third-party PDFs. Real-world documents may be copyrighted, confidential, or covered by terms that prohibit redistribution; keep the corpus in a separately controlled directory and record provenance and licence information for every file. Do not add corpus PDFs to Git.

The regression runner uses the same `remediate_file` pipeline as the CLI and web app. It verifies that remediation succeeds, rendering and extracted text are unchanged, and any per-document semantic expectations are met. veraPDF can be requested for machine validation; configure it using the usual `PDFREM_*` settings or disable it for a local run.

## Corpus layout

Create a directory with a `manifest.json` and its PDF files:

```text
private-pdf-corpus/
  manifest.json
  born-digital/
    annual-report.pdf
  tables/
    budget.pdf
```

The manifest is versioned and documents must identify their category, source, and licence. Expected checks are optional; use them for cases with reviewed ground truth:

```json
{
  "version": 1,
  "documents": [
    {
      "id": "annual-report",
      "file": "born-digital/annual-report.pdf",
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "category": "born-digital-multicolumn",
      "source": "https://example.gov/reports/annual-report.pdf",
      "license": "Public domain; source agency and verification date recorded separately",
      "expected": {
        "required_roles": { "H1": 1, "Table": 1, "TH": 2 },
        "required_issue_rules": [],
        "forbidden_issue_rules": [ "tagger.page-unmapped" ],
        "machine_validation": "pass"
      }
    }
  ]
}
```

`sha256` pins each input so a changed or replaced PDF is rejected before evaluation. Calculate it with `Get-FileHash -Algorithm SHA256 <file>` on Windows or `sha256sum <file>` on Linux/macOS. `required_roles` values are minimum counts in the output structure tree. `required_issue_rules` and `forbidden_issue_rules` refer to issue IDs from the remediation report. `machine_validation` may be `pass`, `fail`, or `not run`; omit it when the result is intentionally environment-dependent.

## Run it

Install the development dependencies, then run from the repository root:

```powershell
python -m pip install -e ".[dev]"
python scripts\evaluate_corpus.py --corpus-dir C:\data\private-pdf-corpus --output-dir C:\data\corpus-results --engine basic --no-verapdf
```

For veraPDF checks, install it with `pdfrem install-engines` and omit `--no-verapdf`. Results include `corpus-results.json`, `corpus-results.csv`, and one remediated PDF per manifest entry. The command exits non-zero if any regression expectation or preservation gate fails.

Use stable corpus versions and review diffs whenever input PDFs, expected annotations, engine versions, or remediation code changes. CI runs the checked-in synthetic and structural regression tests; it does not download or process private/user-supplied corpus documents. A large gold corpus still requires licence review, annotation guidance, independent annotators, adjudication, and a published baseline before accuracy claims are made.
