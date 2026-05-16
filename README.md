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
pip install "profile-pdf-parser @ https://github.com/fkallmer/profile-pdf-parser/archive/refs/tags/v0.1.2.zip"
```

## Python Usage

```python
from pathlib import Path

from profile_pdf_parser import parse_linkedin_pdf

pdf_bytes = Path("Profile.pdf").read_bytes()
profile = parse_linkedin_pdf(pdf_bytes)

print(profile["person"]["name"])
print(profile["berufserfahrung"][0]["company"])
```

`parse_linkedin_pdf()` returns a plain Python `dict`. That makes it easy to map
the parsed data into your own database models, Pydantic models, API responses, or
JSON files.

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

## Output Shape

The parser returns this top-level structure:

```python
{
    "kontakt": {...},
    "person": {...},
    "skills": [...],
    "languages": [...],
    "berufserfahrung": [...],
    "ausbildung": [...],
}
```

Example JSON shape:

```json
{
  "kontakt": {
    "email": "person@example.com",
    "linkedin": "https://www.linkedin.com/in/example"
  },
  "person": {
    "name": "Example Person",
    "headline": "Working Student",
    "location": {
      "stadt": "Lueneburg",
      "bundesland": "Niedersachsen",
      "land": "Deutschland"
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
  "berufserfahrung": [
    {
      "company": "Example GmbH",
      "position": "Working Student",
      "von": "2024-10-01",
      "bis": null,
      "aktuell": true,
      "location": "Hamburg, Deutschland",
      "art": "werkstudent",
      "raw_date": "Oktober 2024 - Present (8 Monate)"
    }
  ],
  "ausbildung": [
    {
      "universitaet": "Example University",
      "abschluss": "B.Sc.",
      "studiengang": "Business Informatics",
      "von_jahr": 2022,
      "bis_jahr": 2025,
      "raw_details": "Bachelor of Science, Business Informatics - (2022 - 2025)"
    }
  ]
}
```

### Field Notes

- `kontakt.email`: email address found in the profile sidebar.
- `kontakt.linkedin`: profile URL found in the profile sidebar.
- `person.location`: split into `stadt`, `bundesland`, and `land` when the PDF
  provides a comma-separated location.
- `skills`: profile sidebar skills as strings.
- `languages`: language entries with an optional proficiency `level`.
- `berufserfahrung[].von` and `berufserfahrung[].bis`: ISO date strings using
  the first day of the parsed month. `bis` is `null` for current roles.
- `berufserfahrung[].aktuell`: `true` when the PDF marks the role as current.
- `berufserfahrung[].art`: best-effort classification such as `werkstudent`,
  `praktikum`, `vollzeit`, `freelance`, or `sonstiges`.
- `ausbildung[].von_jahr` and `ausbildung[].bis_jahr`: parsed years when
  available.

## Runtime Dependency

- `pdfplumber`

## Limits

PDF parsing is best-effort. Profile PDF layouts can change, and extracted data
should be reviewed before being written to a database or shown to users.
