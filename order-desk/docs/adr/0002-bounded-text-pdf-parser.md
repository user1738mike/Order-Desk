# ADR 0002: pypdf with a bounded Linux child for the first text-PDF profile

Accepted locally for `order-text-pdf-v1`; actual fixture, process-isolation,
PostgreSQL and browser checks are recorded in PROJECT_STATE.md.

The narrow delimiter/anchor profile needs page text and simple text-origin
checks, not rendering or inferred tables. pypdf 6.20.0 is pure Python,
BSD-3-Clause, declares Python 3.14 support and adds no mandatory runtime
dependencies on our Python version. It is pinned in pyproject.toml and uv.lock.
pdfplumber 0.11.10 is MIT and provides useful word boxes, but brings pdfminer,
Pillow and native PDFium dependencies unnecessary for this profile. Neither
library offers sufficient hostile-input resource isolation on its own.

Primary references: [pypdf release metadata](https://pypi.org/project/pypdf/6.20.0/),
[pypdf extraction caveats](https://pypdf.readthedocs.io/en/latest/user/extract-text.html),
[security configuration](https://pypdf.readthedocs.io/en/latest/user/security.html),
[pdfplumber packaging](https://github.com/jsvine/pdfplumber/blob/v0.11.10/requirements.txt).
Published pypdf resource advisories and content-stream memory warnings motivate
the OS limits and hard external deadline rather than trusting file-size limits.

Saved page text plus stable character spans is truthful provenance for this
profile. Origin matrices are validated only for simple Courier, unrotated
Letter pages; forms/images/uncertain positions fail. No bounding boxes are
invented. Exact values are preserved and explicit human selection is required.

The existing restricted worker launches a separate memory-only parser with
minimal environment, Linux rlimits/no-new-privileges/seccomp, bounded pipes and
process-group timeout. It never gives the parser database credentials. Native
Windows execution fails closed and uses Docker for development. No remote
service, OCR, subprocess renderer or additional queue is permitted.
