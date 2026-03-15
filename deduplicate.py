#!/usr/bin/env python3
"""
Duplikat-Zusammenführung für den Krankenhausbrand-Monitor.

Zweistufiger Ansatz:
  1. AUTO-MERGE: Multi-Property-Scoring findet sichere Duplikate (Score >= THRESHOLD)
     und verschmilzt sie automatisch.
  2. KANDIDATEN: Unsichere Paare (Score zwischen CANDIDATE_MIN und THRESHOLD) werden
     in merge_candidates.json geschrieben → Website zeigt sie dem Nutzer zur manuellen
     Bestätigung/Ablehnung.

Wird als Schritt nach enrich.py in der GitHub-Actions-Pipeline aufgerufen.
"""

import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DB_FILE = DATA_DIR / "braende.json"
CANDIDATES_FILE = DATA_DIR / "merge_candidates.json"
LOG_FILE = DATA_DIR / "monitor.log"

# ── Schwellenwerte ──
AUTO_MERGE_THRESHOLD = 0.80   # Ab diesem Score: automatisch mergen
CANDIDATE_MIN = 0.45          # Ab diesem Score: als Kandidat vorschlagen


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [DEDUP] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Normalisierung
# ══════════════════════════════════════════════════════════════════════════════

def normalize(text: str) -> str:
    """Normalisiert Text für Vergleiche."""
    if not text or text == "unbekannt":
        return ""
    t = text.lower().strip()
    t = unicodedata.normalize("NFC", t)
    # Sonderzeichen → Leerzeichen (vor Compound-Split, damit Bindestriche weg sind)
    t = re.sub(r"[().,;:\-/\"\']", " ", t)
    # Deutsche Kompositwörter an Krankenhaus-Begriffen auftrennen
    # "marienkrankenhaus" → "marien krankenhaus", "herzklinik" → "herz klinik"
    for term in ["krankenhaus", "klinikum", "klinik", "hospital", "spital"]:
        t = re.sub(rf"(\w+?)({term})", rf"\1 \2", t)
    # Gängige Abkürzungen/Synonyme NACH dem Split
    t = t.replace("st.", "sankt").replace("ev.", "evangelisch")
    t = t.replace("kath.", "katholisch")
    t = t.replace("klinikum", "klinik")
    t = t.replace("krankenhaus", "kh")
    t = t.replace("universitätsklinik", "uniklinik")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def normalize_datum(datum: str) -> str:
    """Normalisiert Datumsformate zu TT.MM.JJJJ."""
    if not datum or datum == "unbekannt":
        return ""
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", datum)
    if m:
        return f"{int(m.group(1)):02d}.{int(m.group(2)):02d}.{m.group(3)}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", datum)
    if m:
        return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    return datum.strip()


def parse_datum(datum_str: str):
    """Parst TT.MM.JJJJ zu datetime.date, None bei Fehler."""
    d = normalize_datum(datum_str)
    if not d:
        return None
    try:
        return datetime.strptime(d, "%d.%m.%Y").date()
    except ValueError:
        return None


def extract_words(text: str) -> set:
    """Extrahiert Wort-Set aus normalisiertem Text."""
    n = normalize(text)
    if not n:
        return set()
    return set(n.split())


# ══════════════════════════════════════════════════════════════════════════════
# Ähnlichkeits-Scoring
# ══════════════════════════════════════════════════════════════════════════════

def jaccard(set_a: set, set_b: set) -> float:
    """Jaccard-Ähnlichkeit zweier Mengen."""
    if not set_a and not set_b:
        return 0.0
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def get_fields(entry: dict) -> dict:
    """Extrahiert relevante Felder aus Entry, Steckbrief bevorzugt."""
    sb = entry.get("steckbrief", {})
    return {
        "einrichtung": sb.get("einrichtung") or entry.get("einrichtung") or "",
        "ort": sb.get("ort") or entry.get("ort") or "",
        "datum": sb.get("datum") or entry.get("datum") or "",
        "bundesland": sb.get("bundesland") or "",
        "brandort": sb.get("brandort") or "",
    }


def similarity_score(entry_a: dict, entry_b: dict) -> tuple[float, dict]:
    """
    Berechnet Ähnlichkeits-Score zwischen zwei Einträgen.

    Gewichtung:
      - Datum:        0.30  (exakt=1.0, ±1 Tag=0.7, ±2 Tage=0.3)
      - Ort:          0.30  (Jaccard auf Wörter)
      - Einrichtung:  0.25  (Jaccard auf Wörter)
      - Bundesland:   0.10  (exakt=1.0)
      - Brandort:     0.05  (Jaccard auf Wörter)

    Returns: (score, detail_dict) — score zwischen 0.0 und 1.0
    """
    fa = get_fields(entry_a)
    fb = get_fields(entry_b)
    details = {}

    # ── Datum (0.30) ──
    da = parse_datum(fa["datum"])
    db = parse_datum(fb["datum"])
    if da and db:
        diff = abs((da - db).days)
        if diff == 0:
            datum_sim = 1.0
        elif diff == 1:
            datum_sim = 0.7
        elif diff == 2:
            datum_sim = 0.3
        else:
            datum_sim = 0.0
    elif not da and not db:
        datum_sim = 0.0  # Kein Signal — kein Score
    else:
        datum_sim = 0.0  # Einer fehlt
    details["datum"] = datum_sim

    # ── Ort (0.30) ──
    ort_a = extract_words(fa["ort"])
    ort_b = extract_words(fb["ort"])
    ort_sim = jaccard(ort_a, ort_b) if (ort_a and ort_b) else 0.0
    # Boost: wenn ein Ort substring des anderen ist
    na, nb = normalize(fa["ort"]), normalize(fb["ort"])
    if na and nb and (na in nb or nb in na):
        ort_sim = max(ort_sim, 0.85)
    details["ort"] = ort_sim

    # ── Einrichtung (0.25) ──
    einr_a = extract_words(fa["einrichtung"])
    einr_b = extract_words(fb["einrichtung"])
    einr_sim = jaccard(einr_a, einr_b) if (einr_a and einr_b) else 0.0
    # Boost: Substring-Match auf normalisierten Gesamtstring
    ea, eb = normalize(fa["einrichtung"]), normalize(fb["einrichtung"])
    if ea and eb and (ea in eb or eb in ea):
        einr_sim = max(einr_sim, 0.80)
    details["einrichtung"] = einr_sim

    # ── Bundesland (0.10) ──
    bla = normalize(fa["bundesland"])
    blb = normalize(fb["bundesland"])
    if bla and blb:
        bl_sim = 1.0 if bla == blb else 0.0
    else:
        bl_sim = 0.0  # Fehlend = kein Signal
    details["bundesland"] = bl_sim

    # ── Brandort (0.05) ──
    bo_a = extract_words(fa["brandort"])
    bo_b = extract_words(fb["brandort"])
    bo_sim = jaccard(bo_a, bo_b) if (bo_a and bo_b) else 0.0
    details["brandort"] = bo_sim

    # ── Gewichteter Score ──
    score = (
        0.30 * datum_sim
        + 0.30 * ort_sim
        + 0.25 * einr_sim
        + 0.10 * bl_sim
        + 0.05 * bo_sim
    )
    details["total"] = round(score, 3)

    return score, details


# ══════════════════════════════════════════════════════════════════════════════
# Cluster-Bildung (Union-Find)
# ══════════════════════════════════════════════════════════════════════════════

class UnionFind:
    """Einfache Union-Find-Struktur für Cluster-Bildung."""
    def __init__(self, n):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1

    def clusters(self):
        groups = defaultdict(list)
        for i in range(len(self.parent)):
            groups[self.find(i)].append(i)
        return list(groups.values())


# ══════════════════════════════════════════════════════════════════════════════
# Merge-Logik
# ══════════════════════════════════════════════════════════════════════════════

STATUS_PRIORITY = {
    "enriched": 5,
    "partial": 4,
    "pending": 3,
    "failed": 2,
    "false_positive": 1,
}


def pick_best_value(*values):
    """Nimmt den ersten nicht-leeren, nicht-'unbekannt' Wert."""
    for v in values:
        if v and v != "unbekannt" and v != "—":
            return v
    for v in values:
        if v:
            return v
    return ""


def merge_steckbriefe(steckbriefe: list) -> dict:
    """Verschmilzt mehrere Steckbriefe — nimmt pro Feld den besten Wert."""
    if not steckbriefe:
        return {}
    if len(steckbriefe) == 1:
        return steckbriefe[0].copy()

    all_keys = set()
    for sb in steckbriefe:
        all_keys.update(sb.keys())

    merged = {}
    for key in all_keys:
        values = [sb.get(key, "") for sb in steckbriefe]
        if key == "zusammenfassung":
            best = max(values, key=lambda x: len(x) if x else 0)
            merged[key] = best or ""
        else:
            merged[key] = pick_best_value(*values)
    return merged


def ensure_quellen(entry: dict):
    """Stellt sicher, dass der Eintrag ein quellen-Array hat."""
    if "quellen" not in entry:
        entry["quellen"] = [{
            "link": entry.get("resolved_url") or entry.get("link", ""),
            "quelle": entry.get("quelle", ""),
            "titel": entry.get("titel", ""),
            "source_url": entry.get("source_url", ""),
        }]


def merge_group(entries: list) -> dict:
    """Verschmilzt eine Gruppe von Einträgen zum selben Brand-Ereignis."""
    if len(entries) == 1:
        ensure_quellen(entries[0])
        return entries[0]

    # Sort by status priority (best first)
    entries.sort(
        key=lambda e: STATUS_PRIORITY.get(e.get("enrichment_status", "pending"), 0),
        reverse=True,
    )

    primary = entries[0]
    merged = primary.copy()

    # Steckbrief mergen
    steckbriefe = [e["steckbrief"] for e in entries if e.get("steckbrief")]
    if steckbriefe:
        merged["steckbrief"] = merge_steckbriefe(steckbriefe)

    # Quellen-Array aufbauen
    quellen = []
    seen_links = set()
    for e in entries:
        # Existing quellen-Array (von vorherigem Merge)?
        if e.get("quellen"):
            for q in e["quellen"]:
                link = q.get("link", "")
                if link and link not in seen_links:
                    seen_links.add(link)
                    quellen.append(q)
        else:
            link = e.get("resolved_url") or e.get("link", "")
            if link and link not in seen_links:
                seen_links.add(link)
                quellen.append({
                    "link": link,
                    "quelle": e.get("quelle", ""),
                    "titel": e.get("titel", ""),
                    "source_url": e.get("source_url", ""),
                    "enrichment_status": e.get("enrichment_status", "pending"),
                })
    merged["quellen"] = quellen

    # Besten Status nehmen
    best_status = max(
        (e.get("enrichment_status", "pending") for e in entries),
        key=lambda s: STATUS_PRIORITY.get(s, 0),
    )
    merged["enrichment_status"] = best_status

    # Metadaten
    erfasst_dates = [e["erfasst_am"] for e in entries if e.get("erfasst_am")]
    if erfasst_dates:
        merged["erfasst_am"] = min(erfasst_dates)

    enriched_dates = [e["enriched_am"] for e in entries if e.get("enriched_am")]
    if enriched_dates:
        merged["enriched_am"] = max(enriched_dates)

    # False-Positive-Grund
    if best_status == "false_positive":
        fp_gruende = [e["false_positive_grund"] for e in entries if e.get("false_positive_grund")]
        if fp_gruende:
            merged["false_positive_grund"] = fp_gruende[0]
    else:
        merged.pop("false_positive_grund", None)

    # Primär-Link
    for e in entries:
        if e.get("enrichment_status") == "enriched":
            merged["link"] = e.get("link", "")
            merged["resolved_url"] = e.get("resolved_url", "")
            merged["resolve_method"] = e.get("resolve_method", "")
            break

    # Top-Level-Felder
    for field in ["einrichtung", "ort", "datum", "titel"]:
        vals = [e.get(field, "") for e in entries]
        merged[field] = pick_best_value(*vals)

    # Audit-Trail
    original_hashes = []
    for e in entries:
        if e.get("merged_from"):
            original_hashes.extend(e["merged_from"])
        elif e.get("hash"):
            original_hashes.append(e["hash"])
    if len(original_hashes) > 1:
        merged["merged_from"] = list(dict.fromkeys(original_hashes))  # deduplicate, keep order

    merged["hash"] = entries[0].get("hash", "")

    return merged


# ══════════════════════════════════════════════════════════════════════════════
# Hauptlogik
# ══════════════════════════════════════════════════════════════════════════════

def load_confirmed_merges() -> set:
    """Lädt vom Nutzer bestätigte Merge-Paare."""
    if not CANDIDATES_FILE.exists():
        return set()
    try:
        data = json.loads(CANDIDATES_FILE.read_text())
        confirmed = set()
        for c in data.get("confirmed", []):
            pair = tuple(sorted(c.get("hashes", [])))
            if len(pair) == 2:
                confirmed.add(pair)
        return confirmed
    except Exception:
        return set()


def load_rejected_merges() -> set:
    """Lädt vom Nutzer abgelehnte Merge-Paare."""
    if not CANDIDATES_FILE.exists():
        return set()
    try:
        data = json.loads(CANDIDATES_FILE.read_text())
        rejected = set()
        for c in data.get("rejected", []):
            pair = tuple(sorted(c.get("hashes", [])))
            if len(pair) == 2:
                rejected.add(pair)
        return rejected
    except Exception:
        return set()


def deduplicate(db: dict) -> dict:
    """
    Führt Duplikat-Zusammenführung auf der Datenbank durch.

    Zweistufig:
      1. Alle Paare scoren → auto-merge ab THRESHOLD, Kandidaten zwischen MIN und THRESHOLD
      2. Vom Nutzer bestätigte Kandidaten werden ebenfalls gemergt
    """
    entries = db.get("entries", [])
    if not entries:
        log("Keine Einträge vorhanden — nichts zu tun.")
        return db

    n = len(entries)
    log(f"Starte Dedup für {n} Einträge")

    # Nutzer-Entscheidungen laden
    confirmed_merges = load_confirmed_merges()
    rejected_merges = load_rejected_merges()
    log(f"Bestätigte Merges: {len(confirmed_merges)}, Abgelehnte: {len(rejected_merges)}")

    # ── Paarweises Scoring ──
    # Optimierung: nur Einträge mit mindestens Ort ODER Datum vergleichen
    # und Vorsortierung nach Bundesland
    uf = UnionFind(n)
    candidates = []

    # Für O(n²)-Vermeidung: Vorab-Gruppierung nach Bundesland + Datum-Monat
    buckets = defaultdict(list)
    for i, e in enumerate(entries):
        f = get_fields(e)
        bl = normalize(f["bundesland"]) or "_"
        d = parse_datum(f["datum"])
        month_key = f"{d.year}-{d.month:02d}" if d else "_"
        # In eigenen Bucket + Nachbar-Monate (für Monatsgrenz-Brände)
        buckets[(bl, month_key)].append(i)
        if d:
            prev = d.replace(day=1) - timedelta(days=1)
            buckets[(bl, f"{prev.year}-{prev.month:02d}")].append(i)

    compared = set()
    auto_merge_count = 0

    for bucket_indices in buckets.values():
        for ii in range(len(bucket_indices)):
            for jj in range(ii + 1, len(bucket_indices)):
                i, j = bucket_indices[ii], bucket_indices[jj]
                pair_key = (min(i, j), max(i, j))
                if pair_key in compared:
                    continue
                compared.add(pair_key)

                score, details = similarity_score(entries[i], entries[j])

                # Hash-Paar für Nutzer-Entscheidungen
                hi = entries[i].get("hash", "")
                hj = entries[j].get("hash", "")
                hash_pair = tuple(sorted([hi, hj])) if hi and hj else None

                # Vom Nutzer abgelehnt? → Skip
                if hash_pair and hash_pair in rejected_merges:
                    continue

                # Vom Nutzer bestätigt? → Auto-Merge
                if hash_pair and hash_pair in confirmed_merges:
                    uf.union(i, j)
                    auto_merge_count += 1
                    fa, fb = get_fields(entries[i]), get_fields(entries[j])
                    log(f"Nutzer-bestätigt: {fa['einrichtung'][:40]} ↔ {fb['einrichtung'][:40]} (Score {score:.2f})")
                    continue

                if score >= AUTO_MERGE_THRESHOLD:
                    uf.union(i, j)
                    auto_merge_count += 1
                    fa, fb = get_fields(entries[i]), get_fields(entries[j])
                    log(f"Auto-Merge ({score:.2f}): {fa['einrichtung'][:40]} / {fa['ort'][:20]} ↔ {fb['einrichtung'][:40]} / {fb['ort'][:20]}")
                elif score >= CANDIDATE_MIN:
                    candidates.append({
                        "i": i, "j": j,
                        "score": round(score, 3),
                        "details": details,
                        "hashes": [hi, hj] if hi and hj else [],
                    })

    log(f"Paare verglichen: {len(compared)}")
    log(f"Auto-Merges: {auto_merge_count}")
    log(f"Kandidaten (unsicher): {len(candidates)}")

    # ── Cluster bilden und mergen ──
    clusters = uf.clusters()
    merged_entries = []
    total_merged = 0

    for cluster in clusters:
        group = [entries[i] for i in cluster]
        if len(group) > 1:
            total_merged += len(group) - 1
            names = [get_fields(e)["einrichtung"][:40] or "?" for e in group]
            log(f"Cluster {len(group)}x: {', '.join(names[:3])}")
        merged_entry = merge_group(group)
        merged_entries.append(merged_entry)

    log(f"Ergebnis: {len(merged_entries)} Einträge (war: {n}, {total_merged} zusammengeführt)")

    db["entries"] = merged_entries

    # ── Kandidaten-Datei schreiben ──
    # Bestehende Entscheidungen beibehalten
    existing = {}
    if CANDIDATES_FILE.exists():
        try:
            existing = json.loads(CANDIDATES_FILE.read_text())
        except Exception:
            existing = {}

    # Neue Kandidaten aufbereiten (nur die, die nicht schon entschieden sind)
    new_candidates = []
    for c in candidates:
        hi, hj = entries[c["i"]].get("hash", ""), entries[c["j"]].get("hash", "")
        hash_pair = tuple(sorted([hi, hj])) if hi and hj else None
        if hash_pair and (hash_pair in confirmed_merges or hash_pair in rejected_merges):
            continue

        fi = get_fields(entries[c["i"]])
        fj = get_fields(entries[c["j"]])
        ei, ej = entries[c["i"]], entries[c["j"]]
        new_candidates.append({
            "hashes": [hi, hj],
            "score": c["score"],
            "details": c["details"],
            "entry_a": {
                "einrichtung": fi["einrichtung"],
                "ort": fi["ort"],
                "datum": fi["datum"],
                "bundesland": fi["bundesland"],
                "status": ei.get("enrichment_status", "pending"),
                "link": ei.get("resolved_url") or ei.get("link", ""),
                "titel": ei.get("titel", ""),
            },
            "entry_b": {
                "einrichtung": fj["einrichtung"],
                "ort": fj["ort"],
                "datum": fj["datum"],
                "bundesland": fj["bundesland"],
                "status": ej.get("enrichment_status", "pending"),
                "link": ej.get("resolved_url") or ej.get("link", ""),
                "titel": ej.get("titel", ""),
            },
        })

    # Sortieren: höchster Score zuerst
    new_candidates.sort(key=lambda c: c["score"], reverse=True)

    candidates_data = {
        "generated_at": datetime.now().isoformat(),
        "auto_merge_threshold": AUTO_MERGE_THRESHOLD,
        "candidate_min_threshold": CANDIDATE_MIN,
        "pending": new_candidates,
        "confirmed": existing.get("confirmed", []),
        "rejected": existing.get("rejected", []),
    }

    CANDIDATES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CANDIDATES_FILE, "w") as f:
        json.dump(candidates_data, f, ensure_ascii=False, indent=2)

    log(f"Kandidaten-Datei: {len(new_candidates)} pending, {len(existing.get('confirmed', []))} confirmed, {len(existing.get('rejected', []))} rejected")

    return db


def main():
    if not DB_FILE.exists():
        log(f"Datenbankdatei nicht gefunden: {DB_FILE}")
        return

    with open(DB_FILE) as f:
        db = json.load(f)

    entries_before = len(db.get("entries", []))
    db = deduplicate(db)
    entries_after = len(db.get("entries", []))

    with open(DB_FILE, "w") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    log(f"Gespeichert: {entries_before} → {entries_after} Einträge")


if __name__ == "__main__":
    main()
```

---

**2. `docs/index.html`** — die hast du gerade erst aktualisiert. Die einzige neue Änderung gegenüber dem Code, den du eben hochgeladen hast, sind zwei Zeilen in den Kandidaten-Karten. Suche im Edit-Modus nach `Bundesland / Status` — es gibt zwei Stellen (für entry_a und entry_b). Jeweils **direkt nach** der Zeile `<div class="field-value">${a.bundesland...` bzw. `${b.bundesland...` und **vor** `</div>` (dem schließenden cand-entry div) diese Zeile einfügen:

Für Entry A (nach `${a.bundesland || '—'} · ${a.status || '—'}</div>`):
```
          ${a.link ? `<a href="${a.link}" target="_blank" style="color:var(--accent);font-size:0.75rem;margin-top:0.3rem;display:inline-block;" onclick="event.stopPropagation()">🔗 Quelle prüfen</a>` : ''}
```

Für Entry B (nach `${b.bundesland || '—'} · ${b.status || '—'}</div>`):
```
          ${b.link ? `<a href="${b.link}" target="_blank" style="color:var(--accent);font-size:0.75rem;margin-top:0.3rem;display:inline-block;" onclick="event.stopPropagation()">🔗 Quelle prüfen</a>` : ''}
