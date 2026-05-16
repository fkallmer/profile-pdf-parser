"""Parser for manually exported professional profile PDFs.

The parser is currently optimized for manually exported LinkedIn profile PDFs.
It reads local PDF bytes only and returns plain Python dictionaries.
"""

import io
import re
from datetime import date
from typing import Literal, Optional

import pdfplumber


Language = Literal["auto", "de", "en"]

# Constants

MONTHS_BY_LANGUAGE: dict[str, dict[str, int]] = {
    "en": {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
    },
    "de": {
    "januar": 1, "februar": 2, "märz": 3, "marz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "sept": 9, "oktober": 10, "okt": 10,
    "november": 11, "nov": 11, "dezember": 12, "dez": 12,
    },
}

MONTHS: dict[str, int] = {
    month: number
    for months in MONTHS_BY_LANGUAGE.values()
    for month, number in months.items()
}

DATE_LINE_RE = re.compile(
    r"^(?P<von_m>[A-Za-zäöüÄÖÜ]+)\s+(?P<von_y>\d{4})\s*[-–—]\s*"
    r"(?P<bis>Present|[A-Za-zäöüÄÖÜ]+\s+\d{4})\s*\(.*\)\s*$",
    re.I,
)

AGGREGATOR_RE = re.compile(r"^\d+\s+\w+(\s+\d+\s+\w+)?\s*$", re.I)

# "(October 2024)" or "(October 2020 - August 2024)"
PAREN_DATE_RE = re.compile(
    r"\((?P<von_m>[A-Za-zäöüÄÖÜ]+)\s+(?P<von_y>\d{4})"
    r"(?:\s*[-–—]\s*(?P<bis_m>[A-Za-zäöüÄÖÜ]+)\s+(?P<bis_y>\d{4}))?\)",
    re.I,
)

# Section markers in the main content area.
SECTION_ALIASES_BY_LANGUAGE = {
    "en": {
        "experience": {"experience", "work experience", "professional experience"},
        "education": {"education"},
        "skills": {"skills", "top skills"},
        "languages": {"languages"},
        "ignored": {"publications", "patents", "honors & awards"},
    },
    "de": {
        "experience": {"berufserfahrung", "erfahrung"},
        "education": {"ausbildung"},
        "skills": {"kenntnisse", "top-kenntnisse"},
        "languages": {"sprachen"},
        "ignored": {"publikationen", "patente", "auszeichnungen"},
    },
}
SECTION_HEADERS = {
    header
    for sections in SECTION_ALIASES_BY_LANGUAGE.values()
    for aliases in sections.values()
    for header in aliases
}

# Degree mapping from profile PDFs to compact labels.
ABSCHLUSS_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Bachelor of Science|\bB\.?Sc\b|\bBSc\b|\bBS\b", re.I), "B.Sc."),
    (re.compile(r"Bachelor of Arts|\bB\.?A\b|\bBA\b", re.I),                "B.A."),
    (re.compile(r"Bachelor of Engineering|\bB\.?Eng\b|\bBEng\b", re.I),     "B.Eng."),
    (re.compile(r"Bachelor of Laws|\bLL\.?B\b|\bLLB\b", re.I),              "LL.B."),
    (re.compile(r"Bachelor of Education|\bB\.?Ed\b|\bBEd\b", re.I),         "B.Ed."),
    (re.compile(r"Master of Science|\bM\.?Sc\b|\bMSc\b|\bMS\b", re.I),      "M.Sc."),
    (re.compile(r"Master of Arts|\bM\.?A\b|\bMA\b", re.I),                  "M.A."),
    (re.compile(r"Master of Laws|\bLL\.?M\b|\bLLM\b", re.I),                "LL.M."),
    (re.compile(r"Master of Education|\bM\.?Ed\b|\bMEd\b", re.I),           "M.Ed."),
    (re.compile(r"Master of Business Administration|\bMBA\b", re.I),         "MBA"),
]

# Derive experience type from the job title.
ART_KEYWORDS_BY_LANGUAGE: dict[str, list[tuple[str, str]]] = {
    "en": [
        ("working student", "working_student"),
        ("internship", "internship"),
        ("intern", "internship"),
        ("freelance", "freelance"),
        ("freelancer", "freelance"),
        ("full-time", "full_time"),
        ("full time", "full_time"),
    ],
    "de": [
        ("werkstudent", "working_student"),
        ("praktikum", "internship"),
        ("freelance", "freelance"),
        ("freelancer", "freelance"),
        ("vollzeit", "full_time"),
    ],
}


def _normalize_language(language: str) -> Language:
    if language not in {"auto", "de", "en"}:
        raise ValueError("language must be one of: auto, de, en")
    return language  # type: ignore[return-value]


def _language_order(language: Language) -> list[str]:
    if language == "auto":
        return ["en", "de"]
    other = "en" if language == "de" else "de"
    return [language, other]


def _month_lookup(language: Language) -> dict[str, int]:
    if language == "auto":
        return MONTHS
    return MONTHS_BY_LANGUAGE[language]


def _detect_language(sidebar_text: str, main_text: str) -> Literal["de", "en"]:
    text = f"{sidebar_text}\n{main_text}".lower()
    de_hits = sum(1 for token in ("berufserfahrung", "ausbildung", "kenntnisse", "sprachen", "kontakt") if token in text)
    en_hits = sum(1 for token in ("experience", "education", "skills", "languages", "contact") if token in text)
    return "de" if de_hits > en_hits else "en"


def _sidebar_section(line: str, language: Language) -> Optional[str]:
    low = line.lower().rstrip(":")
    if low in {"kontakt", "contact"}:
        return "contact"
    for lang in _language_order(language):
        aliases = SECTION_ALIASES_BY_LANGUAGE[lang]
        if low in aliases["skills"]:
            return "skills"
        if low in aliases["languages"]:
            return "languages"
    return None


# PDF to text

def _extract_columns(pdf_bytes: bytes) -> tuple[str, str]:
    """Read PDF bytes and return (sidebar_text, main_text) across all pages."""
    sidebar_parts: list[str] = []
    main_parts: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            split = page.width * 0.30
            words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
            sidebar_parts.append(_words_to_text([w for w in words if w["x1"] <= split]))
            main_parts.append(_words_to_text([w for w in words if w["x0"] >= split]))
    return "\n".join(sidebar_parts), "\n".join(main_parts)


def _words_to_text(words: list[dict]) -> str:
    """Group extracted words into text lines by y coordinate."""
    if not words:
        return ""
    lines: list[list[dict]] = []
    current: list[dict] = []
    current_y: Optional[float] = None
    for w in sorted(words, key=lambda x: (round(x["top"], 1), x["x0"])):
        y = round(w["top"], 1)
        if current_y is None or abs(y - current_y) <= 2.0:
            current.append(w)
            current_y = y
        else:
            lines.append(current)
            current = [w]
            current_y = y
    if current:
        lines.append(current)
    return "\n".join(" ".join(w["text"] for w in line) for line in lines)


def _clean_lines(text: str) -> list[str]:
    """Trim empty lines and remove page footers."""
    return [
        l.strip() for l in text.split("\n")
        if l.strip() and not re.match(r"^Page \d+ of \d+$", l.strip(), re.I)
    ]


# Sidebar parser

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
LINKEDIN_URL_RE = re.compile(r"(www\.)?linkedin\.com/(in/[A-Za-z0-9\-_/]+)", re.I)


def _parse_sidebar(text: str, language: Language = "auto") -> dict:
    """Extract email, profile URL, skills, and languages from the sidebar."""
    lines = _clean_lines(text)
    # Find sidebar sections via German/English headers.
    sections: dict[str, list[str]] = {}
    current = None
    for line in lines:
        section = _sidebar_section(line, language)
        if section:
            current = section
            sections[current] = []
            continue
        if current:
            sections[current].append(line)

    out: dict = {"email": None, "linkedin": None, "skills": [], "languages": []}

    # Extract email from individual lines.
    for line in sections.get("contact", []):
        if not out["email"]:
            m = EMAIL_RE.search(line)
            if m:
                out["email"] = m.group(0)
                break

    # Profile URLs often wrap across PDF lines, so join the entire contact section.
    joined = re.sub(r"\s+", "", " ".join(sections.get("contact", [])))
    m = LINKEDIN_URL_RE.search(joined)
    if m:
        url = m.group(0).rstrip("/").rstrip("-")
        out["linkedin"] = "https://" + url

    for line in sections.get("skills", []):
        line = line.strip()
        if line:
            out["skills"].append(line)

    for line in sections.get("languages", []):
        m = re.match(r"^(.+?)\s*\((.+)\)\s*$", line)
        if m:
            out["languages"].append({"name": m.group(1).strip(), "level": m.group(2).strip()})
        elif line:
            out["languages"].append({"name": line, "level": None})

    return out


# Main parser

def _parse_header(lines: list[str]) -> dict:
    """Parse the first profile lines into name, headline, and location."""
    out = {"name": None, "headline": None, "location": None}
    if len(lines) >= 1:
        out["name"] = lines[0]
    if len(lines) >= 2:
        out["headline"] = lines[1]
    if len(lines) >= 3:
        for i in range(1, min(len(lines), 4)):
            if re.search(r",\s*(Deutschland|Germany|Österreich|Austria|Schweiz|Switzerland)$", lines[i], re.I):
                out["location"] = lines[i]
                out["headline"] = " ".join(lines[1:i]).strip()
                break
    return out


def _is_section_header(line: str, language: Language = "auto") -> Optional[str]:
    low = line.lower().rstrip(":")
    if low in SECTION_HEADERS:
        for lang in _language_order(language):
            for canonical, aliases in SECTION_ALIASES_BY_LANGUAGE[lang].items():
                if low in aliases:
                    return canonical if canonical != "ignored" else low
        return low
    return None


def _split_main_sections(lines: list[str], language: Language = "auto") -> dict[str, list[str]]:
    """Split main text into sections by section headers."""
    sections: dict[str, list[str]] = {"header": [], "experience": [], "education": []}
    current = "header"
    for line in lines:
        sec = _is_section_header(line, language)
        if sec is not None:
            current = sec
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


# Experience

def _parse_date_range(line: str, language: Language = "auto") -> tuple[Optional[date], Optional[date], bool]:
    """Parse a date range line such as 'January 2026 - Present (5 months)'."""
    m = DATE_LINE_RE.match(line)
    if not m:
        return None, None, False
    months = _month_lookup(language)
    von_m = months.get(m.group("von_m").lower())
    von_y = int(m.group("von_y"))
    von_d = date(von_y, von_m, 1) if von_m else None
    bis_raw = m.group("bis")
    if bis_raw.lower().startswith("present"):
        return von_d, None, True
    bm = re.match(r"^([A-Za-zäöüÄÖÜ]+)\s+(\d{4})$", bis_raw)
    if bm:
        bis_mn = months.get(bm.group(1).lower())
        if bis_mn:
            return von_d, date(int(bm.group(2)), bis_mn, 1), False
    return von_d, None, False


def _derive_art(position: str, language: Language = "auto") -> str:
    p = (position or "").lower()
    for lang in _language_order(language):
        for kw, art in ART_KEYWORDS_BY_LANGUAGE[lang]:
            if kw in p:
                return art
    return "other"


def _parse_experiences(lines: list[str], language: Language = "auto") -> list[dict]:
    """Parse work experience lines using date rows as anchors."""
    out: list[dict] = []
    last_company: Optional[str] = None
    i = 0

    while i < len(lines):
        if _is_section_header(lines[i], language):
            i += 1
            continue

        date_idx: Optional[int] = None
        for j in range(i, min(i + 8, len(lines))):
            if DATE_LINE_RE.match(lines[j]):
                date_idx = j
                break

        if date_idx is None:
            break

        block = lines[i:date_idx]

        if len(block) >= 2 and AGGREGATOR_RE.match(block[1]):
            company = block[0]
            position_lines = block[2:]
            last_company = company
        elif len(block) >= 1 and AGGREGATOR_RE.match(block[0]):
            company = last_company
            position_lines = block[1:]
        elif last_company and len(block) == 1:
            company = last_company
            position_lines = block
        else:
            company = block[0] if block else None
            position_lines = block[1:] if len(block) > 1 else []
            last_company = company

        date_line = lines[date_idx]
        location = lines[date_idx + 1] if date_idx + 1 < len(lines) else ""

        position = " ".join(position_lines).strip()
        von, bis, aktuell = _parse_date_range(date_line, language)

        out.append({
            "company":     company,
            "position":    position,
            "start_date":  von.isoformat() if von else None,
            "end_date":    bis.isoformat() if bis else None,
            "current":     aktuell,
            "location":    location,
            "type":        _derive_art(position, language),
            "raw_date":    date_line,
        })

        i = date_idx + 2

    return out


# Education

def _parse_abschluss(text: str) -> Optional[str]:
    for pat, target in ABSCHLUSS_MAP:
        if pat.search(text):
            return target
    return None


def _parse_education(lines: list[str], language: Language = "auto") -> list[dict]:
    """Parse education entries."""
    out: list[dict] = []
    i = 0
    while i < len(lines):
        if _is_section_header(lines[i], language):
            i += 1; continue
        uni = lines[i]
        details = lines[i + 1] if i + 1 < len(lines) else ""
        i += 2

        date_match = PAREN_DATE_RE.search(details)
        von = bis = None
        if date_match:
            months = _month_lookup(language)
            vm = months.get(date_match.group("von_m").lower())
            vy = int(date_match.group("von_y"))
            if vm:
                von = date(vy, vm, 1)
            bm = date_match.group("bis_m")
            by = date_match.group("bis_y")
            if bm and by:
                bm_n = months.get(bm.lower())
                if bm_n:
                    bis = date(int(by), bm_n, 1)

        head = re.split(r"\s*[·•]\s*|\s*\(", details, maxsplit=1)[0].strip()
        abschluss = _parse_abschluss(head)
        studiengang = head
        if "," in head:
            parts = [p.strip() for p in head.split(",", maxsplit=1)]
            if abschluss and abschluss != parts[0]:
                studiengang = parts[1]
            elif not abschluss:
                studiengang = head

        out.append({
            "institution": uni,
            "degree":      abschluss,
            "field":       studiengang,
            "start_year":  von.year if von else None,
            "end_year":    bis.year if bis else None,
            "raw_details": details,
        })

    return out


# Location

def _parse_location(loc: str) -> dict:
    """Parse 'City, Region, Country' into structured parts."""
    parts = [p.strip() for p in (loc or "").split(",")]
    return {
        "city":    parts[0] if len(parts) >= 1 else None,
        "region":  parts[1] if len(parts) >= 2 else None,
        "country": parts[2] if len(parts) >= 3 else None,
    }


# Public API

def parse_profile_pdf(pdf_bytes: bytes, language: Language = "auto") -> dict:
    """Parse profile PDF bytes into structured data with English keys.

    Args:
        pdf_bytes: PDF file content.
        language: CV/profile PDF language. Use "de", "en", or "auto".
    """
    language = _normalize_language(language)
    sidebar_text, main_text = _extract_columns(pdf_bytes)
    effective_language: Language = _detect_language(sidebar_text, main_text) if language == "auto" else language
    sidebar = _parse_sidebar(sidebar_text, effective_language)

    main_lines = _clean_lines(main_text)
    sections = _split_main_sections(main_lines, effective_language)
    header = _parse_header(sections.get("header", []))

    return {
        "contact": {
            "email":    sidebar["email"],
            "profile_url": sidebar["linkedin"],
        },
        "person": {
            "name":     header["name"],
            "headline": header["headline"],
            "location": _parse_location(header["location"] or ""),
        },
        "skills":     sidebar["skills"],
        "languages":  sidebar["languages"],
        "experience": _parse_experiences(sections.get("experience", []), effective_language),
        "education":  _parse_education(sections.get("education", []), effective_language),
    }


def _legacy_experience(entry: dict) -> dict:
    return {
        "company": entry.get("company"),
        "position": entry.get("position"),
        "von": entry.get("start_date"),
        "bis": entry.get("end_date"),
        "aktuell": entry.get("current", False),
        "location": entry.get("location"),
        "art": {
            "working_student": "werkstudent",
            "internship": "praktikum",
            "full_time": "vollzeit",
            "freelance": "freelance",
            "other": "sonstiges",
        }.get(entry.get("type"), entry.get("type")),
        "raw_date": entry.get("raw_date"),
    }


def _legacy_education(entry: dict) -> dict:
    return {
        "universitaet": entry.get("institution"),
        "abschluss": entry.get("degree"),
        "studiengang": entry.get("field"),
        "von_jahr": entry.get("start_year"),
        "bis_jahr": entry.get("end_year"),
        "raw_details": entry.get("raw_details"),
    }


def _legacy_location(location: dict) -> dict:
    return {
        "stadt": location.get("city"),
        "bundesland": location.get("region"),
        "land": location.get("country"),
    }


def to_legacy_dict(parsed: dict) -> dict:
    """Convert the English output shape to the original German-keyed structure."""
    return {
        "kontakt": {
            "email": parsed.get("contact", {}).get("email"),
            "linkedin": parsed.get("contact", {}).get("profile_url"),
        },
        "person": {
            "name": parsed.get("person", {}).get("name"),
            "headline": parsed.get("person", {}).get("headline"),
            "location": _legacy_location(parsed.get("person", {}).get("location", {}) or {}),
        },
        "skills": parsed.get("skills", []),
        "languages": parsed.get("languages", []),
        "berufserfahrung": [_legacy_experience(e) for e in parsed.get("experience", [])],
        "ausbildung": [_legacy_education(e) for e in parsed.get("education", [])],
    }


def parse_linkedin_pdf(pdf_bytes: bytes, language: Language = "auto") -> dict:
    """Backward-compatible parser returning the original German-keyed structure."""
    return to_legacy_dict(parse_profile_pdf(pdf_bytes, language=language))
