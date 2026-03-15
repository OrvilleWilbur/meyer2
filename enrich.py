#!/usr/bin/env python3
"""
Enrichment-Layer für den Krankenhausbrand-Monitor.
Fetcht Artikel-Volltexte und extrahiert per Claude API strukturierte Steckbriefe.

v3.0 — Google News URL-Auflösung via googlenewsdecoder, Boilerplate-Erkennung,
        robuster Snippet-Fallback.
"""

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

# Google News Decoder — zwei Methoden verfügbar
try:
    from googlenewsdecoder import new_decoderv1 as gn_decode_v1
except ImportError:
    gn_decode_v1 = None

try:
    from googlenewsdecoder import GoogleDecoder
    gn_decoder_v2 = GoogleDecoder()
except ImportError:
    gn_decoder_v2 = None

# ── Konfiguration ──
DATA_DIR = Path(__file__).parent / "data"
DB_FILE = DATA_DIR / "braende.json"
LOG_FILE = DATA_DIR / "monitor.log"

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL") or "claude-haiku-4-5-20251001"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY") or ""

# Maximal so viele Einträge pro Lauf enrichen (Rate-Limiting / Kosten)
MAX_ENRICH_PER_RUN = int(os.environ.get("MAX_ENRICH_PER_RUN") or "20")

# User-Agent für Artikel-Abruf
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Bekannte Google-Boilerplate-Texte (wenn resolve fehlschlägt, liefert Google nur diese Seite)
GOOGLE_BOILERPLATE_MARKERS = [
    "google news",
    "before you continue to google",
    "javascript is not enabled",
    "to continue, turn on javascript",
]


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


def is_google_boilerplate(text):
    """Erkennt Google News Boilerplate-Text (wenn Redirect-Auflösung fehlschlägt)."""
    if not text:
        return True
    text_lower = text.lower()
    # Zu kurz für einen echten Artikel
    if len(text.strip()) < 200:
        for marker in GOOGLE_BOILERPLATE_MARKERS:
            if marker in text_lower:
                return True
    # Weitere Heuristik: Text enthält fast nur Google-spezifische Inhalte
    if "consent.google" in text_lower or "accounts.google" in text_lower:
        return True
    return False


# ── Google News Redirect-Auflösung ──

def resolve_google_news_url(url):
    """
    Google News RSS liefert Redirect-URLs (news.google.com/rss/articles/...).
    Löst diese auf über googlenewsdecoder-Library (2 Methoden).
    Gibt (resolved_url, methode) zurück.
    """
    if "news.google.com" not in url:
        return url, "direct"

    # Methode 1: googlenewsdecoder v1 (schnell, offline base64-Decode)
    # Funktioniert nur bei älteren Google News URL-Formaten
    if gn_decode_v1:
        try:
            result = gn_decode_v1(url)
            if isinstance(result, dict):
                if result.get("status") and result.get("decoded_url"):
                    decoded = result["decoded_url"]
                    if decoded.startswith("http") and "google" not in decoded.lower():
                        log(f"Google News URL aufgelöst (v1): {decoded[:80]}")
                        return decoded, "gn_decoder_v1"
            elif isinstance(result, str) and result.startswith("http") and "google" not in result.lower():
                log(f"Google News URL aufgelöst (v1): {result[:80]}")
                return result, "gn_decoder_v1"
        except Exception as e:
            log(f"googlenewsdecoder v1 fehlgeschlagen: {e}")

    # Methode 2: googlenewsdecoder v2 (macht HTTP-Requests an Google, zuverlässiger)
    if gn_decoder_v2:
        try:
            result = gn_decoder_v2.decode_google_news_url(url)
            if result.get("status") and result.get("decoded_url"):
                decoded = result["decoded_url"]
                log(f"Google News URL aufgelöst (v2): {decoded[:80]}")
                return decoded, "gn_decoder_v2"
            else:
                log(f"googlenewsdecoder v2 fehlgeschlagen: {result.get('message', 'unbekannt')}")
        except Exception as e:
            log(f"googlenewsdecoder v2 Fehler: {e}")

    # Methode 3: Fallback — HTTP-Redirect folgen (funktioniert selten bei Google News)
    if requests:
        try:
            headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
            resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
            final_url = resp.url
            if "google.com" not in final_url and "google.de" not in final_url:
                log(f"Google News URL aufgelöst (HTTP-Redirect): {final_url[:80]}")
                return final_url, "http_redirect"
        except Exception as e:
            log(f"HTTP-Redirect-Auflösung fehlgeschlagen: {e}")

    log(f"Google News URL konnte NICHT aufgelöst werden: {url[:80]}")
    return url, "failed"


# ── Artikel-Fetching mit Fallback-Kaskade ──

def fetch_article_text(url):
    """
    Versucht den Volltext eines Artikels zu extrahieren.
    Löst zuerst Google News Redirects auf, dann Fallback-Kaskade.
    Gibt (text, resolved_url, resolve_method) zurück.
    """
    if not requests:
        log("WARNUNG: requests nicht installiert, überspringe Artikel-Fetch")
        return None, url, "no_requests"

    # Google News Redirects auflösen
    resolved_url, resolve_method = resolve_google_news_url(url)

    # Wenn Auflösung fehlgeschlagen und URL noch auf Google zeigt → kein Fetch versuchen
    if resolve_method == "failed" and "news.google.com" in resolved_url:
        log(f"Überspringe Fetch — Google News URL nicht aufgelöst")
        return None, resolved_url, resolve_method

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    }

    try:
        resp = requests.get(resolved_url, headers=headers, timeout=15, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        log(f"Artikel-Fetch fehlgeschlagen für {resolved_url[:80]}: {e}")
        return None, resolved_url, resolve_method

    # Boilerplate-Check (falls wir doch auf einer Google-Seite gelandet sind)
    if is_google_boilerplate(resp.text[:500]):
        log(f"Google Boilerplate erkannt — Text verworfen")
        return None, resolved_url, resolve_method

    if not BeautifulSoup:
        text = re.sub(r'<[^>]+>', ' ', resp.text)
        text = re.sub(r'\s+', ' ', text).strip()
        return (text[:5000] if text else None), resolved_url, resolve_method

    soup = BeautifulSoup(resp.text, "html.parser")

    # Strategie 1: Presseportal.de — spezifischer Selektor
    if "presseportal.de" in resolved_url:
        article = soup.find("div", class_="story-content") or soup.find("article")
        if article:
            text = article.get_text(separator=" ", strip=True)
            if len(text) > 100:
                return text[:5000], resolved_url, resolve_method

    # Strategie 2: <article>-Tag
    article = soup.find("article")
    if article:
        text = article.get_text(separator=" ", strip=True)
        if len(text) > 100:
            return text[:5000], resolved_url, resolve_method

    # Strategie 3: Hauptinhalt über gängige CSS-Klassen
    for selector in ["div.article-body", "div.article-content", "div.story-body",
                      "div.entry-content", "div.post-content", "div.text",
                      "div.article__body", "div.article-text", "div.content-body",
                      "main", "div[role='main']", "div[itemprop='articleBody']"]:
        content = soup.select_one(selector)
        if content:
            text = content.get_text(separator=" ", strip=True)
            if len(text) > 200:
                return text[:5000], resolved_url, resolve_method

    # Strategie 4: Alle <p>-Tags
    paragraphs = soup.find_all("p")
    if paragraphs:
        text = " ".join(p.get_text(strip=True) for p in paragraphs)
        if len(text) > 100:
            return text[:5000], resolved_url, resolve_method

    # Fallback: <meta> description
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        return meta_desc["content"][:1000], resolved_url, resolve_method

    meta_og = soup.find("meta", attrs={"property": "og:description"})
    if meta_og and meta_og.get("content"):
        return meta_og["content"][:1000], resolved_url, resolve_method

    log(f"Kein Artikeltext extrahierbar für {resolved_url[:80]}")
    return None, resolved_url, resolve_method


# ── Claude API Call ──

EXTRACTION_PROMPT = """Du bist ein Datenextraktions-Assistent für eine Datenbank über Brände in Krankenhäusern und Kliniken in Deutschland.

WICHTIG: Prüfe zuerst, ob der Artikel tatsächlich einen Brand IN einem Krankenhaus/einer Klinik beschreibt.
KEIN Krankenhausbrand ist:
- Person wird nach einem Brand (z.B. Wohnungsbrand, Hotelbrand) ins Krankenhaus gebracht
- Brandopfer werden in einer Klinik behandelt (z.B. Crans-Montana Brandopfer in deutscher Klinik)
- Brand in der Nähe eines Krankenhauses, aber nicht im Krankenhaus selbst
- Brandschutzübungen, Brandschutzkonzepte, Brandbriefe
- Brände in ausländischen Krankenhäusern (außerhalb Deutschlands)
- Evakuierungen wegen Bombenentschärfung, Hochwasser oder anderen Nicht-Brand-Gründen
- Artikel die "Krankenhaus" und "Brand/Feuer" nur im Kontext von Behandlung/Einlieferung erwähnen

Wenn der Artikel KEINEN Brand in einem deutschen Krankenhaus/einer Klinik beschreibt, antworte NUR mit:
{"ist_krankenhausbrand": false, "grund": "kurze Begründung"}

Wenn es ein echter Krankenhausbrand in Deutschland ist, antworte mit diesem JSON:
{
  "ist_krankenhausbrand": true,
  "einrichtung": "Name des Krankenhauses/der Klinik (so genau wie möglich)",
  "ort": "Stadt/Gemeinde",
  "plz": "Postleitzahl (falls im Text, sonst leer)",
  "bundesland": "Bundesland (ableiten aus Ort falls nicht explizit genannt)",
  "datum": "Datum des Brands im Format TT.MM.JJJJ (falls im Text)",
  "brandursache": "Ursache falls bekannt, sonst 'unbekannt'",
  "brandort": "Wo genau im Gebäude (z.B. Patientenzimmer, Keller, OP, Station, Dach)",
  "verletzte": "Anzahl und Art (z.B. '3 Leichtverletzte, 1 Schwerverletzter'). 'keine' wenn explizit, 'unbekannt' wenn nicht erwähnt",
  "tote": "Anzahl oder 'keine' oder 'unbekannt'",
  "evakuierung": "ja/nein/teilweise/unbekannt + Anzahl Personen falls bekannt",
  "sachschaden": "Beschreibung oder Summe falls bekannt, sonst 'unbekannt'",
  "feuerwehr_einsatz": "Kurzbeschreibung des Einsatzes falls bekannt",
  "zusammenfassung": "2-3 Sätze sachliche Zusammenfassung des Vorfalls"
}

Antworte ausschließlich mit JSON. Kein Markdown, kein Fließtext.

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

        content = data.get("content", [])
        if content and content[0].get("type") == "text":
            raw_text = content[0]["text"].strip()

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
    Gibt den Status zurück: 'enriched', 'partial', 'false_positive', 'failed'
    """
    url = entry.get("link", "")
    if not url:
        log("Kein Link vorhanden, überspringe")
        return "failed"

    # Schritt 1: Artikel-Volltext fetchen
    article_text, resolved_url, resolve_method = fetch_article_text(url)

    # Aufgelöste URL im Entry speichern (für spätere Referenz)
    if resolved_url != url:
        entry["resolved_url"] = resolved_url
    entry["resolve_method"] = resolve_method

    if not article_text or len(article_text) < 200:
        # Fallback: RSS-Snippet verwenden
        snippet = f"{entry.get('titel', '')} {entry.get('zusammenfassung', '')}"
        if len(snippet.strip()) < 50:
            log(f"Weder Volltext noch Snippet verfügbar für {url[:80]}")
            return "failed"
        log(f"Volltext zu kurz/leer ({len(article_text) if article_text else 0} Z.), verwende RSS-Snippet ({len(snippet)} Z.)")
        article_text = snippet
        is_snippet = True
    else:
        is_snippet = False
        log(f"Volltext extrahiert: {len(article_text)} Zeichen von {resolved_url[:60]}")

    # Schritt 2: Claude API aufrufen
    steckbrief = call_claude_api(article_text)
    if not steckbrief:
        return "failed"

    # Schritt 3: False-Positive-Prüfung durch Claude
    if not steckbrief.get("ist_krankenhausbrand", True):
        grund = steckbrief.get("grund", "kein Grund angegeben")
        log(f"FALSE POSITIVE erkannt: {grund}")
        entry["enrichment_status"] = "false_positive"
        entry["enriched_am"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry["false_positive_grund"] = grund
        return "false_positive"

    # Schritt 4: Steckbrief in Entry schreiben
    entry["steckbrief"] = steckbrief
    entry["enrichment_status"] = "partial" if is_snippet else "enriched"
    entry["enriched_am"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry["artikel_laenge"] = len(article_text)

    # Felder aus Steckbrief übernehmen (falls besser als Regex-Extraktion)
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

    # Verfügbarkeit der Decoder loggen
    log(f"googlenewsdecoder v1: {'verfügbar' if gn_decode_v1 else 'NICHT verfügbar'}")
    log(f"googlenewsdecoder v2: {'verfügbar' if gn_decoder_v2 else 'NICHT verfügbar'}")

    db = load_db()
    entries = db.get("entries", [])

    # Finde Einträge, die noch nicht enriched sind (failed werden erneut versucht)
    pending = [
        (i, e) for i, e in enumerate(entries)
        if e.get("enrichment_status") not in ("enriched", "partial", "false_positive")
    ]

    if not pending:
        log("Keine offenen Einträge zum Enrichen")
        log("=== Enrichment-Lauf beendet ===\n")
        return

    log(f"{len(pending)} Einträge warten auf Enrichment (max {MAX_ENRICH_PER_RUN} pro Lauf)")

    enriched_count = 0
    partial_count = 0
    false_positive_count = 0
    failed_count = 0

    for idx, (i, entry) in enumerate(pending[:MAX_ENRICH_PER_RUN]):
        log(f"--- Enriche [{idx+1}/{min(len(pending), MAX_ENRICH_PER_RUN)}]: {entry.get('titel', '')[:60]}")

        status = enrich_entry(entry)
        entries[i] = entry

        if status == "enriched":
            enriched_count += 1
        elif status == "partial":
            partial_count += 1
        elif status == "false_positive":
            false_positive_count += 1
        else:
            failed_count += 1
            entry["enrichment_status"] = "failed"
            entry["enriched_am"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Rate-Limiting: 1 Sekunde zwischen API-Calls
        if idx < len(pending[:MAX_ENRICH_PER_RUN]) - 1:
            time.sleep(1)

    db["entries"] = entries
    save_db(db)

    log(f"Ergebnis: {enriched_count} enriched, {partial_count} partial, {false_positive_count} false_positive, {failed_count} failed")
    log("=== Enrichment-Lauf beendet ===\n")


if __name__ == "__main__":
    main()
