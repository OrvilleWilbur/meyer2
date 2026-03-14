# Setup-Anleitung: KH-Brand-Monitor auf GitHub

## Voraussetzung
- GitHub-Account (Free reicht)
- Anthropic API Key (https://console.anthropic.com → API Keys)

---

## Schritt 1: Anthropic API Key besorgen

1. https://console.anthropic.com öffnen
2. Account erstellen oder einloggen
3. Links: "API Keys" → "Create Key"
4. Key kopieren und sicher aufbewahren (beginnt mit `sk-ant-...`)
5. Credits aufladen: $5 reichen für ~1 Jahr Betrieb

---

## Schritt 2: GitHub Repository erstellen

1. https://github.com/new öffnen
2. Repository name: `kh-brand-monitor`
3. Visibility: **Public** (für kostenlose GitHub Actions + Pages)
4. KEIN README, .gitignore oder License auswählen (haben wir schon)
5. "Create repository" klicken

---

## Schritt 3: Code hochladen

Im Terminal (im Ordner `kh-brand-monitor/`):

```bash
cd kh-brand-monitor
git init
git add .
git commit -m "Initial: Crawler + Enrichment"
git branch -M main
git remote add origin https://github.com/DEIN-USER/kh-brand-monitor.git
git push -u origin main
```

Alternativ: Dateien über die GitHub-Web-Oberfläche hochladen.

---

## Schritt 4: GitHub Secrets konfigurieren

Repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

### Pflicht-Secret:
| Name | Wert |
|------|------|
| `ANTHROPIC_API_KEY` | `sk-ant-...` (dein API Key) |

### Optional (E-Mail-Benachrichtigung):
| Name | Wert |
|------|------|
| `NOTIFY_EMAIL` | Empfänger (z.B. `2025@bowo.de`) |
| `SMTP_SERVER` | z.B. `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | Absender-Adresse |
| `SMTP_PASS` | **App-Passwort** (nicht das normale Passwort!) |

Hinweis für Gmail: Unter https://myaccount.google.com/apppasswords ein App-Passwort generieren.

---

## Schritt 5: Erster manueller Lauf

1. Repository → **Actions** Tab
2. Links: "Krankenhausbrand-Monitor" auswählen
3. Rechts: **"Run workflow"** → **"Run workflow"** bestätigen
4. Warten bis der Lauf durchgelaufen ist (1-3 Minuten)
5. Prüfen: `data/braende.json` sollte Einträge enthalten

---

## Schritt 6: Überprüfen

Nach dem ersten Lauf in `data/braende.json` schauen:
- Gibt es `entries` mit Daten? → Crawler funktioniert
- Haben Entries ein `steckbrief`-Objekt? → Enrichment funktioniert
- `enrichment_status`: `enriched` = Volltext, `partial` = nur RSS-Snippet, `failed` = Problem

Im `data/monitor.log` stehen Details zu jedem Lauf.

---

## Betrieb

- Der Monitor läuft **automatisch stündlich** (GitHub Actions Cron: `:17`)
- Neue Funde werden automatisch committed und gepusht
- Bei konfigurierten E-Mail-Secrets: Benachrichtigung bei neuen Funden
- Max. 5 Enrichments pro Lauf (Rate-Limiting)

---

## Troubleshooting

| Problem | Lösung |
|---------|--------|
| Actions laufen nicht | Settings → Actions → General → "Allow all actions" |
| Enrichment: "ANTHROPIC_API_KEY nicht gesetzt" | Secret nochmal prüfen, genau `ANTHROPIC_API_KEY` heißt es |
| 0 Treffer in Feeds | Normal wenn gerade kein Brand in den News. Google News Feeds liefern nur ~letzte 7 Tage |
| Enrichment "failed" | Artikel-Website blockiert Scraping. Steckbrief wird aus RSS-Snippet generiert (partial) |
| Actions-Minuten aufgebraucht | Bei Free: 2.000 Min/Monat. Prüfen unter Settings → Billing |
