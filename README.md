# profile-pdf-parser

Parse manually exported professional profile PDFs into structured data.

The parser is currently optimized for manually exported LinkedIn profile PDFs,
but it does not access LinkedIn, automate browser activity, scrape websites, or
download profile data. It only reads PDF bytes that your application or CLI user
already has locally.

This project is not affiliated with, endorsed by, or sponsored by LinkedIn
Corporation. LinkedIn is a trademark of LinkedIn Corporation and its affiliates.

## Install

```bash
pip install "profile-pdf-parser @ https://github.com/fkallmer/profile-pdf-parser/archive/refs/tags/v0.2.0.zip"
```

## Python Usage

```python
from pathlib import Path

from profile_pdf_parser import parse_profile_pdf

pdf_bytes = Path("Profile.pdf").read_bytes()
profile = parse_profile_pdf(pdf_bytes)

print(profile["person"]["name"])
print(profile["experience"][0]["company"])
```

`parse_profile_pdf()` returns a plain Python `dict`. That makes it easy to map
the parsed data into your own database models, Pydantic models, API responses, or
JSON files.

For older integrations, `parse_linkedin_pdf()` still exists and returns the
original German-keyed output shape.

## JSON Export

Write JSON to stdout:

```bash
python -m profile_pdf_parser Profile.pdf
```

Write JSON to a file:

```bash
python -m profile_pdf_parser Profile.pdf -o profile.json
```

If installed with scripts enabled, the console command is available too:

```bash
profile-pdf-parser Profile.pdf -o profile.json
```

Use compact JSON:

```bash
profile-pdf-parser Profile.pdf --indent 0
```

Write the backward-compatible German-keyed output:

```bash
profile-pdf-parser Profile.pdf --legacy -o profile.legacy.json
```

## Output Shape

The default parser output uses English keys:

```python
{
    "contact": {...},
    "person": {...},
    "skills": [...],
    "languages": [...],
    "experience": [...],
    "education": [...],
}
```

Example JSON shape:

```json
{
  "contact": {
    "email": "person@example.com",
    "profile_url": "https://www.linkedin.com/in/example"
  },
  "person": {
    "name": "Example Person",
    "headline": "Working Student",
    "location": {
      "city": "Lueneburg",
      "region": "Niedersachsen",
      "country": "Deutschland"
    }
  },
  "skills": [
    "Python",
    "Project Management"
  ],
  "languages": [
    {
      "name": "Deutsch",
      "level": "Native or Bilingual"
    }
  ],
  "experience": [
    {
      "company": "Example GmbH",
      "position": "Working Student",
      "start_date": "2024-10-01",
      "end_date": null,
      "current": true,
      "location": "Hamburg, Deutschland",
      "type": "working_student",
      "raw_date": "Oktober 2024 - Present (8 Monate)"
    }
  ],
  "education": [
    {
      "institution": "Example University",
      "degree": "B.Sc.",
      "field": "Business Informatics",
      "start_year": 2022,
      "end_year": 2025,
      "raw_details": "Bachelor of Science, Business Informatics - (2022 - 2025)"
    }
  ]
}
```

### Field Notes

- `contact.email`: email address found in the profile sidebar.
- `contact.profile_url`: profile URL found in the profile sidebar.
- `person.location`: split into `city`, `region`, and `country` when the PDF
  provides a comma-separated location.
- `skills`: profile sidebar skills as strings.
- `languages`: language entries with an optional proficiency `level`.
- `experience[].start_date` and `experience[].end_date`: ISO date strings using
  the first day of the parsed month. `end_date` is `null` for current roles.
- `experience[].current`: `true` when the PDF marks the role as current.
- `experience[].type`: best-effort classification such as `working_student`,
  `internship`, `full_time`, `freelance`, or `other`.
- `education[].start_year` and `education[].end_year`: parsed years when
  available.

## Locale Support

This parser is best-effort and currently optimized for German and English
LinkedIn profile PDF exports. It recognizes German and English section headers
and month names. Other locales may work partially, but they are not tested yet.

## Runtime Dependency

- `pdfplumber`

## Limits

PDF parsing is best-effort. Profile PDF layouts can change, and extracted data
should be reviewed before being written to a database or shown to users.
