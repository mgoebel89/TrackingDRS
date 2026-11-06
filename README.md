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
| E+ | Anfragen als Vorgänge mit Gesprächsverlauf: Nachrichten von Team und Lehrkraft, interne Notizen, Ereignisse; Status offen / in Bearbeitung / erledigt, Übernehmen, Ungelesen-Zähler; Eingang für Lehrkräfte; Bestelllisten als Vorgang | fertig |
| F | Fotos vom Aufbau (Team und Lehrkraft), Mindmap als Bild oder PDF, private Lehrernotizen, eigene Projektvorlagen, Excel-Export (.xlsx) im Sheet-Layout, Projektbericht als Druckansicht (PDF) mit Tafeln, Archiv nach Schuljahr, endgültig löschen, ZIP-Sicherung | fertig |
| G | WireGuard-Anbindung (Zugriff von zuhause): Einrichtung im Lehrerbereich (Werte oder Client-Datei), Sperre auf dem VPS, täglicher Sperrtest; Probelauf | gebaut, Probelauf offen |
| I | Überarbeitung nach dem ersten Test (Konzept Fassung 13): „Tätigkeit“ statt „Aufgabe“; Lehrerbereich für alle Teilnehmer des VPN (auch Heimnetz mit 192.168er-Adressen); Anfragen mit großen Reitern, Statuskarte zum Einreichfenster, drei Ständen, zuständiger Lehrkraft und Bestellprüfung per Auswahlliste mit Firma-Frage ans Team; Projekttage als Wochenansicht, Termin buchen im Fenster; Tafel mit neuer Werkzeugleiste, Textmarker, haftenden Pfeilen, Stickern, Rahmen (als Ergebnis mit Bild, wandern mit) und Wiederholen; PDF und PNG nach der Besprechung | fertig (0.10.6) |
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
| `trackingdrs sicherung` | Sicherung (ZIP) nach `/var/lib/trackingdrs/sicherungen` |
| `trackingdrs vpn einrichten` | WireGuard zum VPN-Server einrichten (fragt Server, Schlüssel, Adresse; zeigt den Block für die Server-Config) |
| `trackingdrs vpn status` | Verbindung, letzten Handshake und Sperrtest zeigen |
| `trackingdrs vpn sperrtest` | versuchen, über das VPN Server und Heimnetz zu erreichen (alles muss „gesperrt“ sein) |
| `trackingdrs einrichtungscode` | Code für die erste Einrichtung zeigen |
| `trackingdrs konten` | Lehrkraft-Konten auflisten |
| `trackingdrs passwort <kürzel>` | vorläufiges Passwort setzen und Konto entsperren |
| `journalctl -u trackingdrs -f` | Protokoll der Webseite |

Daten: `/var/lib/trackingdrs` (SQLite-Datenbank, Zertifikate). Programm: `/opt/trackingdrs` (gehört root).

**VPN (von zuhause):** `trackingdrs vpn einrichten` macht den Container zum Teilnehmer im vorhandenen WireGuard-VPN.
Gebraucht werden die Adresse und der `ListenPort` des Servers, sein öffentlicher Schlüssel (auf dem Server
`wg show wg0 public-key`, nicht der `PrivateKey` aus der Config) und eine freie VPN-Adresse für den Container. Der
Schlüssel des Containers entsteht im Container und verlässt ihn nicht; am Ende steht der `[Peer]`-Block zum Einfügen
auf dem Server (`AllowedIPs` nur die eine Adresse). Über das VPN ist nur HTTPS erreichbar. Die VPN-Adresse kommt ins
Zertifikat; liegt sie außerhalb des Schulnetzes, entsteht dabei einmalig eine neue Zertifizierungsstelle (Stamm-
zertifikat auf den Geräten neu installieren). Darum das VPN am besten vor dem Verteilen des Zertifikats einrichten.

**VPN ohne Konsole:** Dasselbe geht unter *Einstellungen → VPN* (nur Admins, mit dem eigenen Passwort bestätigt):
Adresse und Port des VPS, sein öffentlicher Schlüssel und die VPN-Adresse eingeben. Danach zeigt die Seite die
Erweiterung für die Server-Config, die Befehle für den VPS zum Kopieren (eintragen, Sperre, Kontrolle) und die
Config des Containers; *Verbindung prüfen* testet sofort. Wie beim Update legt der Webdienst nur einen Auftrag in
`/var/lib/trackingdrs/vpn` ab, `trackingdrs-vpn-anfrage.path` startet `trackingdrs-vpn anfrage` als root, das die
Angaben noch einmal prüft. Hast du schon eine WireGuard-Datei für den Container (mit dessen PrivateKey, Address und
dem Server als `[Peer]`, gern mit PresharedKey), wählst du im Formular *Config-Datei* und lädst sie hoch; an der
Konsole geht dasselbe mit `trackingdrs vpn einrichten --conf datei.conf`. „Alles über den Tunnel“ (`0.0.0.0/0`) wird
dabei auf das VPN-Netz beschränkt, DNS nicht übernommen. Der private Schlüssel landet nur in `/etc/wireguard`, die Seite
zeigt ihn nie wieder an. Den privaten Schlüssel des Servers fragt die Seite nie ab.

**Sperre auf dem VPN-Server:** Damit der Container über das VPN nichts erreicht (auch nicht, wenn ihn jemand als root
übernimmt), kommt auf den Server einmalig `vps/sperre.sh`:

```bash
curl -fsSLO https://raw.githubusercontent.com/mgoebel89/TrackingDRS/main/vps/sperre.sh
sudo bash sperre.sh einrichten 10.8.0.20
```

Es legt eine eigene nft-Tabelle an (andere Regeln, auch ufw, bleiben unberührt) und lädt sie bei jedem Start vor dem
Netz: Vom Container kommen nur Antworten durch, jede neue Verbindung von ihm wird verworfen (Server, Heimnetz, andere
Teilnehmer). Zum Container sind neue Verbindungen nur auf HTTPS erlaubt. `bash sperre.sh status` zeigt die Regeln mit
Zählern, `bash sperre.sh aus` entfernt sie. Der Container prüft das täglich selbst (`trackingdrs-sperrtest.timer`:
Ping und TCP 22/53/80/443/8080 an Server, Fritzbox und Nachbaradressen); kommt etwas durch, zeigt der Lehrerbereich
im Cockpit eine rote Warnung, den Stand unter *Einstellungen → VPN*.

**Update ohne Konsole:** Unter *Einstellungen → Version und Update* sehen Admins die installierte Version und ob es auf
GitHub eine neuere gibt (geprüft wird täglich und auf Knopfdruck). *Jetzt aktualisieren* legt erst eine Sicherung an
(die letzten fünf bleiben, herunterladbar auf derselben Seite) und führt dann `trackingdrs-update` aus. Der Webdienst
selbst darf nichts installieren: Er legt nur eine Anfrage-Datei in `/var/lib/trackingdrs/update` ab, systemd startet
daraufhin `trackingdrs-selbstupdate` als root (`trackingdrs-update-*.path`, `-pruefen.timer`). Ergebnisse und
Protokoll stehen in `/var/lib/trackingdrs-update`.

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
