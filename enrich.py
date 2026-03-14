#!/usr/bin/env python3
"""
Enrichment-Layer für den Krankenhausbrand-Monitor.
Fetcht Artikel-Volltexte und extrahiert per Claude API strukturierte Steckbriefe.
"""

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

# ── Konfiguration ──
DATA_DIR = Path(__file__).parent / "data"
DB_FILE = DATA_DIR / "braende.json"
LOG_FILE = DATA_DIR / "monitor.log"

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20241022")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Maximal so viele Einträge pro Lauf enrichen (Rate-Limiting / Kosten)
MAX_ENRICH_PER_RUN = int(os.environ.get("MAX_ENRICH_PER_RUN", "5"))

# User-Agent für Artikel-Abruf
USER_AGENT = "Mozilla/5.0 (compatible; KH-Brand-Monitor/1.0; +https://github.com/kh-brand-monitor)"


def log(msg):
    DATA_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [enrich] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_db():
    if DB_FILE.exists():
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"entries": [], "seen_hashes": []}


def save_db(db):
    DATA_DIR.mkdir(exist_ok=True)
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


# ── Artikel-Fetching mit Fallback-Kaskade ──

def fetch_article_text(url):
    """
    Versucht den Volltext eines Artikels zu extrahieren.
    Fallback-Kaskade: HTML-Body → <meta>-Tags → None
    """
    if not requests:
        log("WARNUNG: requests nicht installiert, überspringe Artikel-Fetch")
        return None

    headers = {"User-Agent": USER_AGENT}

    try:
        resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        log(f"Artikel-Fetch fehlgeschlagen für {url}: {e}")
        return None

    if not BeautifulSoup:
        log("WARNUNG: beautifulsoup4 nicht installiert, Fallback auf Raw-Text")
        # Rudimentärer Fallback: HTML-Tags entfernen
        text = re.sub(r'<[^>]+>', ' ', resp.text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:5000] if text else None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Strategie 1: Presseportal.de — spezifischer Selektor
    if "presseportal.de" in url:
        article = soup.find("div", class_="story-content") or soup.find("article")
        if article:
            text = article.get_text(separator=" ", strip=True)
            if len(text) > 100:
                return text[:5000]

    # Strategie 2: <article>-Tag
    article = soup.find("article")
    if article:
        text = article.get_text(separator=" ", strip=True)
        if len(text) > 100:
            return text[:5000]

    # Strategie 3: Größter Text-Block (heuristisch)
    paragraphs = soup.find_all("p")
    if paragraphs:
        text = " ".join(p.get_text(strip=True) for p in paragraphs)
        if len(text) > 100:
            return text[:5000]

    # Fallback: <meta> description
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        return meta_desc["content"][:1000]

    meta_og = soup.find("meta", attrs={"property": "og:description"})
    if meta_og and meta_og.get("content"):
        return meta_og["content"][:1000]

    log(f"Kein Artikeltext extrahierbar für {url}")
    return None


# ── Claude API Call ──

EXTRACTION_PROMPT = """Du bist ein Datenextraktions-Assistent. Extrahiere aus dem folgenden Presseartikel über einen Brand in einem Krankenhaus/einer Klinik strukturierte Daten.

Antworte ausschließlich mit einem JSON-Objekt (kein Markdown, kein Fließtext). Felder:

{
  "einrichtung": "Name des Krankenhauses/der Klinik (so genau wie möglich)",
  "ort": "Stadt/Gemeinde",
  "plz": "Postleitzahl (falls im Text, sonst leer)",
  "bundesland": "Bundesland (ableiten aus Ort falls nicht explizit genannt)",
  "datum": "Datum des Brands im Format TT.MM.JJJJ (falls im Text)",
  "brandursache": "Ursache falls bekannt, sonst 'unbekannt'",
  "brandort": "Wo genau im Gebäude (z.B. Patientenzimmer, Keller, OP, Station, Dach)",
  "verletzte": "Anzahl und Art (z.B. '3 Leichtverletzte, 1 Schwerverletzter'). 'keine' wenn explizit erwähnt, 'unbekannt' wenn nicht erwähnt",
  "tote": "Anzahl oder 'keine' oder 'unbekannt'",
  "evakuierung": "ja/nein/teilweise/unbekannt + Anzahl Personen falls bekannt",
  "sachschaden": "Beschreibung oder Summe falls bekannt, sonst 'unbekannt'",
  "feuerwehr_einsatz": "Kurzbeschreibung des Einsatzes (Löschzüge, Dauer, etc.) falls bekannt",
  "zusammenfassung": "2-3 Sätze sachliche Zusammenfassung des Vorfalls"
}

Falls ein Feld nicht aus dem Text ableitbar ist, setze den Wert auf "unbekannt" oder leer.

ARTIKEL:
"""


def call_claude_api(article_text):
    """Ruft Claude API auf und extrahiert strukturierten Steckbrief."""
    if not ANTHROPIC_API_KEY:
        log("FEHLER: ANTHROPIC_API_KEY nicht gesetzt")
        return None

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 1024,
        "messages": [
            {
                "role": "user",
                "content": EXTRACTION_PROMPT + article_text,
            }
        ],
    }

    try:
        resp = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # Antworttext extrahieren
        content = data.get("content", [])
        if content and content[0].get("type") == "text":
            raw_text = content[0]["text"].strip()

            # JSON aus Antwort parsen (auch wenn in ```json ... ``` gewrappt)
            json_match = re.search(r'\{[\s\S]*\}', raw_text)
            if json_match:
                return json.loads(json_match.group())
            else:
                log(f"Claude-Antwort enthält kein JSON: {raw_text[:200]}")
                return None
        else:
            log(f"Unerwartetes Claude-Antwortformat: {data}")
            return None

    except json.JSONDecodeError as e:
        log(f"JSON-Parse-Fehler in Claude-Antwort: {e}")
        return None
    except Exception as e:
        log(f"Claude API Fehler: {e}")
        return None


# ── Enrichment-Logik ──

def enrich_entry(entry):
    """
    Enriched einen einzelnen braende.json-Eintrag.
    Gibt den Status zurück: 'enriched', 'partial', 'failed'
    """
    url = entry.get("link", "")
    if not url:
        log("Kein Link vorhanden, überspringe")
        return "failed"

    # Schritt 1: Artikel-Volltext fetchen
    article_text = fetch_article_text(url)

    if not article_text:
        # Fallback: RSS-Snippet verwenden
        snippet = f"{entry.get('titel', '')} {entry.get('zusammenfassung', '')}"
        if len(snippet.strip()) < 50:
            log(f"Weder Volltext noch Snippet verfügbar für {url}")
            return "failed"
        log(f"Volltext nicht verfügbar, verwende RSS-Snippet ({len(snippet)} Zeichen)")
        article_text = snippet
        is_snippet = True
    else:
        is_snippet = False
        log(f"Volltext extrahiert: {len(article_text)} Zeichen")

    # Schritt 2: Claude API aufrufen
    steckbrief = call_claude_api(article_text)
    if not steckbrief:
        return "failed"

    # Schritt 3: Steckbrief in Entry schreiben
    entry["steckbrief"] = steckbrief
    entry["enrichment_status"] = "partial" if is_snippet else "enriched"
    entry["enriched_am"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry["artikel_laenge"] = len(article_text)

    # Felder aus Steckbrief in Entry übernehmen (falls besser als Regex-Extraktion)
    if steckbrief.get("einrichtung") and steckbrief["einrichtung"] != "unbekannt":
        entry["einrichtung"] = steckbrief["einrichtung"]
    if steckbrief.get("ort") and steckbrief["ort"] != "unbekannt":
        entry["ort"] = steckbrief["ort"]
    if steckbrief.get("datum") and steckbrief["datum"] != "unbekannt":
        entry["datum"] = steckbrief["datum"]

    status = entry["enrichment_status"]
    log(f"Enrichment abgeschlossen: {status} — {entry.get('einrichtung', '?')} in {entry.get('ort', '?')}")
    return status


def main():
    log("=== Enrichment-Lauf gestartet ===")

    if not ANTHROPIC_API_KEY:
        log("ANTHROPIC_API_KEY nicht gesetzt — Enrichment übersprungen")
        log("=== Enrichment-Lauf beendet (kein API-Key) ===\n")
        return

    if not requests:
        log("FEHLER: requests-Bibliothek nicht verfügbar")
        return

    db = load_db()
    entries = db.get("entries", [])

    # Finde Einträge, die noch nicht enriched sind
    pending = [
        (i, e) for i, e in enumerate(entries)
        if e.get("enrichment_status") not in ("enriched", "partial")
    ]

    if not pending:
        log("Keine offenen Einträge zum Enrichen")
        log("=== Enrichment-Lauf beendet ===\n")
        return

    log(f"{len(pending)} Einträge warten auf Enrichment (max {MAX_ENRICH_PER_RUN} pro Lauf)")

    enriched_count = 0
    partial_count = 0
    failed_count = 0

    for idx, (i, entry) in enumerate(pending[:MAX_ENRICH_PER_RUN]):
        log(f"--- Enriche [{idx+1}/{min(len(pending), MAX_ENRICH_PER_RUN)}]: {entry.get('titel', '')[:60]}")

        status = enrich_entry(entry)
        entries[i] = entry  # Update in-place

        if status == "enriched":
            enriched_count += 1
        elif status == "partial":
            partial_count += 1
        else:
            failed_count += 1
            entry["enrichment_status"] = "failed"
            entry["enriched_am"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Rate-Limiting: 1 Sekunde zwischen API-Calls
        if idx < len(pending[:MAX_ENRICH_PER_RUN]) - 1:
            time.sleep(1)

    db["entries"] = entries
    save_db(db)

    log(f"Ergebnis: {enriched_count} enriched, {partial_count} partial, {failed_count} failed")
    log("=== Enrichment-Lauf beendet ===\n")


if __name__ == "__main__":
    main()
