"""Tests mit nachgebauten AlmaWeb-Seiten (Aufbau vom 10.10.2026 übernommen)."""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stundenplan as sp  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

D = "/scripts/mgrqispi.dll?APPNAME=CampusNet&PRGNAME="


def seite(*links):
    return "<html><body><main>" + "".join(
        f'<a href="{h}">{t}</a>' for t, h in links) + "</main></body></html>"


def zeile(nr, datum, von, bis, raum, lehrende):
    zellen = "".join(
        f'<td class="tbdata table-cell rw"><div><span class="min-w-32 lg:hidden">{lab}</span>'
        f'<span class="break-words whitespace-normal"> {wert} </span></div></td>'
        for lab, wert in [("", nr), ("Datum", datum), ("Von", von), ("Bis", bis),
                          ("Raum", f'<a href="{D}ROOM">{raum}</a>'), ("Lehrende", lehrende)])
    return f'<tr class="table-row">{zellen}</tr>'


def kursseite(titel, *zeilen):
    kopf = "".join(f'<th class="max-lg:hidden">{x}</th>'
                   for x in ["", "Datum", "Von", "Bis", "Raum", "Lehrende "])
    return (f"<html><body><main><h1> {titel} </h1>"
            f'<table class="tb"><tr><th>Phase</th><th>Start</th></tr></table>'
            f'<table class="tb list rw-table"><thead><tr class="rw-hide">{kopf}</tr></thead>'
            f"<tbody>{''.join(zeilen)}</tbody></table></main></body></html>")


SEITEN = {
    sp.START: seite(("WiSe 2026/27", D + "SEM"), ("SoSe 2026", D + "ALT")),
    D + "SEM": seite(("07 - Wirtschaftswissenschaftliche Fakultät", D + "FAK")),
    D + "FAK": seite(("07 - Wirtschaftswissenschaftliche Fakultät >", D + "FAK"),
                     ("Bachelor", D + "BA"), ("Master", D + "MA")),
    D + "BA": seite(("Bachelor >", D + "BA"), ("Wirtschaftswissenschaften", D + "WIWI"),
                    ("Wirtschaftsinformatik (alte Prüfungsordnung)", D + "X")),
    D + "WIWI": seite(("Pflichtbereich", D + "PFL")),
    D + "PFL": seite(("Empfehlung für das 1. Fachsemester", D + "FS1"),
                     ("Empfehlung für das 3. Fachsemester", D + "FS3")),
    D + "FS1": seite(("07-101-1106 Technik des Rechnungswesen (5 LP)", D + "MOD1"),
                     ("02-101-1107 Bürgerliches und Öffentliches Recht (5 LP)", D + "MOD2")),
    D + "MOD1": seite(
        ("07-101-1106 Technik des Rechnungswesen", D + "MODULEDETAILS1"),
        ("07-101-1106.VL01 Technik des Rechnungswesen", D + "COURSEDETAILS&A=1"),
        ("07-101-1106.VL01 Technik des Rechnungswesen", D + "COURSEDETAILS&A=1"),
        ("07-101-1106.ÜB01 Technik des Rechnungswesen", D + "COURSEDETAILS&A=2")),
    D + "MOD2": seite(("02-101-1107.VL02 Öffentliches Recht", D + "COURSEDETAILS&A=3")),
    D + "COURSEDETAILS&A=1": kursseite(
        "07-101-1106.VL01 Technik des Rechnungswesen",
        zeile(1, "Di, 13. Okt. 2026", "11:15", "12:45", "Hörsaal 9 H2.030", "Prof. Dr. Matthias Schmidt"),
        zeile(2, "Di, 5. Jan. 2027", "11:15", "12:45", "Hörsaal 9 H2.030", "Prof. Dr. Matthias Schmidt")),
    D + "COURSEDETAILS&A=2": kursseite(
        "07-101-1106.ÜB01 Technik des Rechnungswesen",
        zeile(1, "Mi, 14. Okt. 2026", "17:15", "18:45", "Hörsaal 9 H2.030", "PD Dr. Esther Pittroff")),
    D + "COURSEDETAILS&A=3": kursseite(
        "02-101-1107.VL02 Öffentliches Recht",
        zeile(1, "Mo, 19. Okt. 2026", "17:15", "18:45", "Hörsaal 3 H1.028", "N. N.")),
}


class FakeClient:
    def __init__(self):
        self.abrufe = []

    def get(self, url):
        self.abrufe.append(url)
        return BeautifulSoup(SEITEN[url], "html.parser")


CFG = {"almaweb": {"semester": "WiSe 2026/27", "pfad": [
    "07 - Wirtschaftswissenschaftliche Fakultät", "Bachelor", "Wirtschaftswissenschaften",
    "Pflichtbereich", "Empfehlung für das 1. Fachsemester"], "veranstaltungen": []}}


def test_alle_termine():
    c = FakeClient()
    t = sp.sammle_termine(CFG, c)
    assert len(t) == 4
    assert t[0].beginn == dt.datetime(2026, 10, 13, 11, 15)
    assert t[0].raum == "Hörsaal 9 H2.030"
    assert t[0].art == "Vorlesung"
    assert t[-1].beginn == dt.datetime(2027, 1, 5, 11, 15)
    # doppelte Links werden nur einmal abgerufen
    assert c.abrufe.count(D + "COURSEDETAILS&A=1") == 1


def test_filter_und_fehlende():
    cfg = {"almaweb": dict(CFG["almaweb"], veranstaltungen=["07-101-1106.ÜB01"])}
    t = sp.sammle_termine(cfg, FakeClient())
    assert [x.art for x in t] == ["Übung"]
    cfg["almaweb"]["veranstaltungen"] = ["07-101-1106.ÜB02"]
    try:
        sp.sammle_termine(cfg, FakeClient())
        raise AssertionError("Fehler erwartet")
    except sp.SyncFehler as e:
        assert "ÜB02" in str(e)


def test_ics(tmp_path):
    t = sp.sammle_termine(CFG, FakeClient())
    ziel = tmp_path / "docs" / "s.ics"
    assert sp.schreibe(ziel, t, "Test, Kalender") is True
    ics = ziel.read_bytes().decode("utf-8")
    assert ics.count("BEGIN:VEVENT") == 4
    assert "DTSTART;TZID=Europe/Berlin:20261013T111500" in ics
    assert "X-WR-CALNAME:Test\\, Kalender" in ics
    assert all(len(z.encode()) <= 75 for z in ics.split("\r\n"))
    # zweiter Lauf ohne Änderung schreibt nicht
    assert sp.schreibe(ziel, t, "Test, Kalender") is False


def test_monate():
    for s, m in [("Mo, 2. März 2027", 3), ("Di, 1. Dez. 2026", 12), ("Fr, 4. Juni 2027", 6),
                 ("Mi, 3. Sept. 2027", 9), ("Do, 7. Mai 2027", 5)]:
        assert sp.parse_datum(s).month == m
