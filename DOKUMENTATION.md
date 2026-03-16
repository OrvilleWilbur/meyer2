# KH-Brand-Monitor — Vollständige Technische Dokumentation

> **Zweck dieses Dokuments:** Jede Person soll in der Lage sein, das gesamte System zu verstehen, nachzubauen, zu warten und weiterzuentwickeln — ohne Zugang zu Chat-Verläufen oder mündlichem Wissen.
>
> **Letzte Aktualisierung:** 15.03.2026, 21:00 Uhr
>
> **Pflege-Regel:** Diese Datei wird bei JEDER Änderung am System simultan aktualisiert (gemäß dem Prinzip der atomaren Synchronität).

---

## 1. Projektübersicht

**Was ist das?** Ein vollautomatischer Monitor, der Brandereignisse in deutschen Krankenhäusern aus Nachrichtenquellen erfasst, per KI analysiert und auf einem Web-Dashboard darstellt.

**Wer betreibt es?** Privat betrieben, keine kommerzielle Nutzung.

**Wo läuft es?**

| Komponente | Plattform | URL / Pfad |
|---|---|---|
| Code-Repository | GitHub (public) | `OrvilleWilbur/meyer2` |
| Pipeline (Crawler + Enrichment + Dedup) | GitHub Actions | Cron: stündlich um :17 |
| Website / Dashboard | GitHub Pages | https://orvillewilbur.github.io/meyer2/ |
| API-Proxy (Chat + Schreibzugriff) | Cloudflare Worker | https://meyer2.2025-1f5.workers.dev |
| Datenbank | JSON-Datei im Repo | `data/braende.json` |

**Monatliche Kosten:**

| Posten | Kosten |
|---|---|
| GitHub Actions | 0 € (Free Tier, ~750 von 2.000 Min/Monat) |
| Claude API Enrichment (Haiku) | ~0,50–1,00 € |
| Claude API Chat (Haiku, 30 Fragen/Tag) | ~2,00–3,00 € |
| Cloudflare Worker | 0 € (Free Tier, 100.000 Requests/Tag) |
| GitHub Pages | 0 € |
| **Gesamt** | **~2,50–4,00 €/Monat** |

---

## 2. Architektur

```
RSS-Feeds (11 Quellen)
       │
       ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  monitor.py  │────▶│  enrich.py   │────▶│deduplicate.py│────▶│ braende.json │
│  (Crawler)   │     │ (Claude API) │     │  (Dedup)     │     │  (Datenbank) │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
       │                                         │
  GitHub Actions                          merge_candidates.json
  (stündlich :17)                                │
                                                 ▼
                                    ┌───────────────────────┐
                                    │   docs/index.html     │
                                    │   (GitHub Pages)      │
                                    │   - Dashboard         │
                                    │   - Duplikat-Review   │
                                    │   - Chat (Claude)     │
                                    │   - CSV-Export         │
                                    └───────────────────────┘
                                                 │
                                    Cloudflare Worker (Proxy)
                                    ├── POST /           → Chat (Anthropic API)
                                    ├── POST /candidates → Duplikat-Entscheidungen → GitHub API
                                    └── POST /fp         → "Nicht relevant" → GitHub API
```

### Datenfluss im Detail

1. **monitor.py** parst 11 RSS-Feeds, filtert nach Keyword-Kombination (Krankenhaus + Brand), dedupliziert per MD5-Hash, speichert neue Treffer in `braende.json`
2. **enrich.py** nimmt max. 20 Einträge mit Status `pending`, löst Google News URLs auf, holt Volltexte, schickt sie an Claude Haiku zur Steckbrief-Extraktion und False-Positive-Erkennung
3. **deduplicate.py** vergleicht alle Einträge paarweise (Multi-Property-Scoring), mergt sichere Duplikate automatisch (Score ≥ 0.80), schreibt unsichere Paare (Score 0.45–0.80) in `merge_candidates.json`
4. **Git Commit** — alle Änderungen an `data/` werden automatisch committed und gepusht
5. **Website** liest `braende.json` und `merge_candidates.json` via GitHub Raw-URL, zeigt Dashboard, Duplikat-Review und Chat an

---

## 3. Dateistruktur

```
kh-brand-monitor/
├── .github/
│   └── workflows/
│       └── monitor.yml              # GitHub Actions Workflow
├── data/
│   ├── braende.json                 # Hauptdatenbank (alle Einträge)
│   ├── merge_candidates.json        # Duplikat-Kandidaten (pending/confirmed/rejected)
│   └── monitor.log                  # Laufzeit-Log aller Pipeline-Schritte
├── docs/
│   ├── index.html                   # Website/Dashboard (Single-File SPA)
│   └── cloudflare-worker.js         # Worker-Code (Referenzkopie, deployed auf Cloudflare)
├── monitor.py                       # RSS-Crawler
├── enrich.py                        # LLM-Enrichment + False-Positive-Filter
├── deduplicate.py                   # Duplikat-Zusammenführung
├── reset_false_positives.py         # Hilfsskript: FP-Status zurücksetzen
├── requirements.txt                 # Python-Abhängigkeiten
├── .gitignore                       # Git-Ausschlüsse
├── README.md                        # Kurz-Readme für GitHub
├── DOKUMENTATION.md                 # DIESE DATEI — vollständige Dokumentation
├── SETUP_ANLEITUNG.md               # Schritt-für-Schritt Setup
├── PROJEKTSTAND_260313.md           # Projektstand 13.03.2026
├── PROJEKTSTAND_260315.md           # Projektstand 15.03.2026
├── SESSION_LOG_260313.md            # Session-Log 13.03.
├── SESSION_LOG_260314.md            # Session-Log 14.03.
└── SESSION_LOG_260315.md            # Session-Log 15.03.
```

---

## 4. Komponenten im Detail

### 4.1 Crawler (`monitor.py`)

**Aufgabe:** RSS-Feeds parsen, relevante Artikel filtern, neue Treffer in `braende.json` speichern.

**Feeds (11 Stück):**

| Feed | Typ | Erwartete Einträge |
|---|---|---|
| presseportal_feuerwehr | Presseportal RSS | ~0–5/Lauf |
| presseportal_blaulicht | Presseportal RSS | ~0–5/Lauf |
| gn_brand_krankenhaus | Google News | ~50–60 |
| gn_feuer_krankenhaus | Google News | ~50–60 |
| gn_feuer_klinik | Google News | ~30–40 |
| gn_brand_klinik | Google News | ~40–50 |
| gn_brand_klinikum | Google News | ~30–40 |
| gn_klinikbrand | Google News | ~80–100 |
| gn_feuer_uniklinik | Google News | ~50–60 |
| gn_evakuierung_klinik | Google News | ~40–50 |
| feuerwehrmagazin | Feuerwehrmagazin RSS | ~10 |

**Keyword-Filter:** 37 Einrichtungs-Keywords × 22 Brand-Keywords, 12 Exclude-Keywords

**Deduplizierung:** MD5-Hash über `(titel + link)` — verhindert doppelte Einträge aus verschiedenen Feeds

**Output:** Neue Einträge mit Status `pending` in `braende.json`

### 4.2 Enrichment (`enrich.py`)

**Aufgabe:** Artikel-Volltexte holen, per Claude Haiku analysieren, Steckbrief extrahieren, False Positives erkennen.

**Ablauf pro Eintrag:**
1. Google News URL auflösen via `googlenewsdecoder` (v1-Methode, ~100% Erfolgsrate)
2. Volltext extrahieren (requests + BeautifulSoup, Fallback-Kaskade: `<article>` → `<p>` → `<meta>` → RSS-Snippet)
3. Claude Haiku API: Prompt mit Volltext → strukturierter Steckbrief + `ist_krankenhausbrand: true/false`
4. Status setzen: `enriched` (Volltext + Steckbrief), `partial` (nur Snippet), `false_positive` (kein KH-Brand), `failed` (technischer Fehler)

**Rate-Limiting:** Max. 20 Enrichments pro Pipeline-Lauf (konfigurierbar via `MAX_ENRICH_PER_RUN`)

**LLM:** `claude-haiku-4-5-20251001` (günstigstes Modell, ausreichend für Steckbrief-Extraktion)

**False-Positive-Erkennung:** Im Claude-Prompt integriert. Typische FP-Fälle:
- Wohnungsbrand, Person kommt ins KH zur Behandlung
- Brand im Ausland, deutsches KH nimmt Opfer auf
- Militärische Aktion an KH (Gaza etc.)
- Brand in Hotel/Schule/Heim, nicht in KH

**Trefferquote:** ~60% echte Krankenhausbrände, ~40% korrekte FP-Erkennung

### 4.3 Duplikaterkennung (`deduplicate.py`)

**Aufgabe:** Gleiche Brand-Ereignisse aus verschiedenen Quellen zusammenführen.

**Scoring-Modell (Multi-Property, gewichtet):**

| Eigenschaft | Gewicht | Vergleichsmethode |
|---|---|---|
| Datum | 0.30 | Exakt=1.0, ±1 Tag=0.7, ±2 Tage=0.3 |
| Ort | 0.30 | Jaccard auf normalisierte Wörter, Substring-Boost |
| Einrichtung | 0.25 | Jaccard auf normalisierte Wörter, Substring-Boost |
| Bundesland | 0.10 | Exakt-Match |
| Brandort | 0.05 | Jaccard auf normalisierte Wörter |

**Normalisierung:** Lowercase, Unicode-NFC, Kompositwörter aufbrechen ("Marienkrankenhaus" → "Marien Krankenhaus"), Synonyme ("Klinikum" → "Klinik", "Krankenhaus" → "KH")

**Schwellenwerte:**
- Score ≥ 0.80: **Auto-Merge** (sofort zusammenführen)
- Score 0.45–0.80: **Kandidat** (in `merge_candidates.json` zur manuellen Prüfung)
- Score < 0.45: **Kein Duplikat** (ignorieren)

**Optimierung:** Vorab-Gruppierung nach Bundesland + Datum-Monat (vermeidet O(n²))

**Merge-Logik bei Zusammenführung:**
- Bester Status gewinnt (enriched > partial > pending > failed > false_positive)
- Steckbriefe werden feldweise gemergt (bester Wert pro Feld)
- Quellen-Array sammelt alle Links
- Audit-Trail über `merged_from`-Array (Original-Hashes)

**Nutzer-Entscheidungen:**
- `merge_candidates.json` enthält drei Listen: `pending`, `confirmed`, `rejected`
- Bestätigte Paare werden beim nächsten Lauf automatisch gemergt
- Abgelehnte Paare werden dauerhaft übersprungen

### 4.4 Website (`docs/index.html`)

**Typ:** Single-File SPA (Single Page Application), kein Build-Step, kein Framework

**Hosting:** GitHub Pages, Serving aus `/docs` auf Branch `main`

**URL:** https://orvillewilbur.github.io/meyer2/

**Authentifizierung:** Client-seitige SHA-256 Passwort-Prüfung (Hash: `d271d50b...`, Passwort: `ppg`)

**Design (Stand 15.03.2026):**
- Dark Theme (Off-Black #0a0a0f, Glassmorphism, Bento Grid)
- Inter Font (Google Fonts)
- Responsive (Desktop + Mobile)
- Micro-Interactions (Hover-Glow, Slide-Up-Modals, Transitions)

**Funktionen:**

| Tab | Funktion |
|---|---|
| **Dashboard** | Tabelle aller Einträge mit Filtern (Status, Bundesland, Freitext), Sortierung, "Nicht relevant"-Button pro Zeile, CSV-Export, Detail-Modal bei Klick |
| **Duplikate** | Kandidaten-Karten mit Score, Quell-Links, "Zusammenführen"/"Kein Duplikat"-Buttons. Debounced Sync (2s) an Worker |
| **Chat** | Freitext-Fragen an Claude Haiku über die Datenbank. 30 Fragen/Tag Limit. Kontext: alle enriched Einträge |

**Datenquellen (Client-seitig):**
- `https://raw.githubusercontent.com/OrvilleWilbur/meyer2/main/data/braende.json`
- `https://raw.githubusercontent.com/OrvilleWilbur/meyer2/main/data/merge_candidates.json`

**Proxy-URL:** `https://meyer2.2025-1f5.workers.dev` (konfigurierbar via "Proxy konfigurieren"-Button, gespeichert in localStorage)

### 4.5 Cloudflare Worker (`docs/cloudflare-worker.js`)

**Aufgabe:** API-Proxy für die Website (hält API-Keys serverseitig)

**Drei Endpoints:**

| Endpoint | Methode | Funktion |
|---|---|---|
| `POST /` | Chat-Proxy | Leitet Anfrage an Anthropic API weiter, fügt `x-api-key` hinzu |
| `POST /candidates` | Duplikat-Entscheidungen | Liest `merge_candidates.json` von GitHub (inkl. SHA), fügt confirmed/rejected hinzu, entfernt aus pending, schreibt zurück via GitHub Contents API |
| `POST /fp` | "Nicht relevant" markieren | Liest `braende.json` von GitHub, findet Eintrag per Hash, setzt `enrichment_status: "false_positive"`, schreibt zurück |

**Environment Variables (auf Cloudflare):**

| Variable | Wert |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API Key (`sk-ant-...`) |
| `GITHUB_TOKEN` | GitHub Personal Access Token (repo scope) |

**CORS:** `Access-Control-Allow-Origin: *` (Public Repo, kein Credentials-Austausch)

**Worker-Name auf Cloudflare:** `meyer2`

**Deployment:** dash.cloudflare.com → Workers & Pages → `meyer2` → Edit Code → Deploy

---

## 5. Datenmodell

### 5.1 braende.json

```json
{
  "entries": [
    {
      "hash": "md5-hash-des-titels-und-links",
      "titel": "Artikeltitel aus RSS",
      "link": "Original-URL aus RSS-Feed",
      "resolved_url": "Aufgelöste Ziel-URL (nach Google News Redirect)",
      "resolve_method": "googlenewsdecoder_v1",
      "quelle": "feed-name",
      "source_url": "RSS-Feed-URL",
      "einrichtung": "Name (aus RSS-Titel extrahiert)",
      "ort": "Ort (aus RSS-Titel extrahiert)",
      "datum": "TT.MM.JJJJ",
      "erfasst_am": "JJJJ-MM-TT HH:MM:SS",
      "enriched_am": "JJJJ-MM-TT HH:MM:SS",
      "enrichment_status": "enriched|partial|pending|failed|false_positive",
      "false_positive_grund": "Begründung (nur bei FP)",
      "artikel_laenge": 3500,
      "steckbrief": {
        "ist_krankenhausbrand": true,
        "einrichtung": "Vollständiger Name",
        "ort": "Stadt",
        "plz": "12345",
        "bundesland": "Bundesland",
        "datum": "TT.MM.JJJJ",
        "brandursache": "...",
        "brandort": "...",
        "verletzte": "...",
        "tote": "...",
        "evakuierung": "...",
        "sachschaden": "...",
        "feuerwehr_einsatz": "...",
        "zusammenfassung": "2-3 Sätze"
      },
      "quellen": [
        {
          "link": "url",
          "quelle": "feed-name",
          "titel": "...",
          "source_url": "...",
          "enrichment_status": "..."
        }
      ],
      "merged_from": ["hash1", "hash2"]
    }
  ]
}
```

### 5.2 merge_candidates.json

```json
{
  "generated_at": "ISO-Timestamp",
  "auto_merge_threshold": 0.80,
  "candidate_min_threshold": 0.45,
  "pending": [
    {
      "hashes": ["hash_a", "hash_b"],
      "score": 0.65,
      "details": { "datum": 1.0, "ort": 0.85, "einrichtung": 0.4, "bundesland": 1.0, "brandort": 0.0, "total": 0.65 },
      "entry_a": { "einrichtung": "...", "ort": "...", "datum": "...", "bundesland": "...", "status": "...", "link": "...", "titel": "..." },
      "entry_b": { "einrichtung": "...", "ort": "...", "datum": "...", "bundesland": "...", "status": "...", "link": "...", "titel": "..." }
    }
  ],
  "confirmed": [
    { "hashes": [...], "score": 0.7, "decided_at": "...", "entry_a_name": "...", "entry_b_name": "..." }
  ],
  "rejected": [
    { "hashes": [...], "score": 0.5, "decided_at": "...", "entry_a_name": "...", "entry_b_name": "..." }
  ]
}
```

---

## 6. GitHub Actions Workflow

**Datei:** `.github/workflows/monitor.yml`

**Trigger:** Cron `17 * * * *` (stündlich um :17) + manueller Trigger (`workflow_dispatch`)

**Schritte:**
1. `actions/checkout@v4` — Repo auschecken
2. `actions/setup-python@v5` — Python 3.11
3. `pip install -r requirements.txt` — Abhängigkeiten
4. `python monitor.py` — Crawler
5. `python enrich.py` — Enrichment (max. 20/Lauf)
6. `python deduplicate.py` — Duplikat-Zusammenführung
7. `git add data/ && git commit && git push` — Änderungen committen

**Secrets (im Repo konfiguriert):**

| Secret | Pflicht | Verwendung |
|---|---|---|
| `ANTHROPIC_API_KEY` | Ja | enrich.py (Claude Haiku API) |
| `NOTIFY_EMAIL` | Nein | E-Mail bei neuen Funden |
| `SMTP_SERVER` | Nein | SMTP für E-Mail |
| `SMTP_PORT` | Nein | SMTP Port |
| `SMTP_USER` | Nein | SMTP Login |
| `SMTP_PASS` | Nein | SMTP Passwort |

---

## 7. Cloudflare Worker Setup

### Erstmalige Einrichtung

1. https://dash.cloudflare.com → Account erstellen (Free)
2. Workers & Pages → Create Worker
3. Name: `meyer2` (oder beliebig)
4. Code aus `docs/cloudflare-worker.js` einfügen
5. Deploy
6. Settings → Variables → Environment Variables hinzufügen:
   - `ANTHROPIC_API_KEY` = dein Anthropic API Key
   - `GITHUB_TOKEN` = GitHub Personal Access Token (Scope: `repo`)

### GitHub Token erstellen

1. https://github.com/settings/tokens → "Generate new token (classic)"
2. Scope: `repo` (Full control of private repositories)
3. Token kopieren → als `GITHUB_TOKEN` im Worker eintragen

### Worker aktualisieren

1. dash.cloudflare.com → Workers & Pages → `meyer2`
2. Edit Code → Alles ersetzen → Deploy

---

## 8. GitHub Pages Setup

1. Repo → Settings → Pages
2. Source: "Deploy from a branch"
3. Branch: `main`, Ordner: `/docs`
4. Save
5. URL: `https://orvillewilbur.github.io/meyer2/`

**Wichtig:** Das Repo muss **Public** sein für kostenloses GitHub Pages.

---

## 9. Website-Passwort

**Mechanismus:** Client-seitiges SHA-256 Hashing, Vergleich mit gespeichertem Hash

**Aktuelles Passwort:** `ppg`

**Hash:** `d271d50b5c2affae5782b863b299887726f5c731376f9f620efe8cc22c13f7fa`

**Passwort ändern:** In `index.html` die Konstante `PW_HASH` durch den SHA-256-Hash des neuen Passworts ersetzen. Hash generieren z.B. via:
```bash
echo -n "neuespasswort" | shasum -a 256
```

**Sicherheitshinweis:** Dies ist KEIN sicherer Schutz. Der Hash ist im Quellcode sichtbar. Es dient nur als Casual-Access-Barriere, nicht als echte Authentifizierung.

---

## 10. Bedienungsanleitung Website

### Dashboard
- **Filter:** Status-Dropdown, Bundesland-Dropdown, Freitextsuche
- **Sortierung:** Klick auf Spaltenüberschrift (↕)
- **Detail-Ansicht:** Klick auf eine Zeile öffnet Modal mit vollständigem Steckbrief und Quellen-Links
- **"Nicht relevant" markieren:** Roter Button in der Aktion-Spalte. Setzt den Eintrag sofort auf `false_positive` und schreibt das über den Worker direkt in `braende.json`
- **CSV-Export:** Button "⬇ CSV" neben der Suche. Exportiert die aktuell gefilterte Ansicht als CSV (Semikolon-getrennt, UTF-8 mit BOM für Excel-Kompatibilität)

### Duplikate
- **Kandidaten-Karten:** Zeigen zwei Einträge nebeneinander mit Übereinstimmungs-Score
- **"Quelle prüfen":** Link zum Original-Artikel (falls vorhanden)
- **"Zusammenführen":** Markiert das Paar als bestätigtes Duplikat → wird beim nächsten Pipeline-Lauf gemergt
- **"Kein Duplikat":** Markiert das Paar als kein Duplikat → wird dauerhaft übersprungen
- **Sync:** Entscheidungen werden nach 2 Sekunden Inaktivität gebündelt an den Worker gesendet

### Chat
- **Freitext-Fragen:** z.B. "Wie viele Brände gab es in NRW?", "Welche Einrichtung hatte die meisten Vorfälle?"
- **Kontext:** Alle enriched Einträge werden als Datenkontext mitgesendet
- **Limit:** 30 Fragen pro Tag (Reset um Mitternacht)
- **Proxy:** Muss konfiguriert sein (Standard: `https://meyer2.2025-1f5.workers.dev`)

---

## 11. Entwicklungshistorie

### Session 13.03.2026
- Projekt initiiert
- `monitor.py` erstellt (6 RSS-Feeds)
- `enrich.py` erstellt (v1, 5 Enrichments/Lauf)
- Erste Daten in `braende.json`
- GitHub Repo `OrvilleWilbur/meyer2` erstellt

### Session 14.03.2026
- Feeds auf 11 erweitert (Google News Varianten)
- Enrichment auf v3.0 (googlenewsdecoder, False-Positive-Erkennung)
- Enrichment-Rate auf 20/Lauf erhöht
- Keyword-Filter erweitert (37 Einrichtungs-Keywords)
- README.md und SETUP_ANLEITUNG.md erstellt

### Session 15.03.2026 (Hauptsession)
- **deduplicate.py** erstellt und deployed:
  - Multi-Property-Scoring (Datum, Ort, Einrichtung, Bundesland, Brandort)
  - Union-Find Clustering für Auto-Merge
  - Kandidaten-System für manuelle Prüfung
  - Workflow-Integration in `monitor.yml`
- **Cloudflare Worker** erstellt und deployed:
  - Chat-Proxy (Anthropic API)
  - Duplikat-Entscheidungen (GitHub Contents API)
  - "Nicht relevant"-Endpoint (`POST /fp`, direktes Schreiben in braende.json)
- **Website (index.html)** erstellt und deployed:
  - Dashboard mit Tabelle, Filtern, Sortierung
  - Duplikat-Kandidaten-Review mit Quell-Links
  - Chat-Interface (Claude Haiku)
  - "Nicht relevant"-Buttons pro Zeile
  - CSV-Export
  - Passwort-Schutz (SHA-256, Passwort: `ppg`)
- **Design-Overhaul:**
  - Bento Grid Statistik-Karten mit Glassmorphism
  - Off-Black Dark Theme (#0a0a0f)
  - Inter Font, Custom Scrollbar
  - Micro-Interactions (Hover-Glow, Slide-Up-Modals)
- **Bug-Fixes:**
  - `deduplicate.py` SyntaxError behoben (Markdown-Text im Python-Code)
  - PROXY_URL Default-Wert gesetzt (war leer)
  - `prompt()` Parameter-Reihenfolge korrigiert
- **GitHub Pages** aktiviert (Branch: main, Ordner: /docs)
- **Cloudflare Account** erstellt, Worker deployed, Env-Vars konfiguriert

---

## 12. Bekannte Probleme und Backlog

### Aktive Probleme
- `__pycache__/` ist im Repo sichtbar → sollte in `.gitignore` und gelöscht werden

### Backlog (priorisiert)

| Nr | Aufgabe | Priorität | Status |
|----|---------|-----------|--------|
| 1 | **KHV-Verknüpfung** — IK-Nummer-Matching gegen `GemVÖ_KHV_31_12_2023_final.xlsx` | Mittel | Offen |
| 2 | **Keyword-Evaluierung auf Website** — FP-Rate-Analyse pro Keyword, User-Vorschläge | Mittel | Offen |
| 3 | **15 Webrecherche-Neufunde** gegen Excel deduplizieren | Niedrig | Offen |
| 4 | **3 fehlende 2024-Zeilen** (170, 173, 201) verifizieren | Niedrig | Offen |
| 5 | **Dynamische Follow-up-Suchen** — nach aktuellem Brand regional fokussieren | Niedrig | Offen |

---

## 13. Lokaler Test / Entwicklung

```bash
# Abhängigkeiten installieren
pip install -r requirements.txt

# Nur Crawler (kein API-Key nötig)
python monitor.py

# Enrichment (API-Key nötig)
ANTHROPIC_API_KEY=sk-ant-... python enrich.py

# Duplikat-Zusammenführung
python deduplicate.py

# Website lokal testen
cd docs && python -m http.server 8000
# → http://localhost:8000
```

---

## 14. Notfall-Wiederherstellung

### Szenario: Repository gelöscht
1. Alle Dateien aus dem lokalen Verzeichnis `kh-brand-monitor/` sind die Source of Truth
2. Neues Repo erstellen, alle Dateien hochladen
3. GitHub Secrets neu konfigurieren (Abschnitt 6)
4. GitHub Pages neu aktivieren (Abschnitt 8)

### Szenario: Cloudflare Worker weg
1. Code aus `docs/cloudflare-worker.js` in neuen Worker einfügen
2. Env-Vars setzen: `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`
3. Worker-URL in Website aktualisieren (localStorage oder Code)

### Szenario: braende.json korrupt
1. Git-Historie enthält alle Versionen: `git log data/braende.json`
2. Alte Version wiederherstellen: `git checkout <commit-hash> -- data/braende.json`

### Szenario: Passwort vergessen
1. In `index.html` nach `PW_HASH` suchen
2. Hash durch neuen ersetzen (siehe Abschnitt 9)

---

## 15. Abhängigkeiten

### Python (`requirements.txt`)
```
feedparser>=6.0
requests>=2.28
beautifulsoup4>=4.12
googlenewsdecoder>=0.1.7
selectolax>=0.4.0
```

### JavaScript (CDN, in index.html)
- Google Fonts: Inter (wght 300–800)
- Keine weiteren externen Bibliotheken

### Externe Services
- GitHub API (Repo-Zugriff, Contents API für Writes)
- Anthropic API (Claude Haiku für Enrichment + Chat)
- Google News RSS (Nachrichtenquellen)

---

## Änderungsprotokoll dieser Dokumentation

| Datum | Änderung |
|---|---|
| 15.03.2026 | Erstversion erstellt. Vollständige Dokumentation aller Komponenten, Datenmodelle, Setup-Anleitungen und Entwicklungshistorie. |
| 15.03.2026 | CSV-Export-Funktion hinzugefügt (↓ CSV Button + exportCSV()-Funktion in index.html). Semikolon-Delimiter, BOM-Header für Excel-Kompatibilität. Exportiert gefilterte Ansicht. |
| 15.03.2026 | Website-Design komplett überarbeitet: Von Dark-Mode/Glasmorphism zu Apple-Style Light-Design (#fbfbfd/#f5f5f7, weiße Cards, subtile Schatten, Pill-Badges, Apple-Blau #0071e3 als Akzent, Inter Font, max-width 1200px zentriert). |
| 15.03.2026 | Skill universelle-atomare-protokollierung um Projekt-Dokumentationspflicht für DOKUMENTATION.md erweitert. |
| 15.03.2026 | BACKLOG: Undo-Funktion für "Nicht relevant"-Markierung fehlt. Einträge bleiben in braende.json erhalten (kein Datenverlust), aber es gibt keinen UI-Mechanismus zur Wiederherstellung. Geplant: Wiederherstellen-Button im Detail-Modal bei FP-Einträgen + Worker-Endpoint POST /unfp. |
