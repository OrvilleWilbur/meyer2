#!/usr/bin/env python3
"""
Krankenhausbrand-Monitor Deutschland
Überwacht RSS-Feeds und News nach Brandereignissen in Krankenhäusern.
Läuft als GitHub Action (stündlich).
"""

import feedparser
import json
import os
import re
import hashlib
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from pathlib import Path

# ── Konfiguration ──
KEYWORDS = [
    "krankenhaus", "klinik", "klinikum", "hospital", "uniklinik",
    "universitätsklinikum", "fachklinik", "patientenzimmer", "station",
    "charité", "helios", "asklepios", "vivantes", "sana", "ameos",
]

BRAND_KEYWORDS = [
    "brand", "feuer", "brennt", "brannte", "flammen", "rauch",
    "rauchentwicklung", "feuerwehr", "evakuiert", "evakuierung",
    "brandstiftung", "brandursache", "lösch",
]

# Ausschluss-Keywords (Falsch-Positive)
EXCLUDE_KEYWORDS = [
    "brandbrief", "brandschutzübung", "brandschutzbegehung",
    "brandmeldeanlage test", "feuerwerk", "brandschutzkonzept",
]

RSS_FEEDS = {
    # Presseportal.de Blaulicht (Feuerwehr-Meldungen)
    "presseportal_feuerwehr": "https://www.presseportal.de/rss/presseportal_feuerwehr.rss2",
    "presseportal_blaulicht": "https://www.presseportal.de/rss/presseportal_blaulicht.rss2",
    # Google News RSS
    "google_news_kh_brand": "https://news.google.com/rss/search?q=%22Brand%22+%22Krankenhaus%22+Deutschland&hl=de&gl=DE&ceid=DE:de",
    "google_news_klinik_feuer": "https://news.google.com/rss/search?q=%22Feuer%22+%22Klinik%22+Deutschland&hl=de&gl=DE&ceid=DE:de",
    "google_news_klinikbrand": "https://news.google.com/rss/search?q=Klinikbrand+OR+Krankenhausbrand+Deutschland&hl=de&gl=DE&ceid=DE:de",
    # Feuerwehrmagazin RSS
    "feuerwehrmagazin": "https://www.feuerwehrmagazin.de/feed",
}

DATA_DIR = Path(__file__).parent / "data"
DB_FILE = DATA_DIR / "braende.json"
LOG_FILE = DATA_DIR / "monitor.log"


def load_db():
    if DB_FILE.exists():
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"entries": [], "seen_hashes": []}


def save_db(db):
    DATA_DIR.mkdir(exist_ok=True)
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def log(msg):
    DATA_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def make_hash(title, link):
    raw = f"{title.lower().strip()}{link.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()


def is_relevant(title, summary):
    """Prüft ob ein Eintrag ein Krankenhausbrand sein könnte."""
    text = f"{title} {summary}".lower()

    # Ausschluss prüfen
    for ex in EXCLUDE_KEYWORDS:
        if ex in text:
            return False

    # Muss mindestens ein Krankenhaus-Keyword UND ein Brand-Keyword enthalten
    has_kh = any(kw in text for kw in KEYWORDS)
    has_brand = any(kw in text for kw in BRAND_KEYWORDS)

    return has_kh and has_brand


def extract_info(title, summary, link, published, source):
    """Extrahiert strukturierte Informationen aus dem Treffer."""
    text = f"{title} {summary}"

    # Datum aus published oder aus Text
    datum = ""
    if published:
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(published)
            datum = dt.strftime("%d.%m.%Y")
        except Exception:
            datum = published[:10] if published else ""

    # Ort extrahieren (häufige Muster in Presseportal-Titeln)
    ort = ""
    m = re.search(r'(?:FW-|POL-|PP\s)(\w[\w\-]+):', title)
    if m:
        ort = m.group(1).replace("-", " ").strip()

    # Einrichtung extrahieren
    einrichtung = ""
    for kw in ["krankenhaus", "klinik", "klinikum", "hospital"]:
        pattern = rf'([\w\-\.]+\s*{kw}[\w\s\-]*?)(?:\s*[–\-:,\.]|\s+(?:in|im|am|auf|der|des|wurde|hat|ist))'
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            einrichtung = m.group(1).strip()
            break
    if not einrichtung:
        for kw in ["krankenhaus", "klinik", "klinikum", "hospital"]:
            pattern = rf'(?:im|in|am|des|dem)\s+([\w\-\.]+\s*{kw}[\w\s\-]*?)(?:\s*[–\-:,\.])'
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                einrichtung = m.group(1).strip()
                break

    # Verletzte/Tote
    verletzte = ""
    m = re.search(r'(\d+)\s*(?:Verletzte|Leichtverletzte|Schwerverletzte)', text, re.IGNORECASE)
    if m:
        verletzte = m.group(0)
    m2 = re.search(r'(\d+)\s*(?:Tote|Todesopfer|gestorben|verstorben|ums Leben)', text, re.IGNORECASE)
    if m2:
        verletzte = f"{m2.group(0)}, {verletzte}" if verletzte else m2.group(0)

    return {
        "datum": datum,
        "einrichtung": einrichtung[:100],
        "ort": ort,
        "titel": title[:200],
        "zusammenfassung": summary[:500],
        "verletzte": verletzte,
        "quelle": source,
        "link": link,
        "erfasst_am": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def fetch_feeds():
    """Alle RSS-Feeds abrufen und relevante Einträge filtern."""
    results = []
    for name, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            log(f"Feed '{name}': {len(feed.entries)} Einträge")
            for entry in feed.entries:
                title = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                link = entry.get("link", "")
                published = entry.get("published", "")

                if is_relevant(title, summary):
                    results.append({
                        "title": title,
                        "summary": summary,
                        "link": link,
                        "published": published,
                        "source": name,
                    })
        except Exception as e:
            log(f"FEHLER bei Feed '{name}': {e}")
    return results


def send_notification(new_entries):
    """E-Mail-Benachrichtigung bei neuen Funden."""
    email_to = os.environ.get("NOTIFY_EMAIL")
    smtp_server = os.environ.get("SMTP_SERVER") or "smtp.gmail.com"
    smtp_port_raw = os.environ.get("SMTP_PORT") or "587"
    smtp_port = int(smtp_port_raw)
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")

    if not all([email_to, smtp_user, smtp_pass]):
        log("E-Mail nicht konfiguriert, überspringe Benachrichtigung")
        return

    body = f"Es wurden {len(new_entries)} neue Krankenhausbrände gefunden:\n\n"
    for e in new_entries:
        body += f"📅 {e['datum']} — {e['einrichtung'] or 'Unbekannt'}\n"
        body += f"   {e['ort']}\n" if e['ort'] else ""
        body += f"   {e['verletzte']}\n" if e['verletzte'] else ""
        body += f"   {e['titel'][:100]}\n"
        body += f"   {e['link']}\n\n"

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"🔥 {len(new_entries)} neue Krankenhausbrände erkannt"
    msg["From"] = smtp_user
    msg["To"] = email_to

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        log(f"E-Mail gesendet an {email_to}")
    except Exception as e:
        log(f"E-Mail-Fehler: {e}")


def main():
    log("=== Monitor-Lauf gestartet ===")

    db = load_db()
    seen = set(db.get("seen_hashes", []))

    candidates = fetch_feeds()
    log(f"{len(candidates)} relevante Treffer in Feeds")

    new_entries = []
    for c in candidates:
        h = make_hash(c["title"], c["link"])
        if h in seen:
            continue
        seen.add(h)
        info = extract_info(c["title"], c["summary"], c["link"], c["published"], c["source"])
        db["entries"].append(info)
        new_entries.append(info)

    db["seen_hashes"] = list(seen)
    save_db(db)

    if new_entries:
        log(f"✅ {len(new_entries)} NEUE Einträge gefunden:")
        for e in new_entries:
            log(f"   {e['datum']} | {e['einrichtung']} | {e['ort']} | {e['titel'][:60]}")
        send_notification(new_entries)
    else:
        log("Keine neuen Einträge")

    log("=== Monitor-Lauf beendet ===\n")


if __name__ == "__main__":
    main()
