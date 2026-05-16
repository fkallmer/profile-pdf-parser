"""
Parser für LinkedIn-Profil-PDF-Exports.

LinkedIn-PDFs haben ein 2-Spalten-Layout:
- Sidebar (links, ~28% Breite): Kontakt, Top-Kenntnisse, Languages
- Main (rechts): Name + Headline + Berufserfahrung + Ausbildung

Wir extrahieren reines Text, gruppieren nach Sektion via Keyword-Ankern und parsen
mit Regex. Ergebnis ist ein Dict mit Vorschlägen, das im Frontend kuratiert wird.
"""

import io
import re
from datetime import date
from typing import Optional

import pdfplumber


# ── Konstanten ────────────────────────────────────────────────────────────────

MONTHS_DE: dict[str, int] = {
    "januar": 1, "februar": 2, "märz": 3, "marz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "sept": 9, "oktober": 10, "okt": 10,
    "november": 11, "nov": 11, "dezember": 12, "dez": 12,
}

DATE_LINE_RE = re.compile(
    r"^(?P<von_m>[A-Za-zäöüÄÖÜ]+)\s+(?P<von_y>\d{4})\s*[-–—]\s*"
    r"(?P<bis>Present|[A-Za-zäöüÄÖÜ]+\s+\d{4})\s*\(.*\)\s*$",
    re.I,
)

AGGREGATOR_RE = re.compile(
    r"^\d+\s+(Monate?|Jahre?)(\s+\d+\s+Monate?)?\s*$",
    re.I,
)

# "(Oktober 2024)" oder "(Oktober 2020 - August 2024)"
PAREN_DATE_RE = re.compile(
    r"\((?P<von_m>[A-Za-zäöüÄÖÜ]+)\s+(?P<von_y>\d{4})"
    r"(?:\s*[-–—]\s*(?P<bis_m>[A-Za-zäöüÄÖÜ]+)\s+(?P<bis_y>\d{4}))?\)",
    re.I,
)

# Section-Marker im Main-Bereich
SECTION_HEADERS = {"berufserfahrung", "ausbildung", "kenntnisse", "publikationen", "patente", "auszeichnungen"}

# Abschluss-Mapping LinkedIn → unsere Werte
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

# Erfahrungs-Typ aus Position ableiten
ART_KEYWORDS: list[tuple[str, str]] = [
    ("werkstudent", "werkstudent"),
    ("working student", "werkstudent"),
    ("praktikum", "praktikum"),
    ("intern", "praktikum"),
    ("internship", "praktikum"),
    ("freelance", "freelance"),
    ("freelancer", "freelance"),
    ("vollzeit", "vollzeit"),
    ("full-time", "vollzeit"),
]


# ── PDF → Text ────────────────────────────────────────────────────────────────

def _extract_columns(pdf_bytes: bytes) -> tuple[str, str]:
    """Liest das PDF und gibt (sidebar_text, main_text) über alle Seiten zurück.

    Verwendet `extract_words()` mit strikter x-Filterung, damit Sidebar-Fragmente
    (LinkedIn-URL-Brüche etc.) nicht in den Main-Bereich bluten.
    """
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
    """Gruppiert Wörter nach Zeile (y-Koordinate) und gibt Text zurück."""
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
    """Trimmt + entfernt leere Zeilen + Page-Footer."""
    return [
        l.strip() for l in text.split("\n")
        if l.strip() and not re.match(r"^Page \d+ of \d+$", l.strip(), re.I)
    ]


# ── Sidebar-Parser ────────────────────────────────────────────────────────────

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
LINKEDIN_URL_RE = re.compile(r"(www\.)?linkedin\.com/(in/[A-Za-z0-9\-_/]+)", re.I)


def _parse_sidebar(text: str) -> dict:
    """Extrahiert Email, LinkedIn-URL, Skills, Sprachen aus der Sidebar."""
    lines = _clean_lines(text)
    # Sidebar-Sektionen finden über deutsche/englische Header
    sections: dict[str, list[str]] = {}
    current = None
    for line in lines:
        low = line.lower().rstrip(":")
        if low in {"kontakt", "contact"}:
            current = "kontakt"; sections[current] = []; continue
        if low in {"top-kenntnisse", "kenntnisse", "top skills", "skills"}:
            current = "skills"; sections[current] = []; continue
        if low in {"languages", "sprachen"}:
            current = "sprachen"; sections[current] = []; continue
        if current:
            sections[current].append(line)

    out: dict = {"email": None, "linkedin": None, "skills": [], "languages": []}

    # Email aus einzelnen Zeilen extrahieren
    for line in sections.get("kontakt", []):
        if not out["email"]:
            m = EMAIL_RE.search(line)
            if m:
                out["email"] = m.group(0)
                break

    # LinkedIn-URL: ganze Sektion zusammenkleben (URLs werden in PDF oft umgebrochen)
    joined = re.sub(r"\s+", "", " ".join(sections.get("kontakt", [])))
    m = LINKEDIN_URL_RE.search(joined)
    if m:
        url = m.group(0).rstrip("/").rstrip("-")
        out["linkedin"] = "https://" + url

    for line in sections.get("skills", []):
        line = line.strip()
        if line:
            out["skills"].append(line)

    for line in sections.get("sprachen", []):
        # Beispiel: "Französisch (Limited Working)"
        m = re.match(r"^(.+?)\s*\((.+)\)\s*$", line)
        if m:
            out["languages"].append({"name": m.group(1).strip(), "level": m.group(2).strip()})
        elif line:
            out["languages"].append({"name": line, "level": None})

    return out


# ── Main-Parser ───────────────────────────────────────────────────────────────

def _parse_header(lines: list[str]) -> dict:
    """Erste 3 Zeilen: Name, Headline, Standort."""
    out = {"name": None, "headline": None, "location": None}
    if len(lines) >= 1:
        out["name"] = lines[0]
    if len(lines) >= 2:
        out["headline"] = lines[1]
    if len(lines) >= 3:
        # Headline kann sich auf 2 Zeilen erstrecken — Standort enthält typisch ", Deutschland" / ", Germany"
        for i in range(1, min(len(lines), 4)):
            if re.search(r",\s*(Deutschland|Germany|Österreich|Austria|Schweiz|Switzerland)$", lines[i], re.I):
                out["location"] = lines[i]
                # Headline ist alles dazwischen
                out["headline"] = " ".join(lines[1:i]).strip()
                break
    return out


def _is_section_header(line: str) -> Optional[str]:
    low = line.lower().rstrip(":")
    if low in SECTION_HEADERS:
        return low
    return None


def _split_main_sections(lines: list[str]) -> dict[str, list[str]]:
    """Schneidet den Main-Text in Abschnitte anhand der Section-Header."""
    sections: dict[str, list[str]] = {"header": [], "berufserfahrung": [], "ausbildung": []}
    current = "header"
    for line in lines:
        sec = _is_section_header(line)
        if sec is not None:
            current = sec
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


# ── Berufserfahrung ───────────────────────────────────────────────────────────

def _parse_date_range(line: str) -> tuple[Optional[date], Optional[date], bool]:
    """Beispiel: 'Januar 2026 - Present (5 Monate)' → (date(2026,1,1), None, True)."""
    m = DATE_LINE_RE.match(line)
    if not m:
        return None, None, False
    von_m = MONTHS_DE.get(m.group("von_m").lower())
    von_y = int(m.group("von_y"))
    von_d = date(von_y, von_m, 1) if von_m else None
    bis_raw = m.group("bis")
    if bis_raw.lower().startswith("present"):
        return von_d, None, True
    bm = re.match(r"^([A-Za-zäöüÄÖÜ]+)\s+(\d{4})$", bis_raw)
    if bm:
        bis_mn = MONTHS_DE.get(bm.group(1).lower())
        if bis_mn:
            return von_d, date(int(bm.group(2)), bis_mn, 1), False
    return von_d, None, False


def _derive_art(position: str) -> str:
    p = (position or "").lower()
    for kw, art in ART_KEYWORDS:
        if kw in p:
            return art
    return "sonstiges"


def _parse_experiences(lines: list[str]) -> list[dict]:
    """State-Machine über die Berufserfahrungs-Zeilen.

    Jeder Eintrag im LinkedIn-PDF besteht aus:
      [Firmenname]            ← optional bei Multi-Position am gleichen Unternehmen
      [Aggregator z.B. '6 Monate']  ← Marker für Multi-Position
      Position (1-2 Zeilen)
      Datum (matcht DATE_LINE_RE)
      Standort

    Wir suchen die Datum-Zeile als Anker und arbeiten von dort.
    """
    out: list[dict] = []
    last_company: Optional[str] = None
    i = 0

    while i < len(lines):
        # Skip Section-Header (sicherheitshalber)
        if _is_section_header(lines[i]):
            i += 1
            continue

        # Nächste Datum-Zeile suchen (max 8 Zeilen voraus)
        date_idx: Optional[int] = None
        for j in range(i, min(i + 8, len(lines))):
            if DATE_LINE_RE.match(lines[j]):
                date_idx = j
                break

        if date_idx is None:
            break

        block = lines[i:date_idx]

        # Klassifikation:
        if len(block) >= 2 and AGGREGATOR_RE.match(block[1]):
            # block[0] = neuer Firmenname, block[1] = Aggregator, block[2:] = Position
            company = block[0]
            position_lines = block[2:]
            last_company = company
        elif len(block) >= 1 and AGGREGATOR_RE.match(block[0]):
            # Multi-Position Folge-Eintrag ohne neue Firmenzeile
            company = last_company
            position_lines = block[1:]
        elif last_company and len(block) == 1:
            # Nur eine Position-Zeile + last_company gesetzt → gehört zur vorherigen Firma
            company = last_company
            position_lines = block
        else:
            # Neue Firma (block[0]) + Position (block[1:])
            company = block[0] if block else None
            position_lines = block[1:] if len(block) > 1 else []
            last_company = company

        date_line = lines[date_idx]
        location = lines[date_idx + 1] if date_idx + 1 < len(lines) else ""

        position = " ".join(position_lines).strip()
        von, bis, aktuell = _parse_date_range(date_line)

        out.append({
            "company":     company,
            "position":    position,
            "von":         von.isoformat() if von else None,
            "bis":         bis.isoformat() if bis else None,
            "aktuell":     aktuell,
            "location":    location,
            "art":         _derive_art(position),
            "raw_date":    date_line,
        })

        i = date_idx + 2  # nach Datum + Location weiter

    return out


# ── Ausbildung ────────────────────────────────────────────────────────────────

def _parse_abschluss(text: str) -> Optional[str]:
    for pat, target in ABSCHLUSS_MAP:
        if pat.search(text):
            return target
    return None


def _parse_education(lines: list[str]) -> list[dict]:
    """Einträge wie:
        Hochschule Bielefeld
        Bachelor of Science - BS, Mechatronics · (Oktober 2020 - August 2024)
    oder
        Rennes School of Business
        International Business · (September 2025 - Dezember 2025)
    """
    out: list[dict] = []
    i = 0
    while i < len(lines):
        if _is_section_header(lines[i]):
            i += 1; continue
        # Zwei Zeilen pro Eintrag (Uni + Details)
        uni = lines[i]
        details = lines[i + 1] if i + 1 < len(lines) else ""
        i += 2

        # Details aufsplitten: "{Abschluss + Studiengang} · ({Datum})"
        date_match = PAREN_DATE_RE.search(details)
        von = bis = None
        if date_match:
            vm = MONTHS_DE.get(date_match.group("von_m").lower())
            vy = int(date_match.group("von_y"))
            if vm:
                von = date(vy, vm, 1)
            bm = date_match.group("bis_m")
            by = date_match.group("bis_y")
            if bm and by:
                bm_n = MONTHS_DE.get(bm.lower())
                if bm_n:
                    bis = date(int(by), bm_n, 1)

        # Text vor "·" oder vor "(": Abschluss + Studiengang
        head = re.split(r"\s*[·•]\s*|\s*\(", details, maxsplit=1)[0].strip()
        abschluss = _parse_abschluss(head)
        studiengang = head
        # "{Abschluss-Bezeichnung}, {Studiengang}"
        if "," in head:
            parts = [p.strip() for p in head.split(",", maxsplit=1)]
            if abschluss and abschluss != parts[0]:
                # Abschluss steht vorne, Studiengang dahinter
                studiengang = parts[1]
            elif not abschluss:
                # Kein Abschluss erkannt, beide Teile als studiengang verwenden
                studiengang = head

        out.append({
            "universitaet": uni,
            "abschluss":    abschluss,
            "studiengang":  studiengang,
            "von_jahr":     von.year if von else None,
            "bis_jahr":     bis.year if bis else None,
            "raw_details":  details,
        })

    return out


# ── Standort → Stadt + Bundesland ─────────────────────────────────────────────

def _parse_location(loc: str) -> dict:
    """'Lüneburg, Niedersachsen, Deutschland' → {stadt, bundesland, land}"""
    parts = [p.strip() for p in (loc or "").split(",")]
    return {
        "stadt":      parts[0] if len(parts) >= 1 else None,
        "bundesland": parts[1] if len(parts) >= 2 else None,
        "land":       parts[2] if len(parts) >= 3 else None,
    }


# ── Hauptfunktion ─────────────────────────────────────────────────────────────

def parse_linkedin_pdf(pdf_bytes: bytes) -> dict:
    """Hauptfunktion: PDF → strukturierte Daten als Dict."""
    sidebar_text, main_text = _extract_columns(pdf_bytes)
    sidebar = _parse_sidebar(sidebar_text)

    main_lines = _clean_lines(main_text)
    sections = _split_main_sections(main_lines)
    header = _parse_header(sections.get("header", []))

    return {
        "kontakt": {
            "email":    sidebar["email"],
            "linkedin": sidebar["linkedin"],
        },
        "person": {
            "name":     header["name"],
            "headline": header["headline"],
            "location": _parse_location(header["location"] or ""),
        },
        "skills":          sidebar["skills"],
        "languages":       sidebar["languages"],
        "berufserfahrung": _parse_experiences(sections.get("berufserfahrung", [])),
        "ausbildung":      _parse_education(sections.get("ausbildung", [])),
    }
