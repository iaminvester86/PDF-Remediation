# Standards and regulations the product must implement or report against

Research date: October 2026. Dates and thresholds change; the product must load them from versioned policy profiles (see `docs/PLAN.md`, section 5.6), never from code.

## 1. Technical standards

| Standard | Status | What it means for the product |
|---|---|---|
| **PDF/UA-1** (ISO 14289-1:2014) | In force. Referenced by Section 508 for authoring tools (504.2.2). | Primary output target for v1. Based on PDF 1.7. |
| **Matterhorn Protocol 1.1** (PDF Association) | Current | 31 checkpoints, 136 failure conditions: 87 machine-checkable, 47 needing human judgment, 2 without a defined test ([PDF Association](https://pdfa.org/rules-for-accessible-pdf-matterhorn-protocol-1-1-is-now-available/)). One vendor counts 89/45. The human-judgment conditions define our **manual verification checklist**. |
| **PDF/UA-2** (ISO 14289-2:2024) | Published 2024. Requires PDF 2.0. | Separate writer path. PDF 2.0 structure namespaces, `pdfuaid:rev`, MathML support, revised table and link rules. Spike 001 showed UA-1 output fails 3 UA-2 rules immediately. Planned for Phase 6. |
| **Well-Tagged PDF (WTPDF 1.0)** | PDF Association specification. Conformance levels "Accessibility" and "Reuse". | Aligned with UA-2. OpenDataLoader targets it. veraPDF validates `wt1a`/`wt1r`. |
| **WCAG 2.0 / 2.1 / 2.2** | 2.0 (2008), 2.1 (2018), 2.2 (Oct 2023, republished Dec 2024) | Report mapping. The PDF-relevant success criteria are listed in section 3. |
| **PDF Techniques for WCAG** (PDF1-PDF23) | W3C Working Group Note | How each WCAG criterion is met in PDF. Used to write remediation guidance text. |
| **EN 301 549** (v3.2.1) | EU ICT procurement standard, WCAG 2.1 based; clause 10 covers documents | Profile for EU customers. European Accessibility Act applies from 28 June 2025. |
| **PDF/A** (ISO 19005) | Archival. PDF/A-1a, 2a, and 3a require tagging. | Optional combined PDF/A-2a + PDF/UA-1 output for records-management customers. veraPDF validates both. |

## 2. U.S. legal requirements (as of October 2026)

| Instrument | Who | Standard | Dates | Product implication |
|---|---|---|---|---|
| **Section 508** (Revised Standards, 36 CFR 1194, effective Jan 18, 2018) | Federal agencies (ICT they develop, procure, maintain, use) | WCAG 2.0 A/AA by reference; PDF/UA-1 for authoring-tool PDF export | In force | "508" profile = WCAG 2.0 AA. **The product itself is an authoring tool:** 504.2 (create accessible content), 504.2.1 (preserve accessibility on conversion), 504.2.2 (PDF/UA-1 export capability), 504.3 (prompts), 504.4 (templates). The tool's own UI must also meet 508. |
| **ADA Title II web rule** (28 CFR 35 subpart H, 2024) | State and local government, including public schools, universities, libraries, transit | WCAG 2.1 AA | **Extended by Interim Final Rule of April 20, 2026:** April 26, **2027** (population 50,000+), April 26, **2028** (smaller and special districts) | Title II profile. Exceptions drive triage (section 4). |
| **HHS Section 504 rule** (45 CFR 84, 2024) | Recipients of HHS funding (hospitals, many universities) | WCAG 2.1 AA | Extended by IFR: May 11, **2027** (15+ employees), May 10, **2028** (fewer) | Same profile as Title II, different dates. |
| **Section 504** (general) and ED/OCR enforcement | Recipients of ED funding (schools, colleges) | No codified technical standard. OCR resolution agreements commonly cite WCAG 2.0/2.1 AA. | Ongoing | Education customers need audit trails for OCR complaint responses. |
| **ADA Title III** | Public accommodations | No codified standard. Litigation commonly cites WCAG 2.1 AA. | Ongoing | Commercial customers. |
| **State laws** | Varies. Examples: Colorado HB21-1110 (WCAG 2.1 AA; grace period ended July 1, 2025), California Gov. Code 7405/11135, Texas TAC 206/213, New York NYS-P08-005, Illinois IITAA. | Varies | Varies | Configurable profile per state. Details need verification per state before release; the source documents contained errors here. |

Not legal advice. Each profile must cite its source and a "last verified" date, and the UI must display both.

## 3. WCAG success criteria that apply to PDF content

These drive the WCAG mapping in reports. AA unless marked.

| SC | Topic | Machine-checkable in PDF? | How the product handles it |
|---|---|---|---|
| 1.1.1 (A) | Non-text content | Presence: yes. Quality: no. | Alt/ActualText presence check (veraPDF), alt-text lint, AI draft, human verification |
| 1.3.1 (A) | Info and relationships | Partly | Tag roles, tables (TH/Scope/Headers), lists, headings. Semantic QA heuristics plus human review. |
| 1.3.2 (A) | Meaningful sequence | No | Reading-order comparison against geometry. Human verification is mandatory. |
| 1.3.3 (A) | Sensory characteristics | No | AI flag ("see the red box"), human review |
| 1.4.1 (A) | Use of colour | No | AI and human flag |
| 1.4.3 | Contrast (minimum) | Partly (text over solid fill) | Render-based estimate. Flag as "needs review" when backgrounds are images or gradients. |
| 1.4.5 | Images of text | Partly | OCR-detect text inside figures, then flag |
| 2.4.2 (A) | Page titled | Yes | Title in XMP + DisplayDocTitle |
| 2.4.4 (A) | Link purpose (in context) | Partly | Link annotation with `Link` struct element and `Contents`. Lint "click here". |
| 2.4.5 | Multiple ways | Partly | Bookmarks generated from headings for documents above a page threshold |
| 2.4.6 | Headings and labels | No | Heading-level QA heuristics, human review |
| 3.1.1 (A) | Language of page | Yes | Catalog `/Lang` |
| 3.1.2 | Language of parts | Partly | Per-span language detection (lingua), `Lang` on struct elements |
| 3.3.2 (A) | Labels or instructions (forms) | Partly | Form field `TU` and widget tagging |
| 4.1.2 (A) | Name, role, value (forms, links) | Partly | Widget annotations, `Form` struct elements, OBJR |

Criteria such as 1.2.x (media), 2.1.x (keyboard), 2.2.x (timing) and 2.3.x (flashing) rarely apply to static PDFs. Reports list them as "Not applicable (static document)" when the triage step confirms that no multimedia, JavaScript, or forms are present.

## 4. Title II exceptions: the cost lever for backlogs

From the 2024 rule (summarised by [Wisconsin](https://www.wisconsin.edu/digital-accessibility/exceptions-to-title-ii/), [ALA](https://www.ala.org/accessibility/ada-rule-exceptions), [Connecticut](https://portal.ct.gov/accessibility/knowledge-base/articles/website-accessibility-faq/accessibility-exceptions)). Must be confirmed against the rule text at ada.gov before encoding.

1. **Archived web content:** created before the compliance date, kept only for reference, research, or recordkeeping, not altered afterwards, and held in an area clearly designated as archived.
2. **Preexisting conventional electronic documents:** PDF, word-processing, presentation, and spreadsheet files available before the compliance date, **unless currently used to apply for, access, or participate in** the entity's services, programs, or activities.
3. Content posted by third parties, individualised password-protected documents, and preexisting social media posts each have their own conditions.
4. Any exception is lost when the document is updated. An accessible version must still be provided on request.

**Product implication:** the triage module classifies each document as *likely exception-eligible*, *must remediate*, or *needs human decision*, using: first-seen or creation date compared with the profile's compliance date; whether the file is linked from an "active" path (forms, applications, current program pages); modification history; and a "currently used" flag the user sets. The tool **recommends**; a named person **decides**, and the decision is logged. With the extended dates, more documents can still be fixed before the cut-off, which changes the prioritisation calculus. This makes the dates a configuration value, not a constant.

## 5. Procurement documentation the product must produce about itself

- **ACR** using VPAT 2.x (508, WCAG, EU, INT editions) and **OpenACR** (GSA's machine-readable format) for the product itself. This includes Chapter 5 (Software) and 504 (Authoring Tools).
- An accessibility statement for any hosted demo.
- **SBOM** (CycloneDX or SPDX) for every release, plus a licence inventory.
- Security documentation for self-hosting: a threat model, hardening guide, logging, and data-flow diagrams. FedRAMP applies to cloud services an agency buys, not to open-source software the agency hosts itself. If a vendor later offers hosting, FedRAMP or GovRAMP (formerly StateRAMP) would apply to that hosted service.
