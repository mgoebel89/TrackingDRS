"""Datenbank (SQLite): Verbindung, Schema-Migrationen, Zeit und Ereignisprotokoll.

Grundsatz: Jede Aenderung an einem Projekt landet zusaetzlich als Zeile in `ereignis` (nur anhaengen, nie aendern).
Daraus entstehen spaeter Verlauf, Versionen und Vergleich. Die uebrigen Tabellen halten den aktuellen Stand.
"""
import datetime
import json
import os
import sqlite3

try:
    from zoneinfo import ZoneInfo
    ZONE = ZoneInfo("Europe/Berlin")
except Exception:   # Windows ohne tzdata (lokales Testen): Ortszeit des Rechners
    ZONE = None

VORLAGEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vorlagen")
OHNE_FK = "ohne_fk"   # Kennzeichen einer Migration, die eine Tabelle neu aufbaut


def jetzt():
    """Aktuelle Zeit in Berlin als ISO-Text ohne Zeitzone, sekundengenau (so steht sie in der Datenbank)."""
    t = datetime.datetime.now(ZONE) if ZONE else datetime.datetime.now()
    return t.replace(tzinfo=None, microsecond=0).isoformat()


def heute():
    return datetime.date.fromisoformat(jetzt()[:10])


def verbinden(pfad):
    con = sqlite3.connect(pfad, timeout=10, isolation_level=None)   # Autocommit; Transaktionen mit transaktion()
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 10000")
    return con


class transaktion:
    """with transaktion(con): ... -> BEGIN IMMEDIATE / COMMIT, bei Fehler ROLLBACK."""

    def __init__(self, con):
        self.con = con

    def __enter__(self):
        self.con.execute("BEGIN IMMEDIATE")
        return self.con

    def __exit__(self, art, wert, spur):
        self.con.execute("COMMIT" if art is None else "ROLLBACK")
        return False


def _vorlagen_einlesen(con):
    for datei in sorted(os.listdir(VORLAGEN_DIR)):
        if datei.endswith(".json"):
            with open(os.path.join(VORLAGEN_DIR, datei), encoding="utf-8") as f:
                daten = json.load(f)
            con.execute("INSERT OR IGNORE INTO vorlage (schluessel, name, daten) VALUES (?, ?, ?)",
                        (datei[:-5], daten["name"], json.dumps(daten, ensure_ascii=False)))


MIGRATIONEN = [
    # 1: Grundgeruest (Stufe A)
    """
    CREATE TABLE einstellung (schluessel TEXT PRIMARY KEY, wert TEXT NOT NULL);
    CREATE TABLE lehrkraft (
        id INTEGER PRIMARY KEY,
        kuerzel TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        rolle TEXT NOT NULL CHECK (rolle IN ('admin', 'lehrkraft')),
        pw TEXT NOT NULL,
        pw_vorlaeufig INTEGER NOT NULL DEFAULT 1,
        gesperrt INTEGER NOT NULL DEFAULT 0,
        stand INTEGER NOT NULL DEFAULT 1,
        erstellt TEXT NOT NULL);
    CREATE TABLE abgemeldet (signatur TEXT PRIMARY KEY, ablauf INTEGER NOT NULL);
    CREATE TABLE vorlage (schluessel TEXT PRIMARY KEY, name TEXT NOT NULL, daten TEXT NOT NULL);
    CREATE TABLE projekt (
        id INTEGER PRIMARY KEY,
        titel TEXT NOT NULL,
        klasse TEXT NOT NULL DEFAULT '',
        schuljahr TEXT NOT NULL DEFAULT '',
        beschreibung TEXT NOT NULL DEFAULT '',
        start TEXT NOT NULL,
        ende TEXT NOT NULL,
        link_token TEXT NOT NULL UNIQUE,
        archiviert INTEGER NOT NULL DEFAULT 0,
        erstellt TEXT NOT NULL);
    CREATE TABLE projekt_lehrkraft (
        projekt_id INTEGER NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id),
        PRIMARY KEY (projekt_id, lehrkraft_id));
    CREATE TABLE mitglied (
        id INTEGER PRIMARY KEY,
        projekt_id INTEGER NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
        vorname TEXT NOT NULL,
        nachname TEXT NOT NULL,
        kuerzel TEXT NOT NULL,
        aktiv INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE phase (
        id INTEGER PRIMARY KEY,
        projekt_id INTEGER NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
        pos INTEGER NOT NULL,
        name TEXT NOT NULL);
    CREATE TABLE aufgabe (
        id INTEGER PRIMARY KEY,
        projekt_id INTEGER NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
        phase_id INTEGER NOT NULL REFERENCES phase(id) ON DELETE CASCADE,
        pos INTEGER NOT NULL,
        titel TEXT NOT NULL,
        aus_vorlage INTEGER NOT NULL DEFAULT 0,
        verantwortlich_id INTEGER REFERENCES mitglied(id),
        verworfen INTEGER NOT NULL DEFAULT 0,
        erstellt TEXT NOT NULL);
    CREATE TABLE ereignis (
        id INTEGER PRIMARY KEY,
        zeit TEXT NOT NULL,
        projekt_id INTEGER REFERENCES projekt(id) ON DELETE CASCADE,
        wer_art TEXT NOT NULL CHECK (wer_art IN ('lehrkraft', 'team', 'system')),
        wer TEXT NOT NULL,
        art TEXT NOT NULL,
        daten TEXT NOT NULL DEFAULT '{}');
    CREATE INDEX ereignis_projekt ON ereignis (projekt_id, id);
    """,
    # 2: Tracking-Sheet (Stufe B). Wochen werden als Datum ihres Montags gespeichert (ISO-Text).
    """
    ALTER TABLE aufgabe ADD COLUMN ende TEXT;
    ALTER TABLE aufgabe ADD COLUMN ende_ursprung TEXT;
    CREATE TABLE zelle (
        aufgabe_id INTEGER NOT NULL REFERENCES aufgabe(id) ON DELETE CASCADE,
        woche TEXT NOT NULL,
        plan INTEGER NOT NULL DEFAULT 0,
        ampel TEXT CHECK (ampel IN ('g', 'y', 'r')),
        PRIMARY KEY (aufgabe_id, woche));
    CREATE TABLE problem (
        id INTEGER PRIMARY KEY,
        aufgabe_id INTEGER NOT NULL REFERENCES aufgabe(id) ON DELETE CASCADE,
        woche TEXT NOT NULL,
        ampel TEXT NOT NULL CHECK (ampel IN ('y', 'r')),
        problem TEXT NOT NULL,
        massnahme TEXT NOT NULL,
        verantwortlich_id INTEGER REFERENCES mitglied(id),
        zeit TEXT NOT NULL,
        wer_art TEXT NOT NULL,
        wer TEXT NOT NULL);
    CREATE TABLE meilenstein (
        id INTEGER PRIMARY KEY,
        projekt_id INTEGER NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
        woche TEXT NOT NULL,
        titel TEXT NOT NULL,
        verworfen INTEGER NOT NULL DEFAULT 0,
        erstellt TEXT NOT NULL);
    CREATE TABLE version (
        id INTEGER PRIMARY KEY,
        projekt_id INTEGER NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
        art TEXT NOT NULL CHECK (art IN ('basisplan', 'buchungsschluss')),
        name TEXT NOT NULL,
        zeit TEXT NOT NULL,
        aktiv INTEGER NOT NULL DEFAULT 1,
        daten TEXT NOT NULL);
    CREATE INDEX version_projekt ON version (projekt_id, id);
    """,
    # 3: Termine (Stufe C1). Projektzeiten sind Regeln, daraus entstehen die Projekttage mit ihren Terminen.
    # Datum als ISO-Text, Uhrzeit als HH:MM. Nichts wird geloescht, nur deaktiviert (aktiv = 0).
    """
    CREATE TABLE projektzeit (
        id INTEGER PRIMARY KEY,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id),
        klasse TEXT NOT NULL,
        wochentag INTEGER NOT NULL CHECK (wochentag BETWEEN 0 AND 6),
        rhythmus TEXT NOT NULL CHECK (rhythmus IN ('jede', 'gerade', 'ungerade')),
        von TEXT NOT NULL,
        bis TEXT NOT NULL,
        fenster_von TEXT NOT NULL,
        fenster_bis TEXT NOT NULL,
        laenge INTEGER NOT NULL,
        schluss_tage INTEGER NOT NULL DEFAULT 1,
        schluss_zeit TEXT NOT NULL DEFAULT '18:00',
        gueltig_von TEXT NOT NULL,
        gueltig_bis TEXT NOT NULL,
        aktiv INTEGER NOT NULL DEFAULT 1,
        erstellt TEXT NOT NULL);
    CREATE TABLE projekttag (
        projektzeit_id INTEGER NOT NULL REFERENCES projektzeit(id),
        datum TEXT NOT NULL,
        gestrichen INTEGER NOT NULL DEFAULT 0,
        fenster_von TEXT,
        fenster_bis TEXT,
        laenge INTEGER,
        grund TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (projektzeit_id, datum));
    CREATE TABLE ausfall (
        id INTEGER PRIMARY KEY,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id),
        klasse TEXT NOT NULL DEFAULT '',
        von TEXT NOT NULL,
        bis TEXT NOT NULL,
        grund TEXT NOT NULL,
        aktiv INTEGER NOT NULL DEFAULT 1,
        erstellt TEXT NOT NULL);
    CREATE TABLE ferien (
        id INTEGER PRIMARY KEY,
        von TEXT NOT NULL,
        bis TEXT NOT NULL,
        name TEXT NOT NULL,
        quelle TEXT NOT NULL DEFAULT 'hand' CHECK (quelle IN ('hand', 'abo')),
        aktiv INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE buchung (
        id INTEGER PRIMARY KEY,
        projekt_id INTEGER NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
        projektzeit_id INTEGER NOT NULL REFERENCES projektzeit(id),
        datum TEXT NOT NULL,
        uhrzeit TEXT NOT NULL,
        woche TEXT NOT NULL,
        aktiv INTEGER NOT NULL DEFAULT 1,
        zeit TEXT NOT NULL,
        wer_art TEXT NOT NULL,
        wer TEXT NOT NULL);
    CREATE UNIQUE INDEX buchung_platz ON buchung (projektzeit_id, datum, uhrzeit) WHERE aktiv = 1;
    CREATE UNIQUE INDEX buchung_woche ON buchung (projekt_id, woche) WHERE aktiv = 1;
    ALTER TABLE aufgabe ADD COLUMN erledigt TEXT;
    ALTER TABLE version ADD COLUMN woche TEXT;
    CREATE UNIQUE INDEX version_woche ON version (projekt_id, woche) WHERE art = 'buchungsschluss'
    """,
    # 4: Kalender-Abos (Stufe C2). Dienstkalender je Lehrkraft, Schulkalender (lehrkraft_id NULL) fuer die Ferien.
    # kalender_termin ist ein Spiegel des letzten Abrufs und wird bei jedem Abruf neu geschrieben.
    """
    CREATE TABLE kalender_abo (
        id INTEGER PRIMARY KEY,
        art TEXT NOT NULL CHECK (art IN ('dienst', 'schule')),
        lehrkraft_id INTEGER REFERENCES lehrkraft(id),
        url TEXT NOT NULL,
        versuch TEXT,
        stand TEXT,
        fehler TEXT,
        anzahl INTEGER NOT NULL DEFAULT 0);
    CREATE UNIQUE INDEX kalender_abo_wer ON kalender_abo (art, COALESCE(lehrkraft_id, 0));
    CREATE TABLE kalender_termin (
        abo_id INTEGER NOT NULL REFERENCES kalender_abo(id) ON DELETE CASCADE,
        beginn TEXT NOT NULL,
        ende TEXT NOT NULL,
        ganztags INTEGER NOT NULL DEFAULT 0,
        titel TEXT NOT NULL,
        ort TEXT NOT NULL DEFAULT '');
    CREATE INDEX kalender_termin_zeit ON kalender_termin (abo_id, beginn)
    """,
    # 5: Besprechungen (Stufe D). Eine je Projekt und Woche. Eintraege sind die Post-its: Fragen und Themen des Teams,
    # Ideen, Ergebnisse (Absprache, Auftrag mit Frist, Meilenstein). zone/x/y sind fuer die Tafel (D2).
    """
    CREATE TABLE besprechung (
        id INTEGER PRIMARY KEY,
        projekt_id INTEGER NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
        woche TEXT NOT NULL,
        vorbereitung TEXT NOT NULL DEFAULT '',
        vorbereitet TEXT,
        notizen TEXT NOT NULL DEFAULT '',
        abgeschlossen TEXT,
        abgeschlossen_von TEXT,
        protokoll TEXT,
        UNIQUE (projekt_id, woche));
    CREATE TABLE eintrag (
        id INTEGER PRIMARY KEY,
        projekt_id INTEGER NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
        besprechung_id INTEGER REFERENCES besprechung(id),
        art TEXT NOT NULL CHECK (art IN ('frage', 'thema', 'idee', 'auftrag', 'absprache', 'meilenstein')),
        text TEXT NOT NULL,
        frist TEXT,
        verantwortlich_id INTEGER REFERENCES mitglied(id),
        erledigt TEXT,
        verworfen INTEGER NOT NULL DEFAULT 0,
        zone TEXT,
        x REAL,
        y REAL,
        erstellt TEXT NOT NULL,
        wer_art TEXT NOT NULL,
        wer TEXT NOT NULL);
    CREATE INDEX eintrag_projekt ON eintrag (projekt_id, id)
    """,
    # 6: Besprechungstafel (Stufe D2). Striche und Positionen der Post-its je Besprechung; Fotos als Datei im Ordner
    # bilder/ (eintrag.bild = Dateiname ohne Endung).
    """
    ALTER TABLE eintrag ADD COLUMN bild TEXT;
    CREATE TABLE tafel (
        besprechung_id INTEGER PRIMARY KEY REFERENCES besprechung(id) ON DELETE CASCADE,
        striche TEXT NOT NULL DEFAULT '[]',
        positionen TEXT NOT NULL DEFAULT '{}',
        stand INTEGER NOT NULL DEFAULT 0,
        aktualisiert TEXT)
    """,
    # 7: Anfragen und Bestelllisten (Stufe E). Status-Wechsel stehen im Ereignisprotokoll.
    """
    CREATE TABLE anfrage (
        id INTEGER PRIMARY KEY,
        projekt_id INTEGER NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
        art TEXT NOT NULL CHECK (art IN ('rueckfrage', 'ausleihe', 'abnahme')),
        titel TEXT NOT NULL,
        text TEXT NOT NULL DEFAULT '',
        aufgabe_id INTEGER REFERENCES aufgabe(id),
        menge TEXT NOT NULL DEFAULT '',
        von TEXT,
        bis TEXT,
        bild TEXT,
        in_besprechung INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        antwort TEXT NOT NULL DEFAULT '',
        erstellt TEXT NOT NULL,
        geaendert TEXT NOT NULL,
        geaendert_von TEXT);
    CREATE INDEX anfrage_projekt ON anfrage (projekt_id, id);
    ALTER TABLE eintrag ADD COLUMN anfrage_id INTEGER REFERENCES anfrage(id);
    CREATE TABLE bestellfenster (
        id INTEGER PRIMARY KEY,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id),
        klasse TEXT NOT NULL DEFAULT '',
        projekt_id INTEGER REFERENCES projekt(id),
        von TEXT NOT NULL,
        bis TEXT NOT NULL,
        aktiv INTEGER NOT NULL DEFAULT 1,
        erstellt TEXT NOT NULL);
    CREATE TABLE bestellliste (
        id INTEGER PRIMARY KEY,
        projekt_id INTEGER NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
        fenster_id INTEGER REFERENCES bestellfenster(id),
        eingereicht TEXT,
        geprueft TEXT,
        geprueft_von TEXT);
    CREATE TABLE position (
        id INTEGER PRIMARY KEY,
        liste_id INTEGER NOT NULL REFERENCES bestellliste(id) ON DELETE CASCADE,
        artikel TEXT NOT NULL,
        bestellnr TEXT NOT NULL DEFAULT '',
        menge INTEGER NOT NULL DEFAULT 1,
        preis TEXT NOT NULL DEFAULT '',
        lieferant TEXT NOT NULL DEFAULT '',
        aufgabe_id INTEGER REFERENCES aufgabe(id),
        begruendung TEXT NOT NULL DEFAULT '',
        gestrichen INTEGER NOT NULL DEFAULT 0,
        entscheidung TEXT CHECK (entscheidung IN ('bestellen', 'lager', 'firma', 'ersetzen', 'ablehnen')),
        menge_genehmigt INTEGER,
        kommentar TEXT NOT NULL DEFAULT '',
        ersatz_artikel TEXT,
        ersatz_bestellnr TEXT,
        ersatz_lieferant TEXT,
        ersatz_weg TEXT CHECK (ersatz_weg IN ('bestellen', 'lager')),
        status TEXT,
        aus_position INTEGER REFERENCES position(id),
        erstellt TEXT NOT NULL);
    CREATE INDEX position_liste ON position (liste_id, id)
    """,
    # 8: Extras (Stufe F). Fotos des Teams und die Mindmap als Datei im Ordner bilder/, private Lehrernotizen.
    """
    CREATE TABLE datei (
        id INTEGER PRIMARY KEY,
        projekt_id INTEGER NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
        art TEXT NOT NULL CHECK (art IN ('foto', 'mindmap')),
        name TEXT NOT NULL,
        typ TEXT NOT NULL,
        titel TEXT NOT NULL DEFAULT '',
        aufgabe_id INTEGER REFERENCES aufgabe(id) ON DELETE SET NULL,
        verworfen INTEGER NOT NULL DEFAULT 0,
        erstellt TEXT NOT NULL,
        wer_art TEXT NOT NULL,
        wer TEXT NOT NULL);
    CREATE INDEX datei_projekt ON datei (projekt_id, id);
    CREATE TABLE notiz (
        id INTEGER PRIMARY KEY,
        projekt_id INTEGER NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        erstellt TEXT NOT NULL,
        geaendert TEXT,
        wer TEXT NOT NULL,
        verworfen INTEGER NOT NULL DEFAULT 0)
    """,
    # 9: Anfragen als Vorgaenge mit Gespraechsverlauf. Die Tabelle anfrage wird neu aufgebaut (neue Art 'bestellung',
    # Status des Vorgangs, Zustaendigkeit); bisherige Antworten werden Nachrichten, eingereichte Listen Vorgaenge.
    (OHNE_FK, """
    CREATE TABLE anfrage_neu (
        id INTEGER PRIMARY KEY,
        projekt_id INTEGER NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
        art TEXT NOT NULL CHECK (art IN ('rueckfrage', 'ausleihe', 'abnahme', 'bestellung')),
        titel TEXT NOT NULL,
        text TEXT NOT NULL DEFAULT '',
        aufgabe_id INTEGER REFERENCES aufgabe(id),
        menge TEXT NOT NULL DEFAULT '',
        von TEXT,
        bis TEXT,
        bild TEXT,
        in_besprechung INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        antwort TEXT NOT NULL DEFAULT '',
        erstellt TEXT NOT NULL,
        geaendert TEXT NOT NULL,
        geaendert_von TEXT,
        stand TEXT NOT NULL DEFAULT 'offen' CHECK (stand IN ('offen', 'bearbeitung', 'erledigt')),
        zustaendig_id INTEGER REFERENCES lehrkraft(id),
        bestellliste_id INTEGER REFERENCES bestellliste(id) ON DELETE CASCADE);
    INSERT INTO anfrage_neu (id, projekt_id, art, titel, text, aufgabe_id, menge, von, bis, bild, in_besprechung, status, antwort,
        erstellt, geaendert, geaendert_von, stand)
        SELECT id, projekt_id, art, titel, text, aufgabe_id, menge, von, bis, bild, in_besprechung, status, antwort, erstellt, geaendert,
        geaendert_von, CASE WHEN status = 'neu' THEN 'offen'
            WHEN status IN ('beantwortet', 'zurueck', 'abgelehnt', 'freigegeben', 'zurueckgezogen') THEN 'erledigt' ELSE 'bearbeitung' END
        FROM anfrage;
    DROP TABLE anfrage;
    ALTER TABLE anfrage_neu RENAME TO anfrage;
    CREATE INDEX anfrage_projekt ON anfrage (projekt_id, id);
    CREATE TABLE nachricht (
        id INTEGER PRIMARY KEY,
        anfrage_id INTEGER NOT NULL REFERENCES anfrage(id) ON DELETE CASCADE,
        art TEXT NOT NULL CHECK (art IN ('nachricht', 'intern', 'ereignis')),
        text TEXT NOT NULL DEFAULT '',
        bild TEXT,
        daten TEXT NOT NULL DEFAULT '{}',
        zeit TEXT NOT NULL,
        wer_art TEXT NOT NULL,
        wer TEXT NOT NULL);
    CREATE INDEX nachricht_anfrage ON nachricht (anfrage_id, id);
    CREATE TABLE gelesen (
        anfrage_id INTEGER NOT NULL REFERENCES anfrage(id) ON DELETE CASCADE,
        leser TEXT NOT NULL,
        bis INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (anfrage_id, leser));
    INSERT INTO nachricht (anfrage_id, art, text, zeit, wer_art, wer)
        SELECT id, 'nachricht', antwort, geaendert, 'lehrkraft', COALESCE(geaendert_von, '') FROM anfrage WHERE antwort != '';
    INSERT INTO anfrage (projekt_id, art, titel, status, erstellt, geaendert, stand, bestellliste_id)
        SELECT projekt_id, 'bestellung', 'Bestellliste vom ' || substr(eingereicht, 9, 2) || '.' || substr(eingereicht, 6, 2) || '.',
        'neu', eingereicht, eingereicht, CASE WHEN geprueft IS NULL THEN 'offen' ELSE 'bearbeitung' END, id
        FROM bestellliste WHERE eingereicht IS NOT NULL
    """),
]


def migrieren(con):
    """Bringt das Schema auf den neuesten Stand (PRAGMA user_version = Anzahl angewandter Migrationen).
    Migrationen mit OHNE_FK bauen eine Tabelle neu auf: dafuer ist die Fremdschluessel-Pruefung kurz aus (das geht nur
    ausserhalb einer Transaktion), danach muss PRAGMA foreign_key_check leer sein, sonst wird alles zurueckgerollt."""
    stand = con.execute("PRAGMA user_version").fetchone()[0]
    for nummer in range(stand, len(MIGRATIONEN)):
        eintrag = MIGRATIONEN[nummer]
        ohne_fk = isinstance(eintrag, tuple)
        sql = eintrag[1] if ohne_fk else eintrag
        if ohne_fk:
            con.execute("PRAGMA foreign_keys = OFF")
        con.execute("BEGIN IMMEDIATE")
        try:
            for befehl in sql.split(";"):
                if befehl.strip():
                    con.execute(befehl)
            if ohne_fk and con.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Migration %d: Fremdschluessel verletzt" % (nummer + 1))
            con.execute("PRAGMA user_version = %d" % (nummer + 1))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            if ohne_fk:
                con.execute("PRAGMA foreign_keys = ON")
    _vorlagen_einlesen(con)


def oeffnen(daten_dir):
    """Datenbank im Datenordner oeffnen und migrieren."""
    os.makedirs(daten_dir, exist_ok=True)
    con = verbinden(os.path.join(daten_dir, "trackingdrs.sqlite"))
    con.execute("PRAGMA journal_mode = WAL")
    migrieren(con)
    return con


def ereignis(con, projekt_id, wer_art, wer, art, **daten):
    """Haengt ein Ereignis an. wer_art: lehrkraft | team | system, wer: Kuerzel bzw. 'Team'."""
    con.execute("INSERT INTO ereignis (zeit, projekt_id, wer_art, wer, art, daten) VALUES (?, ?, ?, ?, ?, ?)",
                (jetzt(), projekt_id, wer_art, wer, art, json.dumps(daten, ensure_ascii=False)))


def einstellung(con, schluessel, vorgabe=None):
    zeile = con.execute("SELECT wert FROM einstellung WHERE schluessel = ?", (schluessel,)).fetchone()
    return zeile[0] if zeile else vorgabe


def einstellung_setzen(con, schluessel, wert):
    con.execute("INSERT INTO einstellung (schluessel, wert) VALUES (?, ?) "
                "ON CONFLICT (schluessel) DO UPDATE SET wert = excluded.wert", (schluessel, wert))
