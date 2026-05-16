# profile-pdf-parser

Small parser for manually exported professional profile PDFs.

The parser is currently optimized for manually exported LinkedIn profile PDFs,
but it does not access LinkedIn, automate browser activity, scrape websites, or
download profile data.

This project is not affiliated with, endorsed by, or sponsored by LinkedIn
Corporation. LinkedIn is a trademark of LinkedIn Corporation and its affiliates.

```python
from profile_pdf_parser import parse_linkedin_pdf

profile = parse_linkedin_pdf(pdf_bytes)
```

The package returns plain dictionaries so applications can map the parsed data
to their own database models.

## Runtime Dependency

- `pdfplumber`

## Parsed Data

- contact email and profile URL
- profile header and location
- skills and languages
- work experience
- education
