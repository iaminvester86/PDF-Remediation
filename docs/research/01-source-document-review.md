# Review of the three supplied source documents

Documents reviewed:

- **A.** *Comprehensive Guide to Accessibility Tool Requirements for U.S. Federal and State Markets* (41 pp., states it is current "as of March 2026")
- **B.** *Pitfalls* (13 pp., a chat transcript collating "Section 508 compliance pitfalls")
- **C.** *Web Accessibility Guidelines Research Report* (27 pp., dated February 2025)

Purpose: decide what can be relied on when planning the product. Each item below states the claim, what is actually true, and the consequence for the plan. Verified corrections cite the source used. Anything I could not verify is labelled as such.

## 1. Summary judgement

| Doc | Usable for | Not usable for |
|---|---|---|
| A | General orientation on Section 508, ADA Title II, ACR/VPAT, procurement steps, overlay risks | Exact WCAG counts, current Title II dates, anything PDF-specific (it omits PDF/UA and Matterhorn entirely) |
| B | A checklist of *topics* to consider | Any statistic. Most numbers have no traceable primary source and several look fabricated. |
| C | Feature inventory of web-testing platforms | WCAG counts and dates, the competitor comparison table (unsourced, and contradicted by the vendor's own site) |

None of the three documents addresses the core of a **PDF remediation** product: PDF/UA (ISO 14289-1/-2), the Matterhorn Protocol, Well-Tagged PDF, tag-tree semantics, content-stream marking, font embedding, or the Section 508 rule that authoring tools exporting PDF must be able to export PDF/UA-1 (36 CFR 1194, E205/504.2.2). They are written for web accessibility testing. The plan therefore relies on separate research for the PDF domain.

## 2. Factual errors and corrections

### 2.1 Regulatory dates (A, C): superseded

- **Claim (A §1.2, C §2.1, §4.1):** ADA Title II compliance by April 24, 2026 (50,000+ population) and April 24/26, 2027 (smaller).
- **Correction:** DOJ issued an Interim Final Rule on April 20, 2026 extending the dates by one year: **April 26, 2027** (50,000+) and **April 26, 2028** (smaller entities and special districts). The WCAG 2.1 AA standard is unchanged. Sources: [Duane Morris](https://www.duanemorris.com/alerts/doj_extends_ada_title_ii_digital_accessibility_deadlines_one_year_0426.html), [SBA Office of Advocacy](https://advocacy.sba.gov/2026/04/27/doj-extends-compliance-dates-for-state-and-local-governments-to-make-their-websites-accessible/), [Reed Smith](https://www.reedsmith.com/articles/doj-extends-digital-accessibility-compliance-dates-under-title-ii-of-the-ada/). Reports mention an NFB legal challenge to the extension; its status is unverified.
- **Related, missing from all three:** HHS's Section 504 rule (WCAG 2.1 AA for HHS funding recipients, which includes many universities and hospitals) was extended the same way to **May 11, 2027** (15+ employees) and **May 10, 2028** ([Deque](https://www.deque.com/de/blog/hhs-section-504-deadline-extended-what-did-and-didnt-change-and-what-your-organization-needs-to-do/), [Mondaq](https://www.mondaq.com/unitedstates/healthcare/1787678/hhs-office-of-civil-rights-issues-interim-final-rule-extending-section-504-compliance-deadlines)). Not verified against the Federal Register text.
- **Plan consequence:** compliance dates must be **configuration data**, not code. The Title II "preexisting conventional electronic documents" exception is defined relative to the compliance date, so a moved date changes which PDFs qualify. Triage logic must read the date from a versioned policy profile.

### 2.2 Which WCAG version applies to whom (A)

- **Claim (A §1.3):** "WCAG 2.1 is the technical standard mandated by both federal Section 508 and state ADA Title II."
- **Correction:** The Revised 508 Standards incorporate **WCAG 2.0** Level A and AA by reference. Title II uses **WCAG 2.1** AA. Document A contradicts itself, stating this correctly in §8.2.
- **Plan consequence:** reports need selectable profiles (508 / WCAG 2.0 AA, Title II / WCAG 2.1 AA, EN 301 549, WCAG 2.2 AA, PDF/UA-1, PDF/UA-2).

### 2.3 WCAG success-criteria counts (A, C)

| Version | Correct A / AA / AAA / total | Doc A says | Doc C says |
|---|---|---|---|
| WCAG 2.0 | 25 / 13 / 23 / 61 | n/a | 25 / 13 / 23 / 61 (correct) |
| WCAG 2.1 additions | 5 / 7 / 5 / 17 | "12 additional" (§1.3) and "17 (5 A, 12 AA)" (§8.2) | 2 / 12 / 3 / 17 |
| WCAG 2.1 totals | 30 / 20 / 28 / 78 | "30 A + 20 AA = 50" (correct) | 27 / 25 / 26 / 78 |
| WCAG 2.2 additions | 2 / 4 / 3 / 9 (and 4.1.1 removed) | n/a | Table: 2 / 5 / 1 / 8. Text: "nine". Self-contradictory. |
| WCAG 2.2 totals | 31 / 24 / 31 / 86 | n/a | 29 / 30 / 27 / 86 |

The 2.2 totals follow from 2.1 (30/20/28): Level A gains 3.2.6 and 3.3.7 and loses 4.1.1, giving 31. Level AA gains 2.4.11, 2.5.7, 2.5.8 and 3.3.8, giving 24. Level AAA gains 2.4.12, 2.4.13 and 3.3.9, giving 31.

Doc C also states "Perceivable (17 guidelines in WCAG 2.2), Operable (24 guidelines)…". WCAG 2.2 has 13 guidelines in total. These numbers are wrong.

### 2.4 Publication dates and versions (C)

- **Claim:** "WCAG 2.2, published in December 2024."
- **Correction:** WCAG 2.2 became a W3C Recommendation on **5 October 2023**. The 12 December 2024 version is a republication with minor editorial updates ([W3C news](https://www.w3.org/WAI/news/2024-12-12/wcag2updates/)).
- **Claim:** "The current version, WAI-ARIA 1.3."
- **Correction:** WAI-ARIA 1.2 is the current W3C Recommendation. 1.3 is a working draft. This is of low relevance to PDF work.

### 2.5 State law detail (C)

- **Claim:** Colorado HB21-1110 effective July 1, 2024.
- **Context missing:** HB24-1454 granted a one-year good-faith grace period to July 1, 2025. That period has now ended ([Colorado fiscal note](https://leg.colorado.gov/sites/default/files/documents/2024A/bills/fn/2024a_hb1454_f1.pdf), [Level Access](https://www.levelaccess.com/blog/hb-21-1110-colorado-accessibility-law/)). Sources disagree on whether the grace covered local entities as well as state agencies. **Unverified.**

### 2.6 Competitor table (C §7)

- **Claim:** iAccessible has "AI-Powered Suggestions: No", "CI/CD: Limited", "Real-time monitoring: No".
- **Evidence against:** iAccessible's own site describes AI remediation tiers (Levels 1 to 3, including AI-generated image descriptions) and an AI-assisted document remediation product (e-508), as well as monitoring. The table cites no source. Treat it as unreliable. See `02-competitive-landscape.md`.

## 3. Unsupported or likely fabricated statistics (B, and some in A/C)

None of the following could be traced to a primary source. Several of them (marked †) cite references that point to unrelated pages; for example, references 1 to 19 in Doc B are FedRAMP POA&M templates. **Do not reuse any of these in product material, grant applications, or procurement responses.**

| Claim | Where | Status |
|---|---|---|
| "Federal agencies reject 68% of ICT submissions due to Section 508 failures (42% missing ACR, 31% testing, 27% content)" | B | No primary source found † |
| "92% of agency rejections cite alt text failures" | B | No primary source found † |
| "85% of government PDFs fail basic tagging" | B | No primary source found † |
| "Overlay widgets fail 100% of manual audits"; "47 lawsuits in 2025" | B | No primary source found. The overlay critique itself is well supported, but these numbers are not. |
| "Only 3,200 certified [Trusted] testers nationwide (2026)" | B | No primary source found |
| "87% of developers untrained per GSA 2024 audit" | B | No primary source found † |
| "73% of colorblind users abandon sites with poor contrast", "22% of adults have dexterity limitations", "Retrofitting costs 10x" | B | No primary source found |
| Automated tools detect "20-30%" (A), "30-40%" (C), "30-50%" (B) of issues | A, B, C | The three documents contradict each other. The figure depends on how issues are counted (by success criterion or by issue volume). Deque's own published study claims about 57% by volume. For PDFs, the more useful anchor is Matterhorn's split: of 136 failure conditions, 87 are machine-checkable and 47 need human judgment (2 have no defined test) ([PDF Association](https://pdfa.org/rules-for-accessible-pdf-matterhorn-protocol-1-1-is-now-available/)). |
| "Federal agencies increasingly accept only test results from Trusted Tester certified individuals" | A | The cited section508.gov page does not say this. Agencies choose their own methods. Unverified. |
| "Uncertified audits rejected"; Trusted Tester required federally | B | Overstated. Trusted Tester is a DHS-developed method that many agencies use. It is not a statutory requirement. |

## 4. Advice that is wrong or harmful in a PDF context (B)

- "Remediate with Adobe Acrobat Pro 'Prepare for Accessibility'": this is vendor-specific and not a requirement.
- "Complex charts: use `<figure><figcaption>`": this is HTML advice. In PDF the equivalents are a `Figure` with `Alt`, plus a `Caption` and/or a long description in the document.
- "Layered graphics → Flatten to JPG": rasterising content that includes text creates an image of text (WCAG 1.4.5) and destroys selectable text. It is acceptable only for purely decorative or vector-only figures.
- "Use Axe-Deque rule image-alt" as the test for alt text: axe is a web/HTML engine and does not test PDFs.

## 5. What the documents get right and the plan keeps

- Overlays do not fix underlying content. The product must change the document itself, not layer something on top. (A §8.1, B; well supported by independent sources.)
- Automated checks are necessary but not sufficient. A hybrid process with human verification is required. (A §4.1, §8.3; confirmed independently by our spike, where a semantically wrong file passed veraPDF.)
- ACR/VPAT documentation is expected in procurement, and an OpenACR (machine-readable) ACR is the recommended format. (A §4.2.) The product itself will need its own ACR.
- Remediation is a lifecycle that needs severity-based prioritisation, retesting, and records retention. (A §6.2, §9.)
- Documentation and audit records matter for government buyers. (A §9.)

## 6. Material the documents omit that the plan adds

1. PDF/UA-1 (ISO 14289-1), PDF/UA-2 (ISO 14289-2:2024), Well-Tagged PDF (WTPDF 1.0), Matterhorn Protocol 1.1.
2. Section 508 authoring-tool rule: tools that export PDF 1.7 must be able to export PDF/UA-1 (504.2.2), and must preserve accessibility information on conversion (504.2.1). ([PDF Association](https://www.pdfa.org/new-section-508-rules-require-pdfua-for-pdf-1-7-creators)). A remediation tool is an authoring tool under this definition.
3. The Title II exceptions for archived content and preexisting conventional electronic documents. These drive backlog triage and are the largest cost lever for document-heavy agencies such as education departments.
4. HHS Section 504 web rule (above).
5. Government AI constraints: OMB M-25-21/M-25-22, FedRAMP routes for model access, FERPA "school official" requirements. See `05-ai-integration-and-government-constraints.md`.
6. Open-source licensing constraints on the PDF and ML stack. See `04-open-source-stack-and-licensing.md`.
