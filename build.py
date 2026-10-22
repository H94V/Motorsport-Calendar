#!/usr/bin/env python3
"""Génère un fichier .ics par série dans docs/ (publié ensuite sur GitHub Pages).

- Séries "auto" : récupérées via le paquet `motorsport-calendar` (commande `motocal`).
- Séries "manuelles" : lues dans data/<cle>.csv (voir data/_exemple.csv).

Si une récupération échoue, l'ancien fichier de docs/ est conservé.
"""
import csv
import datetime as dt
import hashlib
import subprocess
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"
DATA = ROOT / "data"
TODAY = dt.date.today()
YEARS = [TODAY.year, TODAY.year + 1]
PRODID = "-//H94V//motorsport-calendar//FR"

# clé -> nom affiché. Les clés auto correspondent aux commandes `motocal generate-<clé>`.
AUTO = {
    "f1": "Formule 1",
    "f2": "Formule 2",
    "f3": "Formule 3",
    "wec": "WEC",
    "elms": "ELMS",
    "motogp": "MotoGP",
}
# clé -> nom affiché. Chaque clé attend un fichier data/<clé>.csv
MANUAL = {
    "f1academy": "F1 Academy",
    "formulae": "Formule E",
    "imsa": "IMSA WeatherTech",
    "indycar": "IndyCar",
    "nascar": "NASCAR Cup",
    "wrc": "WRC",
    "dakar": "Dakar",
    "gtwceurope": "GT World Challenge Europe",
    "alms": "Asian Le Mans Series",
    "nurb24": "24h du Nürburgring",
    "macau": "Grand Prix de Macao",
    "goodwood": "Goodwood",
    "monacohistorique": "Monaco Historique",
    "michelinpilot": "Michelin Pilot Challenge",
    "vpsportscar": "VP SportsCar Challenge",
    "mx5cup": "MX-5 Cup",
    "supercup": "Porsche Supercup",
}


def esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def write_ics(path: Path, name: str, vtimezones: list, events: list) -> None:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}",
             "CALSCALE:GREGORIAN", f"X-WR-CALNAME:{esc(name)}"]
    for block in vtimezones + events:
        lines.extend(block.splitlines())
    lines.append("END:VCALENDAR")
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))


def extract_blocks(text: str, tag: str) -> list:
    blocks, current = [], None
    for line in text.replace("\r\n", "\n").split("\n"):
        if line == f"BEGIN:{tag}":
            current = [line]
        elif line == f"END:{tag}" and current is not None:
            current.append(line)
            blocks.append("\n".join(current))
            current = None
        elif current is not None:
            current.append(line)
    return blocks


def build_auto(key: str, name: str) -> None:
    events, vtz = [], []
    for year in YEARS:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.ics"
            result = subprocess.run(
                ["motocal", f"generate-{key}", str(year), str(out)],
                capture_output=True, text=True)
            if result.returncode != 0 or not out.exists():
                print(f"[{key}] {year}: indisponible ({result.stderr.strip()[:120]})")
                continue
            text = out.read_text(encoding="utf-8")
            events += extract_blocks(text, "VEVENT")
            for z in extract_blocks(text, "VTIMEZONE"):
                if z not in vtz:
                    vtz.append(z)
    if not events:
        print(f"[{key}] aucun événement : ancien fichier conservé")
        return
    write_ics(DOCS / f"{key}.ics", name, vtz, events)
    print(f"[{key}] {len(events)} sessions")


def build_manual(key: str, name: str) -> None:
    src = DATA / f"{key}.csv"
    if not src.exists():
        return
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    events = []
    with src.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if not row.get("date"):
                continue
            tz = ZoneInfo(row["timezone"].strip())
            start = dt.datetime.fromisoformat(
                f"{row['date'].strip()}T{row['time'].strip()}").replace(tzinfo=tz)
            end = start + dt.timedelta(minutes=int(row["duration_min"]))
            start_u = start.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            end_u = end.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            title = f"{name} - {row['event'].strip()} - {row['session'].strip()}"
            uid = hashlib.sha1(
                f"{key}|{row['date']}|{row['time']}|{row['event']}|{row['session']}"
                .encode()).hexdigest() + "@h94v-motorsport"
            lines = ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{now}",
                     f"DTSTART:{start_u}", f"DTEND:{end_u}", f"SUMMARY:{esc(title)}"]
            if row.get("location", "").strip():
                lines.append(f"LOCATION:{esc(row['location'].strip())}")
            lines.append("END:VEVENT")
            events.append("\n".join(lines))
    if not events:
        return
    write_ics(DOCS / f"{key}.ics", name, [], events)
    print(f"[{key}] {len(events)} sessions (manuel)")


def write_index() -> None:
    names = {**AUTO, **MANUAL}
    items = []
    for f in sorted(DOCS.glob("*.ics")):
        label = names.get(f.stem, f.stem)
        items.append(f'<li><a href="{f.name}">{label}</a> <code>{f.name}</code></li>')
    html = ("<!doctype html><meta charset='utf-8'><title>Calendriers sport mécanique</title>"
            "<h1>Calendriers</h1><p>Copie l'adresse d'un lien dans Google Agenda "
            "(Autres agendas → À partir de l'URL).</p><ul>" + "".join(items) + "</ul>")
    (DOCS / "index.html").write_text(html, encoding="utf-8")


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    for key, name in AUTO.items():
        try:
            build_auto(key, name)
        except Exception as exc:  # une série en panne ne bloque pas les autres
            print(f"[{key}] erreur : {exc}")
    for key, name in MANUAL.items():
        try:
            build_manual(key, name)
        except Exception as exc:
            print(f"[{key}] erreur : {exc}")
    write_index()


if __name__ == "__main__":
    main()
