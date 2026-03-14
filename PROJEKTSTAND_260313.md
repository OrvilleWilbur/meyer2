# KH-Brand-Monitor — Projektstand 13.03.2026

## Projektziel
Aufbau einer umfassenden Datenbank aller Brandereignisse in Krankenhäusern in Deutschland, bestehend aus drei Teilprojekten: automatisiertem Crawler, LLM-basiertem Enrichment und passwortgeschützter Website.

---

## Teilprojekte — Status & Plattform

### TP 1 — Crawler/Monitor ✅ FERTIG (Code steht, noch nicht deployed)
- **Plattform:** GitHub Actions (Cron-Job, stündlich)
- **Funktion:** Parst 6 RSS-Feeds (Presseportal Feuerwehr, Presseportal Blaulicht, 3× Google News, Feuerwehrmagazin), filtert per Keyword-Kombination (Krankenhaus + Brand), dedupliziert per Hash, speichert Treffer in `braende.json`
- **Code:** `monitor.py` (8.363 Bytes)
- **Workflow:** `.github/workflows/monitor.yml` (stündlich um :17)
- **Daten:** `data/braende.json` (leer, Schema: `{"entries": [], "seen_hashes": []}`)
- **Dependencies:** `feedparser>=6.0`
- **Bekannte Einschränkung:** RSS-Feeds sind nicht vollständig — kleinere Vorfälle in Lokalzeitungen werden nicht erfasst. Erweiterbar durch zusätzliche Feeds.

### TP 2 — Enrichment ✅ FERTIG (Code steht, noch nicht deployed)
- **Plattform:** GitHub Actions (im selben Workflow wie TP 1, nachgelagert)
- **LLM-API:** Claude Haiku 4.5 (Anthropic API), Modell: `claude-haiku-4-5-20241022`
- **Geschätzte Kosten:** ~$0.50/Monat (~10 Fälle × ~4.000 Tokens)
- **Code:** `enrich.py` (10.525 Bytes), gebaut am 14.03.2026
- **Ablauf:**
  1. Einträge ohne `enrichment_status` identifizieren
  2. Artikel-Volltext fetchen (requests + BeautifulSoup)
  3. Fallback-Kaskade: HTML-Body → `<article>`-Tag → `<p>`-Tags → `<meta>`-Tags → RSS-Snippet
  4. Claude API Call → strukturierter Steckbrief (JSON) extrahieren
  5. Steckbrief + Status zurückschreiben in `braende.json`
- **Steckbrief-Felder:** Einrichtung, Ort, PLZ, Bundesland, Datum, Brandursache, Brandort, Verletzte, Tote, Evakuierung, Sachschaden, Feuerwehr-Einsatz, Zusammenfassung
- **Status-Feld pro Eintrag:** `enriched` (Volltext), `partial` (nur RSS-Snippet), `failed`
- **Rate-Limiting:** Max. 5 Enrichments pro Lauf, 1s Pause zwischen API-Calls
- **Noch zu tun:** Claude API Key als GitHub Secret, erster Live-Test

### TP 3 — Website/Dashboard ❌ NOCH NICHT GEBAUT
- **Plattform:** GitHub Pages (kostenlos bei Public Repo)
- **Geplante Funktion:** Statische HTML-Seite, generiert aus `braende.json`. Filterfunktion nach Bundesland, Jahr, Einrichtungstyp. Einzelseiten pro Brand (Steckbrief-Detailansicht).
- **Passwortschutz:** Client-seitiges JS (kein echter Schutz). Für echten Login später Cloudflare Access evaluieren.
- **Zu bauen:** Site-Generator-Script, HTML-Templates, Deploy-Step in GitHub Actions

---

## Architektur-Entscheidungen (getroffen)

| Entscheidung | Ergebnis | Begründung |
|---|---|---|
| LLM-Plattform | Claude API (Haiku 4.5) | Beste Extraktionsqualität für deutsche Pressetexte. ~$0.50/Monat vs. Mittwald 9€/Monat |
| Mittwald AI Hosting | Verworfen | 9€-Tarif wäre ausreichend (5M Tokens, nur ~40K benötigt), aber Modellqualität (gpt-oss-120b) unbekannt. Kein Preisvorteil bei diesem Volumen |
| Hosting | GitHub (Actions + Pages) | Alles in einem Ökosystem. Free Tier reicht (2.000 Actions-Min/Monat, ~750 benötigt) |
| GitHub Pro | Nicht nötig | Bringt für dieses Projekt keinen relevanten Mehrwert. Pages für Private Repos wäre der einzige Vorteil, aber kein echter Login-Schutz |
| DACH-Scope | Nur Deutschland | DACH wurde bewusst auf D reduziert, um Komplexität zu begrenzen |
| API-Design | API-agnostisch | Endpoint + Modell als Config-Parameter, Wechsel zu anderem Provider jederzeit möglich |

---

## Bestehende Dateien (Gesamtprojekt)

### Im Repo `kh-brand-monitor/`
- `monitor.py` — Crawler-Code (fertig)
- `.github/workflows/monitor.yml` — GitHub Actions Workflow (fertig)
- `data/braende.json` — Datenbank (leer, Schema steht)
- `data/monitor.log` — Log (Test-Einträge)
- `requirements.txt` — `feedparser>=6.0`
- `README.md` — Setup-Anleitung
- `.gitignore`

### Im übergeordneten Verzeichnis
- `Braende_KHV_Verknuepfung_Gesamt_260216.xlsx` — Hauptdatei: 709 bvfa-Brandfälle verknüpft mit KHV-Verzeichnis (567 hoch, 53 mittel, 61 kein Match, 28 nicht im KHV)
- `Braende_KHV_Verknuepfung.xlsx` — Ältere Version
- `Webrecherche_Krankenhausbraende_260313.md` — 15 potenzielle Neufunde aus Webrecherche (2 vor 2013, 7 aus 2024, 3 aus 2025, 3 aus 2026)
- `kh-brand-monitor-architektur.html` — Interaktives Architekturdiagramm
- `GemVÖ_KHV_31_12_2023_final.xlsx` — KHV-Verzeichnis (2.782 Einträge)

---

## Offene Punkte / Nächste Schritte

1. ~~**`enrich.py` bauen**~~ ✅ erledigt 14.03.2026
2. ~~**`braende.json` Schema erweitern**~~ ✅ erledigt 14.03.2026
3. ~~**`monitor.yml` anpassen**~~ ✅ erledigt 14.03.2026
4. **Claude API Key** als GitHub Secret konfigurieren
5. **GitHub Repo erstellen** und Code deployen
6. **15 Webrecherche-Neufunde** gegen Excel dedupen und ggf. einpflegen
7. **3 fehlende 2024-Zeilen** (Zeilen 170, 173, 201 aus Excel) verifizieren
8. **Site-Generator** für TP 3 bauen
9. **Passwortschutz** evaluieren (Cloudflare Access vs. Client-JS)
10. **Quellen erweitern** — Lokalzeitungen, weitere RSS-Feeds

---

## Kosten-Übersicht (monatlich, Betrieb)

| Posten | Kosten |
|---|---|
| GitHub Actions | 0 € (Free Tier) |
| Claude API (Haiku) | ~0,50 € |
| GitHub Pages | 0 € |
| **Gesamt** | **~0,50 €/Monat** |
