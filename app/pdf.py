"""PDF einer abgeschlossenen Besprechung (Stufe I7), ohne Zusatzpakete: A4 quer, Seite 1 die Tafel als Bild (JPEG, im
Browser beim Abschliessen gemalt), danach das Ergebnis als Text (Absprachen, Auftraege, Meilensteine, Geklaertes, Stand
des Teams, Kurzzusammenfassung), Skizzen aus Rahmen als Bild beim Eintrag. Lehrernotizen kommen nie hinein.

Schrift: Helvetica aus den PDF-Grundschriften (WinAnsi), damit braucht die Datei keine eingebettete Schrift. Zeichen,
die es dort nicht gibt, werden ersetzt.
"""
import datetime
import json
import os
import struct

from . import db
from .projekte import ProjektFehler

BREITE, HOEHE = 842, 595   # A4 quer in Punkt
RAND = 36
ERSATZ = {"✓": "OK", "✕": "x", "◆": "*", "→": "->", "↺": "", "…": "...", " ": " ", " ": " "}


def _text(s):
    s = str(s or "")
    for a, b in ERSATZ.items():
        s = s.replace(a, b)
    roh = s.encode("cp1252", errors="replace")
    return roh.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _jpeg_masse(daten):
    """Breite, Hoehe und Farbkanaele aus dem SOF-Marker eines JPEG."""
    i = 2
    while i + 9 < len(daten):
        if daten[i] != 0xFF:
            i += 1
            continue
        marke = daten[i + 1]
        if marke in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", daten[i + 5:i + 9])
            return w, h, daten[i + 9]
        if marke in (0xD8, 0x01) or 0xD0 <= marke <= 0xD7:
            i += 2
            continue
        i += 2 + struct.unpack(">H", daten[i + 2:i + 4])[0]
    raise ValueError("kein JPEG")


class Dokument:
    def __init__(self):
        self.seiten = []      # je Seite: [inhalt (bytes), [bildnamen]]
        self.bilder = []      # (name, breite, hoehe, kanaele, daten)
        self.neue_seite()

    def neue_seite(self):
        self.seiten.append([bytearray(), []])
        self.y = HOEHE - RAND

    def _schreiben(self, text):
        self.seiten[-1][0] += text.encode("latin-1") if isinstance(text, str) else text

    def zeile(self, text, groesse=10, fett=False, x=RAND, farbe=(0.11, 0.14, 0.2)):
        self._schreiben("%.3f %.3f %.3f rg BT /%s %d Tf %.1f %.1f Td (" % (farbe + ("F2" if fett else "F1", groesse, x, self.y)))
        self._schreiben(_text(text))
        self._schreiben(") Tj ET\n")

    def absatz(self, text, groesse=10, fett=False, einzug=0, abstand=1.35, breite=None):
        """Umbrechen nach Zeichenzahl (Helvetica: im Mittel etwa eine halbe Schriftgroesse je Zeichen)."""
        breite = breite or (BREITE - 2 * RAND - einzug)
        je_zeile = max(20, int(breite / (groesse * 0.5)))
        for roh in str(text or "").split("\n"):
            woerter, z = roh.split(" "), ""
            zeilen = []
            for w in woerter:
                if len(z) + len(w) + 1 > je_zeile and z:
                    zeilen.append(z)
                    z = w
                else:
                    z = (z + " " + w) if z else w
            zeilen.append(z)
            for z in zeilen:
                self.platz(groesse * abstand)
                self.zeile(z, groesse, fett, RAND + einzug)
                self.y -= groesse * abstand

    def platz(self, hoehe):
        if self.y - hoehe < RAND:
            self.neue_seite()

    def bild(self, daten, w_max, h_max, x=RAND):
        """JPEG einsetzen (proportional, oben links an der aktuellen Zeile). Gibt die Hoehe zurueck."""
        w, h, kanaele = _jpeg_masse(daten)
        f = min(w_max / w, h_max / h)
        bw, bh = w * f, h * f
        self.platz(bh + 4)
        name = "B%d" % (len(self.bilder) + 1)
        self.bilder.append((name, w, h, kanaele, daten))
        self.seiten[-1][1].append(name)
        self._schreiben("q %.1f 0 0 %.1f %.1f %.1f cm /%s Do Q\n" % (bw, bh, x, self.y - bh, name))
        self.y -= bh + 8
        return bh

    def linie(self):
        self._schreiben("0.8 0.83 0.86 RG 0.6 w %d %.1f m %d %.1f l S\n" % (RAND, self.y + 4, BREITE - RAND, self.y + 4))

    def bytes(self):
        objekte = []   # Inhalt je Objektnummer (1-basiert)

        def neu(inhalt):
            objekte.append(inhalt)
            return len(objekte)

        katalog = neu(None)
        seitenbaum = neu(None)
        f1 = neu(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        f2 = neu(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        bildnr = {}
        for name, w, h, kanaele, daten in self.bilder:
            kopf = ("<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /%s /BitsPerComponent 8 "
                    "/Filter /DCTDecode /Length %d >>\nstream\n" % (w, h, "DeviceGray" if kanaele == 1 else "DeviceRGB", len(daten)))
            bildnr[name] = neu(kopf.encode("latin-1") + daten + b"\nendstream")
        seiten = []
        for inhalt, namen in self.seiten:
            strom = neu(b"<< /Length %d >>\nstream\n" % len(inhalt) + bytes(inhalt) + b"\nendstream")
            xo = " ".join("/%s %d 0 R" % (n, bildnr[n]) for n in namen)
            seiten.append(neu(("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R /Resources << /Font << /F1 %d 0 R "
                               "/F2 %d 0 R >> /XObject << %s >> >> >>" % (seitenbaum, BREITE, HOEHE, strom, f1, f2, xo)).encode("latin-1")))
        objekte[katalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % seitenbaum
        objekte[seitenbaum - 1] = ("<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % s for s in seiten), len(seiten))).encode("latin-1")
        aus = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        lagen = []
        for i, inhalt in enumerate(objekte, 1):
            lagen.append(len(aus))
            aus += b"%d 0 obj\n" % i + inhalt + b"\nendobj\n"
        xref = len(aus)
        aus += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objekte) + 1)
        for lage in lagen:
            aus += b"%010d 00000 n \n" % lage
        aus += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objekte) + 1, katalog, xref)
        return bytes(aus)


def _datum(text):
    return datetime.date.fromisoformat(text[:10]).strftime("%d.%m.%Y") if text else ""


def _kw(woche):
    return "KW %d" % datetime.date.fromisoformat(woche).isocalendar()[1]


def _jpeg(daten_dir, name):
    if not name or not (isinstance(name, str) and len(name) == 24):
        return None
    pfad = os.path.join(daten_dir, "bilder", name + ".jpg")
    if not os.path.exists(pfad):
        return None
    with open(pfad, "rb") as f:
        return f.read()


def _besprechung(con, pid, bid):
    z = con.execute("SELECT * FROM besprechung WHERE id = ? AND projekt_id = ? AND abgeschlossen IS NOT NULL", (bid, pid)).fetchone()
    if z is None:
        raise ProjektFehler("Diese Besprechung gibt es nicht.")
    return z


def tafelbild_setzen(con, pid, bid, name):
    """Bild der eingefrorenen Tafel nachtragen (fuer Besprechungen von vor 0.10.6), nur wenn es noch keins gibt."""
    with db.transaktion(con):
        z = _besprechung(con, pid, bid)
        p = json.loads(z["protokoll"] or "{}")
        if not p.get("tafel_bild"):
            p["tafel_bild"] = name
            con.execute("UPDATE besprechung SET protokoll = ? WHERE id = ?", (json.dumps(p, ensure_ascii=False), z["id"]))
        return p.get("tafel_bild")


def dateiname(con, pid, bid):
    z = _besprechung(con, pid, bid)
    p = con.execute("SELECT titel FROM projekt WHERE id = ?", (pid,)).fetchone()
    return "Besprechung %s - %s.pdf" % (_kw(z["woche"]), p["titel"])


def besprechung_pdf(con, daten_dir, pid, bid):
    z = _besprechung(con, pid, bid)
    p = json.loads(z["protokoll"] or "{}")
    proj = con.execute("SELECT titel, klasse FROM projekt WHERE id = ?", (pid,)).fetchone()
    d = Dokument()
    termin = p.get("termin")
    kopf = "Besprechung %s · %s (%s)" % (_kw(z["woche"]), proj["titel"], proj["klasse"])
    unter = ((_datum(termin["datum"]) + ", " + termin["uhrzeit"] + " Uhr · ") if termin else "") + \
        "abgeschlossen %s %s" % (_datum(z["abgeschlossen"]), z["abgeschlossen"][11:16])
    d.zeile(kopf, 16, True)
    d.y -= 18
    d.zeile(unter, 9, farbe=(0.36, 0.4, 0.47))
    d.y -= 14
    bild = _jpeg(daten_dir, p.get("tafel_bild"))
    if bild:
        d.bild(bild, BREITE - 2 * RAND, HOEHE - 2 * RAND - 40)
    else:
        d.absatz("(Für diese Besprechung gibt es noch kein Bild der Tafel.)", 10)
    # Seite 2: das Ergebnis
    d.neue_seite()
    d.zeile("Ergebnis · " + kopf, 14, True)
    d.y -= 22
    ergebnis = p.get("ergebnis") or []

    def teil(titel, eintraege, zeile):
        if not eintraege:
            return
        d.platz(40)
        d.zeile(titel, 11, True, farbe=(0, 0.39, 0.61))
        d.y -= 15
        for e in eintraege:
            d.absatz(zeile(e), 10, einzug=10)
            skizze = _jpeg(daten_dir, e.get("bild"))
            if skizze:
                d.bild(skizze, 260, 170, RAND + 10)
        d.y -= 6

    teil("Absprachen", [e for e in ergebnis if e["art"] == "absprache"], lambda e: "- " + e["text"])
    teil("Aufträge", [e for e in ergebnis if e["art"] == "auftrag"],
         lambda e: "- " + e["text"] + (" · bis " + _datum(e["frist"]) if e.get("frist") else "") +
         (" · " + e["verantwortlich"] if e.get("verantwortlich") else ""))
    teil("Meilensteine", [e for e in ergebnis if e["art"] == "meilenstein"],
         lambda e: "- " + e["text"] + (" · " + _kw(e["frist"]) if e.get("frist") else ""))
    teil("Geklärt", p.get("geklaert") or [], lambda e: "- " + e["text"])
    if not ergebnis and not p.get("geklaert"):
        d.absatz("In dieser Besprechung wurde kein Ergebnis festgehalten.", 10)
    if p.get("vorbereitung"):
        d.platz(40)
        d.zeile("Stand des Teams", 11, True, farbe=(0, 0.39, 0.61))
        d.y -= 15
        d.absatz(p["vorbereitung"], 10, einzug=10)
        d.y -= 6
    zus = p.get("zusammenfassung")
    if zus:
        d.platz(40)
        d.linie()
        d.y -= 10
        d.zeile("Kurzzusammenfassung (seit der letzten Besprechung)", 11, True, farbe=(0, 0.39, 0.61))
        d.y -= 15
        ampel = zus.get("ampel")
        if ampel and ampel.get("ampel"):
            d.absatz("Gesamtstatus %s: %s" % (_kw(ampel["woche"]), {"g": "grün", "y": "gelb", "r": "rot"}.get(ampel["ampel"], ampel["ampel"])), 10, einzug=10)
        for a in zus.get("aenderungen") or []:
            d.absatz("- " + a.get("text", ""), 9, einzug=10)
        for pr in zus.get("probleme") or []:
            d.absatz("- Problem (%s): %s%s" % (pr.get("aufgabe", ""), pr.get("problem", ""),
                                               " -> " + pr["massnahme"] if pr.get("massnahme") else ""), 9, einzug=10)
        for a in zus.get("auftraege") or []:
            d.absatz("- Auftrag: %s%s" % (a["text"], " (erledigt)" if a.get("erledigt") else " (offen)"), 9, einzug=10)
    return d.bytes()
