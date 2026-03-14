# Krankenhausbrand-Monitor Deutschland

Automatische Überwachung und Aufbereitung von Brandereignissen in deutschen Krankenhäusern.

## Architektur

```
RSS-Feeds (6 Quellen)
       │
       ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  monitor.py  │────▶│  enrich.py   │────▶│ braende.json │
│  (Crawler)   │     │ (Claude API) │     │  (Datenbank) │
└──────────────┘     └──────────────┘     └──────────────┘
       │                    │
       │              Claude Haiku API
       │              (Steckbrief-Extraktion)
       ▼
  GitHub Actions (stündlich)
```

## Komponenten

### 1. Crawler (`monitor.py`)
- Parst 6 RSS-Feeds: Presseportal (Feuerwehr/Blaulicht), 3× Google News, Feuerwehrmagazin
- Filtert nach Keyword-Kombination (Krankenhaus + Brand)
- Dedupliziert per MD5-Hash
- Speichert Rohtreffer in `data/braende.json`

### 2. Enrichment (`enrich.py`)
- Fetcht Artikel-Volltext (requests + BeautifulSoup)
- Fallback-Kaskade: HTML-Body → `<article>` → `<p>`-Tags → `<meta>`-Tags → RSS-Snippet
- Claude Haiku API extrahiert strukturierten Steckbrief
- Felder: Einrichtung, Ort, PLZ, Bundesland, Datum, Brandursache, Brandort, Verletzte, Tote, Evakuierung, Sachschaden, Feuerwehreinsatz
- Status pro Eintrag: `enriched`, `partial`, `failed`
- Max. 5 Enrichments pro Lauf (konfigurierbar)

### 3. Datenbank (`data/braende.json`)
- JSON-Datei, versioniert im Git-Repo
- Schema v2.0 mit Steckbrief-Substruktur
- Automatischer Commit nach jedem Lauf

## Setup

### 1. Repository erstellen
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/DEIN-USER/kh-brand-monitor.git
git push -u origin main
```

### 2. GitHub Secrets konfigurieren
Repository → Settings → Secrets and variables → Actions → New repository secret

| Secret | Pflicht | Wert |
|--------|---------|------|
| `ANTHROPIC_API_KEY` | ✅ Ja | Dein Anthropic API Key |
| `NOTIFY_EMAIL` | Optional | Empfänger-Adresse |
| `SMTP_SERVER` | Optional | z.B. `smtp.gmail.com` |
| `SMTP_PORT` | Optional | z.B. `587` |
| `SMTP_USER` | Optional | Absender-Adresse |
| `SMTP_PASS` | Optional | App-Passwort |

### 3. Erster Lauf
Actions → Krankenhausbrand-Monitor → Run workflow (manueller Trigger)

## Datenformat

```json
{
  "datum": "13.03.2026",
  "einrichtung": "Klinikum Musterstadt",
  "ort": "Musterstadt",
  "titel": "FW-MS: Brand im Klinikum Musterstadt",
  "zusammenfassung": "Am Mittwochabend brach ein Feuer...",
  "verletzte": "3 Leichtverletzte",
  "quelle": "presseportal_feuerwehr",
  "link": "https://www.presseportal.de/...",
  "erfasst_am": "2026-03-13 14:17:00",
  "enrichment_status": "enriched",
  "enriched_am": "2026-03-13 14:17:05",
  "artikel_laenge": 2340,
  "steckbrief": {
    "einrichtung": "Klinikum Musterstadt",
    "ort": "Musterstadt",
    "plz": "48149",
    "bundesland": "Nordrhein-Westfalen",
    "datum": "12.03.2026",
    "brandursache": "Technischer Defekt",
    "brandort": "Patientenzimmer 3. OG",
    "verletzte": "3 Leichtverletzte (Rauchvergiftung)",
    "tote": "keine",
    "evakuierung": "ja, 45 Patienten",
    "sachschaden": "ca. 200.000 EUR",
    "feuerwehr_einsatz": "4 Löschzüge, 60 Einsatzkräfte, 2 Stunden",
    "zusammenfassung": "Am Abend des 12. März brach im Patientenzimmer..."
  }
}
```

## Kosten (monatlich)

| Posten | Kosten |
|--------|--------|
| GitHub Actions | 0 € (Free Tier, ~750 von 2.000 Min.) |
| Claude API (Haiku) | ~0,50 € (~10 Fälle × ~4K Tokens) |
| **Gesamt** | **~0,50 €/Monat** |

## Lokaler Test

```bash
pip install -r requirements.txt
python monitor.py                          # Nur Crawler
ANTHROPIC_API_KEY=sk-... python enrich.py  # Nur Enrichment
```
