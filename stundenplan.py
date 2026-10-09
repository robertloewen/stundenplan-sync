#!/usr/bin/env python3
"""Stundenplan-Sync: liest Termine aus dem öffentlichen AlmaWeb-Vorlesungsverzeichnis
der Uni Leipzig und schreibt sie als abonnierbare .ics-Datei.

Kein Login nötig. Konfiguration in config.toml.
Aufruf:  python stundenplan.py [--config config.toml] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://almaweb.uni-leipzig.de"
START = (BASE + "/scripts/mgrqispi.dll?APPNAME=CampusNet&PRGNAME=EXTERNALPAGES"
         "&ARGUMENTS=-N000000000000001,-N000405,-Acc")
USER_AGENT = "stundenplan-sync/1.0 (privater Kalender-Export, 1x taeglich)"

MONATE = {
    "jan": 1, "feb": 2, "mär": 3, "mar": 3, "märz": 3, "apr": 4, "mai": 5,
    "jun": 6, "juni": 6, "jul": 7, "juli": 7, "aug": 8, "sep": 9, "sept": 9,
    "okt": 10, "nov": 11, "dez": 12,
}
ARTEN = {
    "VL": "Vorlesung", "ÜB": "Übung", "UE": "Übung", "VÜ": "Vorlesung/Übung",
    "SE": "Seminar", "TU": "Tutorium", "PR": "Praktikum", "KO": "Kolloquium",
}
MODUL_RE = re.compile(r"^(\d{2}-\d{3}-\d{4})\s")
KURS_RE = re.compile(r"^(\d{2}-\d{3}-\d{4}\.([A-ZÄÖÜ]+)\d+)\s+(.+)$")
DATUM_RE = re.compile(r"(\d{1,2})\.\s*([A-Za-zÄÖÜäöü]+)\.?\s*(\d{4})")
ZEIT_RE = re.compile(r"(\d{1,2}):(\d{2})")


class SyncFehler(Exception):
    pass


@dataclass(frozen=True)
class Termin:
    kurs_nr: str
    titel: str
    art: str
    beginn: dt.datetime
    ende: dt.datetime
    raum: str
    lehrende: str


# ---------------------------------------------------------------- Abruf

def text(el) -> str:
    return " ".join(el.get_text(" ").split())


class AlmaWeb:
    def __init__(self, pause: float = 1.5, session: requests.Session | None = None):
        self.pause = pause
        self.s = session or requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self._erster = True

    def get(self, url: str) -> BeautifulSoup:
        if not self._erster:
            time.sleep(self.pause)
        self._erster = False
        r = self.s.get(urljoin(BASE, url), timeout=30)
        r.raise_for_status()
        # Bytes übergeben: BeautifulSoup erkennt die Kodierung aus dem <meta charset>.
        # (requests nimmt ohne charset-Header ISO-8859-1 an und zerlegt sonst die Umlaute.)
        return BeautifulSoup(r.content, "html.parser")


def links(soup: BeautifulSoup) -> list[tuple[str, str]]:
    return [(text(a), a["href"]) for a in soup.find_all("a", href=True) if text(a)]


def folge(soup: BeautifulSoup, linktext: str) -> str:
    """URL des Links mit diesem Text. Erst exakte Übereinstimmung, dann eindeutiger Präfix."""
    alle = links(soup)
    exakt = [h for t, h in alle if t == linktext]
    if exakt:
        return exakt[0]
    praefix = {h for t, h in alle if t.startswith(linktext) and not t.endswith(">")}
    if len(praefix) == 1:
        return praefix.pop()
    vorhanden = " | ".join(t for t, _ in alle[-40:])
    raise SyncFehler(f"Link '{linktext}' nicht gefunden (Treffer: {len(praefix)}). "
                     f"Links auf der Seite: {vorhanden}")


# ---------------------------------------------------------------- Parsen

def parse_datum(s: str) -> dt.date:
    m = DATUM_RE.search(s)
    if not m:
        raise SyncFehler(f"Datum nicht lesbar: {s!r}")
    tag, monat, jahr = m.groups()
    key = monat.lower().rstrip(".")
    nr = MONATE.get(key) or MONATE.get(key[:3])
    if not nr:
        raise SyncFehler(f"Monat nicht lesbar: {s!r}")
    return dt.date(int(jahr), nr, int(tag))


def parse_zeit(s: str) -> dt.time:
    m = ZEIT_RE.search(s)
    if not m:
        raise SyncFehler(f"Uhrzeit nicht lesbar: {s!r}")
    return dt.time(int(m.group(1)), int(m.group(2)))


def zellwert(td) -> str:
    # Jede Zelle enthält ein (mobiles) Label und den Wert in span.break-words
    span = td.find("span", class_="break-words")
    return text(span if span else td)


def parse_kursseite(soup: BeautifulSoup, kurs_nr: str, titel: str, art: str) -> list[Termin]:
    tabelle = next((t for t in soup.find_all("table")
                    if any(text(th) == "Raum" for th in t.find_all("th"))), None)
    if tabelle is None:
        return []
    termine = []
    for tr in tabelle.find_all("tr"):
        zellen = tr.find_all("td", class_="tbdata")
        if len(zellen) < 5:
            continue
        werte = [zellwert(td) for td in zellen]
        _, datum, von, bis, raum, *rest = werte
        tag = parse_datum(datum)
        termine.append(Termin(
            kurs_nr=kurs_nr, titel=titel, art=art,
            beginn=dt.datetime.combine(tag, parse_zeit(von)),
            ende=dt.datetime.combine(tag, parse_zeit(bis)),
            raum=raum, lehrende=rest[0] if rest else "",
        ))
    return termine


# ---------------------------------------------------------------- Ablauf

def sammle_termine(cfg: dict, client: AlmaWeb) -> list[Termin]:
    alma = cfg["almaweb"]
    soup = client.get(START)
    for schritt in [alma["semester"], *alma["pfad"]]:
        soup = client.get(folge(soup, schritt))

    module = {}
    for t, h in links(soup):
        m = MODUL_RE.match(t)
        if m and m.group(1) not in module:
            module[m.group(1)] = h
    if not module:
        raise SyncFehler("Keine Module auf der Semesterseite gefunden")

    gewuenscht = set(cfg["almaweb"].get("veranstaltungen") or [])
    kurse: dict[str, tuple[str, str, str]] = {}
    for url in module.values():
        for t, h in links(client.get(url)):
            m = KURS_RE.match(t)
            if m and "COURSEDETAILS" in h and m.group(1) not in kurse:
                if not gewuenscht or m.group(1) in gewuenscht:
                    kurse[m.group(1)] = (m.group(3), m.group(2), h)

    fehlend = gewuenscht - kurse.keys()
    if fehlend:
        raise SyncFehler(f"Veranstaltungen nicht gefunden: {', '.join(sorted(fehlend))}")

    termine: list[Termin] = []
    for nr, (titel, kuerzel, url) in sorted(kurse.items()):
        neu = parse_kursseite(client.get(url), nr, titel, ARTEN.get(kuerzel, kuerzel))
        print(f"  {nr:<22} {len(neu):>3} Termine  {titel}")
        termine += neu
    if not termine:
        raise SyncFehler("Keine Termine gefunden – Seitenaufbau geändert?")
    return sorted(termine, key=lambda x: (x.beginn, x.kurs_nr))


# ---------------------------------------------------------------- iCalendar

VTIMEZONE = """BEGIN:VTIMEZONE
TZID:Europe/Berlin
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE""".splitlines()


def esc(s: str) -> str:
    return (s.replace("\\", "\\\\").replace(";", "\\;")
             .replace(",", "\\,").replace("\n", "\\n"))


def falten(zeile: str) -> str:
    # RFC 5545: Zeilen max. 75 Oktette, Fortsetzung mit führendem Leerzeichen
    out, teil = [], ""
    for ch in zeile:
        if len((teil + ch).encode()) > (75 if not out else 74):
            out.append(teil)
            teil = ""
        teil += ch
    out.append(teil)
    return "\r\n ".join(out)


def baue_ics(termine: list[Termin], name: str, stempel: str) -> str:
    f = "%Y%m%dT%H%M%S"
    z = ["BEGIN:VCALENDAR", "VERSION:2.0",
         "PRODID:-//stundenplan-sync//AlmaWeb Uni Leipzig//DE",
         "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
         f"X-WR-CALNAME:{esc(name)}", "X-WR-TIMEZONE:Europe/Berlin",
         "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H",
         *VTIMEZONE]
    for t in termine:
        uid = re.sub(r"[^A-Za-z0-9.-]", "_", f"{t.kurs_nr}-{t.beginn:%Y%m%dT%H%M}")
        beschreibung = f"{t.art} · {t.kurs_nr}"
        if t.lehrende:
            beschreibung += f"\nLehrende: {t.lehrende}"
        z += ["BEGIN:VEVENT",
              f"UID:{uid}@stundenplan-sync",
              f"DTSTAMP:{stempel}",
              f"DTSTART;TZID=Europe/Berlin:{t.beginn.strftime(f)}",
              f"DTEND;TZID=Europe/Berlin:{t.ende.strftime(f)}",
              f"SUMMARY:{esc(t.titel)} ({esc(t.art)})",
              f"LOCATION:{esc(t.raum)}",
              f"DESCRIPTION:{esc(beschreibung)}",
              "END:VEVENT"]
    z.append("END:VCALENDAR")
    return "\r\n".join(falten(x) for x in z) + "\r\n"


def ohne_stempel(ics: str) -> str:
    return re.sub(r"^DTSTAMP:.*$", "", ics, flags=re.M)


def schreibe(ziel: Path, termine: list[Termin], name: str) -> bool:
    """Schreibt nur bei inhaltlicher Änderung. Gibt True zurück, wenn geschrieben wurde."""
    stempel = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    neu = baue_ics(termine, name, stempel)
    if ziel.exists() and ohne_stempel(ziel.read_bytes().decode("utf-8")) == ohne_stempel(neu):
        return False
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(neu, "utf-8", newline="")
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--dry-run", action="store_true", help="nur abrufen, nichts schreiben")
    args = ap.parse_args(argv)
    cfg = tomllib.loads(Path(args.config).read_text("utf-8"))
    try:
        termine = sammle_termine(cfg, AlmaWeb(pause=cfg["almaweb"].get("pause", 1.5)))
    except (SyncFehler, requests.RequestException) as e:
        # Bei Fehlern bleibt die letzte gute .ics unverändert online
        print(f"FEHLER: {e}", file=sys.stderr)
        return 1
    print(f"{len(termine)} Termine gesamt")
    if args.dry_run:
        return 0
    ziel = Path(cfg["kalender"]["datei"])
    geaendert = schreibe(ziel, termine, cfg["kalender"]["name"])
    print("Kalender aktualisiert" if geaendert else "Keine Änderungen")
    return 0


if __name__ == "__main__":
    sys.exit(main())
