# linkedin-profile-pdf

Small parser for LinkedIn profile PDF exports.

```python
from linkedin_profile_pdf import parse_linkedin_pdf

profile = parse_linkedin_pdf(pdf_bytes)
```

The package returns plain dictionaries so applications can map the parsed data
to their own database models.

## Runtime Dependency

- `pdfplumber`

## Parsed Data

- contact email and LinkedIn URL
- profile header and location
- skills and languages
- work experience
- education
