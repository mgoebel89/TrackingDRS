# TrackingDRS

Projektarbeit im Blick: ein Container für die Schule, der das Tracking-Sheet, die Besprechungen und die Anfragen eines
Schülerprojekts zusammenführt, von der ersten Idee bis zum Demonstrator. Entwickelt für die Mechatronik an der
David-Roentgen-Schule Neuwied.

Jede Eingabe ist ein Eintrag mit Zeitstempel. Raster, Ampeln, Versionen und die Kurzzusammenfassung für die
Besprechung werden daraus berechnet.

## Stand

| Stufe | Inhalt | Stand |
|---|---|---|
| A | Grundgerüst: Installation, Lehrkraft-Konten, HTTPS, Firewall, Projekte, Teams, Team-Link, Standardvorlage | fertig |
| B | Tracking-Sheet: Raster mit Plan und Ampel, Verantwortliche, Meilensteine, Basisplan, Vergleich, Handyansicht „Diese Woche“, Schul-Logo | fertig (Versionen zum Buchungsschluss kommen mit C) |
| C1 | Projektzeiten als Regeln (Wochentag, jede/gerade/ungerade KW), Ferien, Ausfälle, einzelne Tage anpassen, Termine buchen und umbuchen bis zum Buchungsschluss, Version zum Buchungsschluss, Häkchen „erledigt“, Warnungen, Team-Links über HTTP | fertig |
| C2 | Cockpit (Handlungsbedarf, zwei Wochen, Projektkarten, Ampel-Matrix), Kalender (Monat, Halbjahr), Aktivitäten, Dienstkalender je Lehrkraft und Schulkalender (Ferien) als ICS-Abo | fertig |
| D1 | Besprechung: Vorbereitung des Teams (Stand, Fragen, Themen, Ideen), Kurzzusammenfassung ohne KI, Lehrernotizen, Ergebnis (Absprachen, Aufträge mit Frist, Meilensteine), Abschließen mit Protokoll, Aufträge abhaken, Warnung „Auftrag überfällig“ | fertig |
| D2 | Besprechungstafel (Smartboard): Zonen, Stift mit Druckstufen, Radierer, Post-its ziehen (in Ergebnis-Zonen werden sie zu Absprache, Auftrag, Meilenstein), live von Schülergeräten (Post-its, Fotos), Fenster auf dem zweiten Bildschirm, beim Abschließen eingefroren | fertig |
| E | Anfragen (Rückfrage, auch über die Tafel; Material ausleihen; Abnahme mit Foto) mit Status und Verlauf; Bestellliste: sammeln, im Einreichfenster einreichen (auch Sonderfenster), Prüfung je Position (bestellen, SchulLager, Firma, ersetzen, ablehnen), Status bis ausgegeben, Sammelbestellung je Lieferant als CSV und Druckansicht | fertig |
| F | Fotos vom Aufbau (Team und Lehrkraft), Mindmap als Bild oder PDF, private Lehrernotizen, eigene Projektvorlagen, Excel-Export (.xlsx) im Sheet-Layout, Projektbericht als Druckansicht (PDF) mit Tafeln, Archiv nach Schuljahr, endgültig löschen, ZIP-Sicherung | fertig |
| G | WireGuard-Anbindung (Zugriff von zuhause), Probelauf | geplant |
| H | optional: Anbindung an SchulLager | geplant |

## Installation (Proxmox VE)

Auf dem Proxmox-Host in der Shell des Knotens:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/mgoebel89/TrackingDRS/main/proxmox/trackingdrs.sh)"
```

Das Skript legt einen unprivilegierten Ubuntu-24.04-Container an und installiert TrackingDRS. Am Ende zeigt es die
Adresse und den Einrichtungscode. Im Browser `https://<container>/einrichtung` öffnen und das erste Admin-Konto anlegen.

Ohne Proxmox, in einem vorhandenen Ubuntu-24.04- oder Debian-12-System als root:

```bash
git clone https://github.com/mgoebel89/TrackingDRS /opt/trackingdrs && bash /opt/trackingdrs/deploy/install.sh
```

**HTTPS:** Der Container stellt sich sein Zertifikat mit einer eigenen kleinen Zertifizierungsstelle aus. Damit der
Browser nicht warnt, das Stammzertifikat von `http://<container>/ca.crt` auf den Lehrer-Geräten installieren. Die
Zertifizierungsstelle darf nur für das Netz des Containers ausstellen.

**Team-Links über HTTP:** Die Schülergeräte haben das Stammzertifikat nicht. Deshalb bedient Port 80 die Team-Seiten
(`/t/<link>`) und ihre Schnittstelle direkt; alles andere (Anmeldung, Lehrerbereich) leitet nach HTTPS um bzw. wird
abgelehnt. Der Lehrerbereich zeigt den Team-Link schon mit `http://` an.

## Betrieb

| Befehl (im Container) | Wirkung |
|---|---|
| `trackingdrs-update` | neuesten Stand holen und neu installieren, Daten bleiben |
| `trackingdrs einrichtungscode` | Code für die erste Einrichtung zeigen |
| `trackingdrs konten` | Lehrkraft-Konten auflisten |
| `trackingdrs passwort <kürzel>` | vorläufiges Passwort setzen und Konto entsperren |
| `journalctl -u trackingdrs -f` | Protokoll der Webseite |

Daten: `/var/lib/trackingdrs` (SQLite-Datenbank, Zertifikate). Programm: `/opt/trackingdrs` (gehört root).

## Entwicklung

Python 3.11 oder neuer. Für die Kalender-Abos zusätzlich `icalendar` und `recurring-ical-events` (im Container `python3-icalendar`, `python3-recurring-ical-events`; ohne sie läuft alles andere weiter). Im Repo-Ordner:

```bash
python3 -m unittest discover -s tests
```

```bash
python3 tests/dev_server.py 8461
```

Der Testserver läuft ohne HTTPS auf `http://127.0.0.1:8461` und legt seine Daten in `.dev-daten/` ab.
Den Einrichtungscode zeigt `TRACKINGDRS_DATEN=.dev-daten python3 -m app.cli einrichtungscode`.

| Ordner | Inhalt |
|---|---|
| `app/` | Server (`server.py`), Datenbank (`db.py`), Konten, Projekte, Tracking-Sheet (`sheet.py`), Termine (`termine.py`), Konsolenbefehle, Vorlagen |
| `web/` | Seiten, Stil und Skripte der Oberfläche (ohne Build-Schritt) |
| `deploy/` | Installation, Update, Dienste, Zertifikat, Firewall |
| `proxmox/` | Einzeiler für den Proxmox-Host |
| `tests/` | automatische Tests und lokaler Testserver |
