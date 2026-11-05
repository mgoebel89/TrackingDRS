"""Export: Tracking-Sheet als Excel-Datei (.xlsx, ohne Zusatzpakete geschrieben) im Layout des Sheets, und die Daten
fuer den Projektbericht (Druckansicht im Browser, als PDF speichern).

Excel: Blatt "Tracking-Sheet" mit KW-Spalten wie im Original (b = geplant, e = Endtermin, g/y/r = Ampel, farbig),
Gesamtstatus und Meilensteinen; Blaetter "Probleme" und "Verlauf".
"""
import datetime
import io
import json
import re
import zipfile
from xml.sax.saxutils import escape

from . import anfragen, besprechung, bestellung, extras, projekte, sheet, tafel

# Stile (Index in cellXfs von styles.xml)
NORMAL, FETT, PLAN, GRUEN, GELB, ROT, PHASE, KOPF, MEILENSTEIN, FREI, TITEL, UMBRUCH = range(12)
STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="5"><font><sz val="10"/><name val="Calibri"/></font><font><b/><sz val="10"/><name val="Calibri"/></font>
<font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font><font><b/><sz val="12"/><color rgb="FF00639C"/><name val="Calibri"/></font>
<font><b/><sz val="14"/><color rgb="FF00639C"/><name val="Calibri"/></font></fonts>
<fills count="9"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF9DCDEA"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF9FB400"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFF8B442"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFD4005E"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFE8EBEF"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF00639C"/></patternFill></fill>
<fill><patternFill patternType="lightUp"><fgColor rgb="FFC8CDD5"/></patternFill></fill></fills>
<borders count="2"><border/><border><left style="thin"><color rgb="FFD5DAE1"/></left><right style="thin"><color rgb="FFD5DAE1"/></right>
<top style="thin"><color rgb="FFD5DAE1"/></top><bottom style="thin"><color rgb="FFD5DAE1"/></bottom></border></borders>
<cellStyleXfs count="1"><xf/></cellStyleXfs>
<cellXfs count="12">
<xf fontId="0" fillId="0" borderId="0"/>
<xf fontId="1" fillId="0" borderId="0" applyFont="1"/>
<xf fontId="1" fillId="2" borderId="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center"/></xf>
<xf fontId="1" fillId="3" borderId="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center"/></xf>
<xf fontId="1" fillId="4" borderId="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center"/></xf>
<xf fontId="2" fillId="5" borderId="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center"/></xf>
<xf fontId="1" fillId="6" borderId="1" applyFont="1" applyFill="1" applyBorder="1"/>
<xf fontId="2" fillId="7" borderId="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center"/></xf>
<xf fontId="3" fillId="0" borderId="1" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center"/></xf>
<xf fontId="0" fillId="8" borderId="1" applyFill="1" applyBorder="1"/>
<xf fontId="4" fillId="0" borderId="0" applyFont="1"/>
<xf fontId="0" fillId="0" borderId="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
</cellXfs></styleSheet>"""
STEUERZEICHEN = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _spalte(n):
    """0 -> A, 25 -> Z, 26 -> AA"""
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _zelle(ref, wert, stil):
    if wert is None or wert == "":
        return '<c r="%s" s="%d"/>' % (ref, stil) if stil else ""
    if isinstance(wert, (int, float)) and not isinstance(wert, bool):
        return '<c r="%s" s="%d"><v>%s</v></c>' % (ref, stil, wert)
    text = escape(STEUERZEICHEN.sub("", str(wert)))
    return '<c r="%s" s="%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, stil, text)


def _blatt(zeilen, breiten, fixiert=None):
    """zeilen: Liste von Zeilen, jede Zelle None, Wert oder (Wert, Stil)."""
    teile = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
    if fixiert:
        spalten, reihen = fixiert
        teile.append('<sheetViews><sheetView workbookViewId="0"><pane xSplit="%d" ySplit="%d" topLeftCell="%s%d" activePane="bottomRight" '
                     'state="frozen"/></sheetView></sheetViews>' % (spalten, reihen, _spalte(spalten), reihen + 1))
    teile.append("<cols>" + "".join('<col min="%d" max="%d" width="%s" customWidth="1"/>' % (i + 1, i + 1, b) for i, b in enumerate(breiten)) + "</cols>")
    teile.append("<sheetData>")
    for r, zeile in enumerate(zeilen, start=1):
        zellen = []
        for c, zelle in enumerate(zeile):
            wert, stil = zelle if isinstance(zelle, tuple) else (zelle, NORMAL)
            zellen.append(_zelle("%s%d" % (_spalte(c), r), wert, stil))
        teile.append('<row r="%d">%s</row>' % (r, "".join(zellen)))
    teile.append("</sheetData></worksheet>")
    return "".join(teile)


def xlsx(blaetter):
    """blaetter: Liste (Name, Blatt-XML). Rueckgabe: Bytes einer .xlsx-Datei."""
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.'
                             'spreadsheetml.worksheet+xml"/>' % (i + 1) for i in range(len(blaetter))) + "</Types>")
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                   'officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/'
                   'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(re.sub(r"[\[\]:*?/\\]", "", n)[:31]), i + 1, i + 1)
                             for i, (n, _x) in enumerate(blaetter)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.'
                   'openxmlformats.org/package/2006/relationships">'
                   + "".join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                             'Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1) for i in range(len(blaetter)))
                   + '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
                     'Target="styles.xml"/></Relationships>' % (len(blaetter) + 1))
        z.writestr("xl/styles.xml", STYLES)
        for i, (_n, xml) in enumerate(blaetter):
            z.writestr("xl/worksheets/sheet%d.xml" % (i + 1), xml)
    return puffer.getvalue()


def _kw(woche):
    return datetime.date.fromisoformat(woche).isocalendar()[1]


def sheet_xlsx(con, pid):
    """Das Tracking-Sheet eines Projekts als Excel-Datei."""
    d = sheet.lesen(con, pid)
    p = d["projekt"]
    W = d["wochen"]
    frei = set(W) - set(d["projektwochen"]) if d["projektwochen"] is not None else set()
    kuerzel = {m["id"]: m["kuerzel"] for m in d["mitglieder"]}
    farbe = {"g": GRUEN, "y": GELB, "r": ROT}
    team = ", ".join("%s %s (%s)" % (m["vorname"], m["nachname"], m["kuerzel"]) for m in d["mitglieder"] if m["aktiv"])
    z = [[("Tracking-Sheet · " + p["titel"], TITEL)],
         ["Klasse %s · %s bis %s · Team: %s · Stand %s" % (p["klasse"], "KW %d/%s" % (_kw(W[0]), W[0][:4]), "KW %d/%s" % (_kw(W[-1]), W[-1][:4]),
                                                         team or "–", datetime.datetime.now().strftime("%d.%m.%Y %H:%M"))],
         [],
         [("Nr", KOPF), ("Tätigkeit", KOPF), ("Verantw.", KOPF), ("Erledigt", KOPF)] + [(_kw(w), KOPF) for w in W]]
    nr = 0
    gesamt = {}
    for ph in d["phasen"]:
        z.append([("", PHASE), (ph["name"].upper(), PHASE), ("", PHASE), ("", PHASE)] + [("", PHASE) for _w in W])
        for a in ph["aufgaben"]:
            nr += 1
            zeile = [nr, a["titel"] + (" (verworfen)" if a["verworfen"] else ""), kuerzel.get(a["verantwortlich_id"], ""),
                     a["erledigt"][8:10] + "." + a["erledigt"][5:7] + "." if a["erledigt"] else ""]
            for w in W:
                ampel = a["ampel"].get(w)
                if ampel and not a["verworfen"]:
                    gesamt[w] = max(gesamt.get(w, ampel), ampel, key="gyr".index)
                wert = "e" if a["ende"] == w else ampel or ("b" if w in a["plan"] else "")
                stil = farbe[ampel] if ampel else PLAN if w in a["plan"] or a["ende"] == w else FREI if w in frei else NORMAL
                zeile.append((wert, stil))
            z.append(zeile)
    z.append([("", PHASE), ("Meilensteine", PHASE), ("", PHASE), ("", PHASE)] +
             [("◆" if any(m["woche"] == w and not m["verworfen"] for m in d["meilensteine"]) else "", MEILENSTEIN) for w in W])
    z.append([("", PHASE), ("Gesamtstatus", PHASE), ("", PHASE), ("", PHASE)] +
             [(gesamt.get(w, ""), farbe[gesamt[w]] if w in gesamt else NORMAL) for w in W])
    z.append([])
    z.append([("Legende:", FETT), "b = geplante Woche, e = Endtermin, g/y/r = Ampel (grün, gelb, rot), ◆ = Meilenstein, schraffiert = kein Projekttag"])
    ms = [m for m in d["meilensteine"] if not m["verworfen"]]
    if ms:
        z.append([])
        z.append([("Meilensteine", FETT)])
        for m in ms:
            z.append(["", "KW %d: %s" % (_kw(m["woche"]), m["titel"])])
    tracking = _blatt(z, [5, 42, 9, 9] + [4.2] * len(W), fixiert=(4, 4))

    titel = {a["id"]: a["titel"] for ph in d["phasen"] for a in ph["aufgaben"]}
    probleme = [[("KW", KOPF), ("Tätigkeit", KOPF), ("Ampel", KOPF), ("Problem", KOPF), ("Korrekturmaßnahme", KOPF), ("Verantw.", KOPF),
                 ("Eingetragen", KOPF)]]
    for pr in con.execute("SELECT pr.* FROM problem pr JOIN aufgabe a ON a.id = pr.aufgabe_id WHERE a.projekt_id = ? ORDER BY pr.woche, pr.id", (pid,)):
        probleme.append([_kw(pr["woche"]), (titel.get(pr["aufgabe_id"], ""), UMBRUCH), (pr["ampel"], farbe[pr["ampel"]]), (pr["problem"], UMBRUCH),
                         (pr["massnahme"], UMBRUCH), kuerzel.get(pr["verantwortlich_id"], ""), pr["zeit"].replace("T", " ")[:16]])
    verlauf = [[("Zeit", KOPF), ("Wer", KOPF), ("Was", KOPF), ("Einzelheiten", KOPF)]]
    for e in con.execute("SELECT * FROM ereignis WHERE projekt_id = ? ORDER BY id", (pid,)):
        verlauf.append([e["zeit"].replace("T", " ")[:16], "Team" if e["wer_art"] == "team" else e["wer"].upper(), e["art"],
                        (", ".join("%s: %s" % (k, v) for k, v in json.loads(e["daten"]).items() if not k.endswith("_id")), UMBRUCH)])
    return xlsx([("Tracking-Sheet", tracking), ("Probleme", _blatt(probleme, [6, 30, 7, 45, 45, 9, 17], fixiert=(0, 1))),
                 ("Verlauf", _blatt(verlauf, [17, 8, 22, 90], fixiert=(0, 1)))])


def dateiname(titel, endung):
    sauber = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß_-]+", "-", titel).strip("-") or "projekt"
    return "%s-%s.%s" % (sauber, datetime.date.today().isoformat(), endung)


def bericht(con, pid, mit_notizen=False):
    """Alles fuer den Projektbericht (Druckansicht): Projekt, Sheet, Probleme, Besprechungen mit Tafeln, Anfragen,
    Bestelllisten, Fotos, Verlauf; Lehrernotizen nur auf Wunsch."""
    d = projekte.details(con, pid, ereignisse=100000)
    protokolle = besprechung._protokolle(con, pid, lehrkraft=mit_notizen)
    for p in protokolle:
        p["tafel_daten"] = tafel.eingefroren(con, pid, p["id"]) if p.get("tafel") else None
        p.pop("zusammenfassung", None)
    titel = {a["id"]: a["titel"] for a in con.execute("SELECT id, titel FROM aufgabe WHERE projekt_id = ?", (pid,))}
    kuerzel = {m["id"]: m["kuerzel"] for m in con.execute("SELECT id, kuerzel FROM mitglied WHERE projekt_id = ?", (pid,))}
    return {
        "projekt": d, "sheet": sheet.lesen(con, pid), "protokolle": protokolle,
        "probleme": [{"woche": pr["woche"], "aufgabe": titel.get(pr["aufgabe_id"]), "ampel": pr["ampel"], "problem": pr["problem"],
                      "massnahme": pr["massnahme"], "verantwortlich": kuerzel.get(pr["verantwortlich_id"]), "zeit": pr["zeit"]}
                     for pr in con.execute("SELECT pr.* FROM problem pr JOIN aufgabe a ON a.id = pr.aufgabe_id WHERE a.projekt_id = ? "
                                           "ORDER BY pr.woche, pr.id", (pid,))],
        "anfragen": anfragen.liste(con, pid), "bestellung": bestellung.team_sicht(con, pid)["eingereicht"],
        "fotos": extras.fotos(con, pid), "mindmap": extras.mindmap(con, pid),
        "notizen": extras.notizen(con, pid) if mit_notizen else None,
    }
