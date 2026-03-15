#!/usr/bin/env python3
"""
Einmaliges Reset-Script: Setzt alle false_positive und enriched-Einträge zurück,
die mit fehlerhafter Google News URL-Auflösung erstellt wurden.

Lauf: python reset_false_positives.py
Danach: Datei löschen (nicht dauerhaft im Repo behalten).
"""

import json
from pathlib import Path

DB_FILE = Path(__file__).parent / "data" / "braende.json"

with open(DB_FILE, "r", encoding="utf-8") as f:
    db = json.load(f)

reset_count = 0
entries = db.get("entries", [])

for entry in entries:
    status = entry.get("enrichment_status", "")

    # Alle false_positive zurücksetzen (waren durch Google Boilerplate falsch klassifiziert)
    if status == "false_positive":
        entry.pop("enrichment_status", None)
        entry.pop("enriched_am", None)
        entry.pop("false_positive_grund", None)
        entry.pop("resolve_method", None)
        entry.pop("resolved_url", None)
        reset_count += 1

    # Auch die "enriched" mit nur wenig Zeichen zurücksetzen (fehlende Volltexte)
    elif status == "enriched" and entry.get("artikel_laenge", 9999) < 200:
        entry.pop("enrichment_status", None)
        entry.pop("enriched_am", None)
        entry.pop("steckbrief", None)
        entry.pop("artikel_laenge", None)
        entry.pop("resolve_method", None)
        entry.pop("resolved_url", None)
        reset_count += 1

    # Auch "partial" Einträge zurücksetzen (Snippet-basiert, können jetzt besser werden)
    elif status == "partial":
        entry.pop("enrichment_status", None)
        entry.pop("enriched_am", None)
        entry.pop("steckbrief", None)
        entry.pop("artikel_laenge", None)
        entry.pop("resolve_method", None)
        entry.pop("resolved_url", None)
        reset_count += 1

    # failed zurücksetzen (hatten keine Chance mit funktionierendem Decoder)
    elif status == "failed":
        entry.pop("enrichment_status", None)
        entry.pop("enriched_am", None)
        entry.pop("resolve_method", None)
        entry.pop("resolved_url", None)
        reset_count += 1

with open(DB_FILE, "w", encoding="utf-8") as f:
    json.dump(db, f, ensure_ascii=False, indent=2)

print(f"Reset abgeschlossen: {reset_count} Einträge zurückgesetzt")
print(f"Total Einträge: {len(entries)}")
print("Alle Einträge werden beim nächsten Enrichment-Lauf neu verarbeitet.")
