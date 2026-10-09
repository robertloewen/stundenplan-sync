# Stundenplan-Sync

Holt die Termine aus dem **öffentlichen** AlmaWeb-Vorlesungsverzeichnis der Uni Leipzig
und stellt sie als abonnierbaren Kalender (`.ics`) bereit. Kein Login, keine Zugangsdaten.

- Läuft täglich per GitHub Actions (ca. 05:17 Uhr)
- Veröffentlicht über GitHub Pages: `https://<account>.github.io/<repo>/`
- Bei Fehlern bleibt die letzte funktionierende Version online

## Einrichtung (einmalig)

1. Repo auf GitHub anlegen (**öffentlich**) und diese Dateien pushen.
2. *Settings → Pages*: unter *Build and deployment* bei Source **GitHub Actions** wählen.
3. *Actions*-Tab → **Stundenplan aktualisieren** → **Run workflow**. Nach ca. 1 Minute liegt
   `docs/stundenplan.ics` im Repo.
4. `https://<account>.github.io/<repo>/` öffnen → **Im Kalender abonnieren**.
   Diese Seite kannst du an Kommilitonen schicken.

## Neues Semester

In `config.toml` anpassen:

- `semester`, z. B. `"SoSe 2027"`
- letzter Eintrag in `pfad`, z. B. `"Empfehlung für das 2. Fachsemester"`
- ggf. `name` des Kalenders

Die Linktexte müssen so lauten wie im Vorlesungsverzeichnis.
Bei mehreren Übungsgruppen die gewünschten Nummern in `veranstaltungen` eintragen.

## Lokal testen

```
pip install -r requirements.txt pytest
pytest -q
python stundenplan.py --dry-run
```
