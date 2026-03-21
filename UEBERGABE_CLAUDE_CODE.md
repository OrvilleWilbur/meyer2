# Übergabe-Prompt: KH-Brand-Monitor → Claude Code

Kopiere diesen gesamten Block als ersten Prompt in eine neue Claude-Code-Session.

---

## PROMPT START

Du arbeitest am Projekt **KH-Brand-Monitor** — einem vollautomatischen System zur Erfassung und Analyse von Krankenhausbränden in Deutschland.

### Repository

- **Repo:** `OrvilleWilbur/meyer2` (public)
- **GitHub PAT (Fine-grained, Contents Read/Write für meyer2):** `<DEIN_GITHUB_PAT_HIER_EINSETZEN>`
- **Klonen:** `git clone https://x-access-token:<PAT>@github.com/OrvilleWilbur/meyer2.git`
- **Push-Berechtigung:** Ja, direkt auf `main`

### Architektur (Kurzfassung)

```
RSS-Feeds (11 Quellen) → monitor.py (Crawler) → enrich.py (Claude Haiku API) → deduplicate.py (Dedup) → braende.json
                                                                                                              ↓
                                                                                    docs/index.html (GitHub Pages Dashboard)
                                                                                              ↕
                                                                          Cloudflare Worker (Chat + FP + Kandidaten)
```

### Technologie-Stack

| Komponente | Technologie |
|---|---|
| Pipeline | Python (GitHub Actions, stündlich :17) |
| LLM | Claude Haiku via Anthropic API |
| Website | Single-File HTML (docs/index.html), GitHub Pages |
| API-Proxy | Cloudflare Worker (`https://meyer2.2025-1f5.workers.dev`) |
| Datenbank | `data/braende.json` (JSON im Repo) |
| Duplikat-Kandidaten | `data/merge_candidates.json` |
| Passwort-Schutz | SHA-256 Client-Side (Passwort: `ppg`) |

### Dateistruktur (wichtigste Dateien)

```
meyer2/
├── monitor.py              # RSS-Crawler, 11 Feeds, Keyword-Filter
├── enrich.py               # Claude Haiku Enrichment (max 20/Lauf), FP-Erkennung
├── deduplicate.py          # Multi-Property-Scoring, Union-Find, Auto-Merge ≥0.80
├── data/
│   ├── braende.json        # Hauptdatenbank (alle Einträge)
│   └── merge_candidates.json  # Duplikat-Kandidaten (pending/confirmed/rejected)
├── docs/
│   ├── index.html          # Dashboard (Apple-Style Light-Design)
│   └── cloudflare-worker.js # Worker-Code (Referenz, deployed auf Cloudflare)
├── .github/workflows/
│   └── monitor.yml         # GitHub Actions Pipeline
├── DOKUMENTATION.md        # Vollständige technische Doku (579 Zeilen, PFLICHTLEKTÜRE)
├── requirements.txt        # Python-Dependencies
└── keywords.json           # RSS-Filterregeln
```

### Cloudflare Worker — 3 Endpoints

| Endpoint | Funktion |
|---|---|
| `POST /` | Chat-Proxy (leitet an Anthropic API weiter) |
| `POST /candidates` | Duplikat-Entscheidungen schreiben (merge_candidates.json) |
| `POST /fp` | "Nicht relevant" markieren (braende.json) |

### Design-Entscheidungen

- **Apple-Style Light-Design** (aktuell): Heller Hintergrund (#fbfbfd/#f5f5f7), weiße Cards, subtile Schatten, Pill-Badges, Apple-Blau (#0071e3), Inter Font, max-width 1200px
- **CSV-Export:** Semikolon-Delimiter, BOM-Header für Excel, exportiert gefilterte Ansicht
- **Dedup-Scoring:** Gewichtet — Datum 0.30, Ort 0.30, Einrichtung 0.25, Bundesland 0.10, Brandort 0.05
- **Debounced Sync:** 2s Delay für Batch-Entscheidungen bei Duplikaten

### Aktuelle Zahlen (Stand 15.03.2026)

- 223 Einträge in braende.json
- 61 offene Duplikat-Kandidaten
- ~122 noch nicht enriched (Pipeline max 20 pro Lauf)

### Offene Backlog-Punkte

1. **Undo-Funktion für "Nicht relevant"** — Wiederherstellen-Button im Detail-Modal + neuer Worker-Endpoint `POST /unfp` (Daten gehen nicht verloren, Status-Reset auf `pending` fehlt nur)
2. **`__pycache__`** auf GitHub sichtbar — `.gitignore` ergänzen und Ordner löschen
3. **KHV-Verknüpfung** — IK-Nummer-Matching mit Krankenhausverzeichnis
4. **Keyword-Evaluierung** auf der Website
5. **Node.js 20 Deprecation-Warning** in GitHub Actions — auf Node 24 migrieren (ab Juni 2026 Pflicht)

### Verbindliche Regeln

1. **DOKUMENTATION.md** ist bei JEDER Änderung simultan zu aktualisieren (Änderungsprotokoll am Ende)
2. **Keine partiellen Code-Edits** — User will immer den kompletten Code sehen oder direkt gepusht bekommen
3. **Git Push direkt** über HTTPS + PAT (kein manuelles Copy-Paste auf GitHub)
4. **Commit-Format:** Emoji + kurze Beschreibung, z.B. `🔥 Neue Einträge` oder `📄 Doku aktualisiert`

### Erste Aktion

Lies `DOKUMENTATION.md` im Repo — das ist die vollständige technische Dokumentation mit allen Details zu Datenmodellen, Workflows, Setup und Entwicklungshistorie.

## PROMPT ENDE
