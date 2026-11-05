// Gemeinsame Hilfen fuer alle Seiten: Schnittstelle, DOM-Bau ohne innerHTML, Meldungen, Dialoge, Kalenderwochen.
'use strict';

// Schul-Logo im Kopf: ohne hinterlegtes Logo (404) verschwindet das Bild
document.querySelectorAll('img.logo').forEach(img => {
  const weg = () => img.remove();
  if (img.complete && img.naturalWidth === 0) weg(); else img.addEventListener('error', weg);
});

const T = {
  NAME: 'Projektarbeit MT',   // Name der Seite (Titel, Kopfzeile); intern heisst das System TrackingDRS

  async api(methode, url, daten) {
    const kopf = { 'X-TrackingDRS': '1' };
    if (daten !== undefined) kopf['Content-Type'] = 'application/json';
    let antwort;
    try {
      antwort = await fetch(url, { method: methode, headers: kopf, credentials: 'same-origin',
        body: daten !== undefined ? JSON.stringify(daten) : undefined });
    } catch (e) {
      throw new Error('Keine Verbindung zum Server.');
    }
    let inhalt = {};
    try { inhalt = await antwort.json(); } catch (e) { /* leer */ }
    if (!antwort.ok) {
      const f = new Error(inhalt.fehler || 'Fehler ' + antwort.status);
      f.status = antwort.status;
      throw f;
    }
    return inhalt;
  },

  // el('div', {class: 'karte', onclick: fn}, 'Text', kindElement, [weitere])
  el(tag, attribute, ...kinder) {
    const e = document.createElement(tag);
    for (const [name, wert] of Object.entries(attribute || {})) {
      if (wert === null || wert === undefined || wert === false) continue;
      if (name.startsWith('on')) e.addEventListener(name.slice(2), wert);
      else if (name === 'class') e.className = wert;
      else if (name === 'text') e.textContent = wert;
      else if (name === 'value') e.value = wert;
      else if (name === 'checked') e.checked = true;
      else e.setAttribute(name, wert === true ? '' : wert);
    }
    const anhaengen = k => {
      if (k === null || k === undefined || k === false) return;
      if (Array.isArray(k)) k.forEach(anhaengen);
      else e.appendChild(typeof k === 'string' || typeof k === 'number' ? document.createTextNode(String(k)) : k);
    };
    kinder.forEach(anhaengen);
    return e;
  },

  leeren(e) { while (e.firstChild) e.removeChild(e.firstChild); return e; },

  // Inhalt ersetzen; null/false werden uebersprungen (Element.append wuerde "null" als Text einfuegen)
  setzen(e, ...kinder) {
    T.leeren(e);
    kinder.flat(Infinity).forEach(k => { if (k !== null && k !== undefined && k !== false) e.append(k); });
    return e;
  },

  // Kurze Einblendung unten rechts; mit ziel (Adresse) ein Link, der laenger stehen bleibt (Neues bei Anfragen)
  meldung(text, fehler, ziel) {
    let ort = document.getElementById('meldungen');
    if (!ort) { ort = T.el('div', { id: 'meldungen', 'aria-live': 'polite' }); document.body.appendChild(ort); }
    const m = ziel ? T.el('a', { class: 'meldung hinweis', href: ziel, onclick: () => m.remove() }, text)
      : T.el('div', { class: 'meldung' + (fehler ? ' fehler' : ''), text });
    ort.appendChild(m);
    setTimeout(() => m.remove(), ziel ? 12000 : fehler ? 7000 : 3500);
  },

  // Seitentitel mit der Zahl des Ungelesenen davor ("(2) Cockpit · Projektarbeit MT"), damit es im Browser-Tab auffaellt
  titel(text) { T.titelText = text; T.titelZeigen(); },
  titelZahl(n) { T.titelN = n; T.titelZeigen(); },
  titelZeigen() { document.title = (T.titelN ? '(' + T.titelN + ') ' : '') + (T.titelText ? T.titelText + ' · ' + T.NAME : T.NAME); },

  // Neues beobachten: laden() liefert {neu: [{id, nid, ...}]}; was seit dem letzten Abruf dazugekommen ist, geht an
  // melden(v). Der erste Abruf merkt sich nur den Stand, sonst poppt nach dem Oeffnen der Seite alles auf einmal auf.
  // Rueckgabe: Funktion fuer einen Abruf sofort (z. B. nachdem etwas gelesen wurde).
  beobachten(laden, melden, alle = 60000) {
    let gesehen = null;
    const schluessel = v => v.id + ':' + v.nid;
    async function abfragen() {
      let z;
      try { z = await laden(); } catch (e) { return; }
      const liste = z.neu || [];
      if (gesehen) liste.filter(v => !gesehen.has(schluessel(v))).forEach(melden);
      else gesehen = new Set();
      liste.forEach(v => gesehen.add(schluessel(v)));
    }
    abfragen();
    setInterval(abfragen, alle);
    return abfragen;
  },

  // Strichsymbole (24er Raster) fuer die Team-Reiter
  SYMBOLE: {
    start: 'M3 11.5 12 4l9 7.5M5.5 9.5V20h4.5v-6h4v6h4.5V9.5',
    sheet: 'M3.5 4.5h17v15h-17zM3.5 9.5h17M3.5 14.5h17M9 4.5v15',
    bespr: 'M4 5h16v10.5H10L5.5 19.5v-4H4zM8 9.5h8M8 12.5h5',
    anfr: 'M3.5 6h17v12h-17zM3.5 7l8.5 6.5L20.5 7',
    fotos: 'M3.5 8h4l1.8-2.5h5.4L16.5 8h4v11h-17zM12 10.5a3.25 3.25 0 1 0 0 6.5a3.25 3.25 0 1 0 0-6.5',
    projekt: 'M3.5 6h6l2 2.5h9v10.5h-17z',
  },
  // Reiterleiste (Team-Ansicht und Projektseite der Lehrkraft): klebt unter der Kopfzeile, am Handy feste Leiste unten.
  // eintraege: [{schluessel, ziel, lang, kurz, symbol, zahl}], zahl = Platz fuer einen roten Zaehler
  reiterleiste(eintraege) {
    document.body.classList.add('mit-unterleiste');
    return T.el('nav', { class: 'reiterleiste', 'aria-label': 'Bereiche' }, eintraege.map(r =>
      T.el('a', { href: r.ziel, 'data-reiter': r.schluessel, title: r.lang }, T.symbol(r.symbol), T.el('span', { class: 'lang', text: r.lang }),
        T.el('span', { class: 'kurz', text: r.kurz }), r.zahl ? T.el('span', { class: 'reiter-zahl', hidden: true }) : null)));
  },
  reiterAktiv(leiste, schluessel) {
    leiste.querySelectorAll('a').forEach(a => {
      a.classList.toggle('an', a.dataset.reiter === schluessel);
      if (a.dataset.reiter === schluessel) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
  },
  reiterZahl(leiste, n, titel) {
    const b = leiste && leiste.querySelector('.reiter-zahl');
    if (!b) return;
    b.textContent = String(n);
    b.hidden = !n;
    b.title = titel || '';
  },
  // Hoehe von Kopfzeile und Reiterleiste, damit Klebendes (Reiter, Seitenleiste im Sheet) darunter bleibt
  hoehenMerken() {
    const kopf = document.querySelector('header.kopf'), leiste = document.querySelector('.reiterleiste');
    const wurzel = document.documentElement.style;
    if (kopf) wurzel.setProperty('--kopf-h', kopf.offsetHeight + 'px');
    if (leiste) wurzel.setProperty('--reiter-h', leiste.offsetHeight + 'px');
  },

  symbol(name) {
    const ns = 'http://www.w3.org/2000/svg';
    const s = document.createElementNS(ns, 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('aria-hidden', 'true');
    s.setAttribute('class', 'symbol');
    const p = document.createElementNS(ns, 'path');
    p.setAttribute('d', T.SYMBOLE[name]);
    s.appendChild(p);
    return s;
  },

  // Dialog mit Formular. felder: Element(e) im Formular. Rueckgabe: Promise, das mit dem Ergebnis von speichern()
  // aufgeloest wird (oder null bei Abbrechen). speichern(form) darf einen Fehler werfen: er erscheint im Dialog.
  dialog({ titel, inhalt, knopf = 'Speichern', abbrechen = 'Abbrechen', speichern, gefaehrlich = false, fest = false }) {
    return new Promise(fertig => {
      const fehler = T.el('div', { class: 'fehlertext', role: 'alert' });
      const ok = T.el('button', { type: 'submit', class: gefaehrlich ? 'warnen' : 'haupt', text: knopf });
      const form = T.el('form', { method: 'dialog' },
        T.el('h2', { class: 'dreieck', text: titel }), inhalt, fehler,
        T.el('div', { class: 'knoepfe' },
          abbrechen && !fest ? T.el('button', { type: 'button', value: 'nein', text: abbrechen, onclick: () => schliessen(null) }) : null, ok));
      const d = T.el('dialog', {}, form);
      const schliessen = wert => { d.close(); d.remove(); fertig(wert); };
      d.addEventListener('cancel', ev => { ev.preventDefault(); if (!fest) schliessen(null); });
      form.addEventListener('submit', async ev => {
        ev.preventDefault();
        fehler.textContent = '';
        ok.disabled = true;
        try { schliessen(speichern ? await speichern(form) : true); }
        catch (e) { fehler.textContent = e.message; ok.disabled = false; }
      });
      document.body.appendChild(d);
      d.showModal();
      const erstes = form.querySelector('input:not([type=hidden]):not([readonly]), select, textarea');
      if (erstes) erstes.focus();
    });
  },

  feld(beschriftung, eingabe, hilfe) {
    return T.el('label', { class: 'feld' }, beschriftung, eingabe, hilfe ? T.el('span', { class: 'hilfe', text: hilfe }) : null);
  },

  // ISO-Kalenderwoche
  kw(datum) {
    const d = new Date(Date.UTC(datum.getFullYear(), datum.getMonth(), datum.getDate()));
    const tag = d.getUTCDay() || 7;
    d.setUTCDate(d.getUTCDate() + 4 - tag);
    const jahresanfang = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    return Math.ceil(((d - jahresanfang) / 86400000 + 1) / 7);
  },
  datum(text) { return new Date(text.slice(0, 10) + 'T12:00:00'); },
  kwText(text) { return 'KW ' + T.kw(T.datum(text)); },
  zeitraum(start, ende) {
    const s = T.datum(start), e = T.datum(ende);
    return 'KW ' + T.kw(s) + '/' + s.getFullYear() + ' bis KW ' + T.kw(e) + '/' + e.getFullYear();
  },
  tagText(text) {
    const d = T.datum(text);
    return d.toLocaleDateString('de-DE', { weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric' });
  },
  zeitText(text) {
    if (!text) return '';
    const d = new Date(text);
    return d.toLocaleDateString('de-DE', { weekday: 'short', day: '2-digit', month: '2-digit' }) + ' ' +
      d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  },
  // '2026-11-09T18:00:00' -> 'Mo 09.11., 18:00' (ohne Umrechnung: die Zeiten sind Schulzeit)
  zeitpunkt(text) {
    if (!text) return '';
    const d = T.datum(text);
    return T.TAGE[d.getDay()] + ' ' + text.slice(8, 10) + '.' + text.slice(5, 7) + '., ' + text.slice(11, 16);
  },
  // '2026-11-03' -> 'Di 03.11.'
  kurzTag(text) {
    const d = T.datum(text);
    return T.TAGE[d.getDay()] + ' ' + text.slice(8, 10) + '.' + text.slice(5, 7) + '.';
  },
  TAGE: ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'],
  isoDatum(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  },

  // Ereignis aus dem Verlauf als Satz
  verlaufText(e) {
    const d = e.daten || {};
    const kw = w => w ? T.kwText(w) : 'keine';
    const ampel = a => ({ g: 'grün', y: 'gelb', r: 'rot' })[a] || 'leer';
    const texte = {
      projekt_angelegt: () => 'Projekt angelegt',
      projekt_geaendert: () => 'Projekt geändert: ' + Object.keys(d).map(k => ({ titel: 'Titel', klasse: 'Klasse',
        schuljahr: 'Schuljahr', beschreibung: 'Beschreibung', start: 'Start', ende: 'Ende' })[k] || k).join(', '),
      lehrkraefte_geaendert: () => 'Betreuung jetzt: ' + d.lehrkraefte.map(k => k.toUpperCase()).join(', '),
      mitglied_angelegt: () => 'Teammitglied ' + d.name + ' hinzugefügt',
      mitglied_geaendert: () => 'Teammitglied ' + d.name + (d.aktiv ? ' geändert' : ' deaktiviert'),
      link_erneuert: () => 'Team-Link erneuert, der alte gilt nicht mehr',
      archiviert: () => 'Projekt archiviert',
      reaktiviert: () => 'Projekt wieder aktiv',
      aufgabe_neu: () => 'Tätigkeit „' + d.titel + '“ angelegt (' + d.phase + ')',
      titel: () => 'umbenannt: „' + d.alt + '“ → „' + d.titel + '“',
      verantwortlich: () => '„' + d.titel + '“: verantwortlich ' + (d.alt ? d.alt + ' → ' : '') + d.kuerzel,
      verworfen: () => '„' + d.titel + '“ verworfen',
      wiederhergestellt: () => '„' + d.titel + '“ wiederhergestellt',
      reihenfolge: () => '„' + d.titel + '“ verschoben',
      plan: () => '„' + d.titel + '“: ' + d.wochen.map(w => T.kwText(w)).join(', ') + (d.wert ? ' geplant' : ' nicht mehr geplant'),
      ende: () => '„' + d.titel + '“: Endtermin ' + (d.alt ? kw(d.alt) + ' → ' : '') + kw(d.woche),
      ampel: () => '„' + d.titel + '“: ' + T.kwText(d.woche) + ' ' + ampel(d.ampel) + (d.problem ? ' – ' + d.problem : ''),
      meilenstein_neu: () => 'Meilenstein „' + d.titel + '“ in ' + kw(d.woche),
      meilenstein_geaendert: () => 'Meilenstein „' + d.titel + '“: ' + kw(d.woche_alt) + ' → ' + kw(d.woche),
      meilenstein_verworfen: () => 'Meilenstein „' + d.titel + '“ verworfen',
      meilenstein_zurueck: () => 'Meilenstein „' + d.titel + '“ wiederhergestellt',
      erledigt: () => '„' + d.titel + '“ erledigt ✓',
      nicht_erledigt: () => '„' + d.titel + '“ doch nicht erledigt',
      termin_gebucht: () => (d.alt_datum ? 'Termin umgebucht: ' + T.kurzTag(d.alt_datum) + ' ' + d.alt_uhrzeit + ' → '
        : 'Termin gebucht: ') + T.kurzTag(d.datum) + ' ' + d.uhrzeit,
      termin_storniert: () => 'Termin ' + T.kurzTag(d.datum) + ' ' + d.uhrzeit + ' abgesagt',
      termin_entfallen: () => 'Termin ' + T.kurzTag(d.datum) + ' ' + d.uhrzeit + ' entfällt: ' + d.grund,
      vorbereitung: () => 'Stand für die Besprechung ' + T.kwText(d.woche) + ' eingetragen',
      eintrag_neu: () => ({ frage: 'Frage', thema: 'Thema', idee: 'Idee', auftrag: 'Auftrag', absprache: 'Absprache' })[d.eintragsart] +
        ': „' + d.text + '“' + (d.frist ? ' bis ' + d.frist.slice(8, 10) + '.' + d.frist.slice(5, 7) + '.' : ''),
      eintrag_erledigt: () => (d.eintragsart === 'auftrag' ? 'Auftrag erledigt' : 'Geklärt') + ': „' + d.text + '“',
      eintrag_offen: () => 'Wieder offen: „' + d.text + '“',
      eintrag_verworfen: () => 'Verworfen: „' + d.text + '“',
      eintrag_umgewandelt: () => '„' + d.text + '“ an der Tafel: ' + ({ idee: 'Idee', auftrag: 'Auftrag', absprache: 'Absprache' })[d.eintragsart],
      besprechung_abgeschlossen: () => 'Besprechung ' + T.kwText(d.woche) + ' abgeschlossen (' + d.ergebnisse + ' Ergebnisse)',
      anfrage_neu: () => ({ rueckfrage: 'Rückfrage', ausleihe: 'Ausleihe', abnahme: 'Abnahme' })[d.anfrageart] + ': „' + d.titel + '“',
      anfrage_status: () => '„' + d.titel + '“: ' + ({ beantwortet: 'beantwortet', bereitgelegt: 'bereitgelegt', ausgegeben: 'ausgegeben',
        zurueck: 'zurückgegeben', abgelehnt: 'abgelehnt', freigegeben: 'freigegeben', nachbessern: 'nachbessern', zurueckgezogen: 'zurückgezogen',
        neu: 'erneut angefragt' })[d.status] + (d.antwort ? ' – ' + d.antwort : ''),
      anfrage_nachricht: () => ({ rueckfrage: 'Rückfrage', ausleihe: 'Ausleihe', abnahme: 'Abnahme', bestellung: 'Bestellliste' })[d.anfrageart] +
        ' „' + d.titel + '“: ' + d.text,
      sonderfenster: () => 'Sonderfenster für die Bestellliste bis ' + d.bis.slice(8, 10) + '.' + d.bis.slice(5, 7) + '., ' + d.bis.slice(11, 16),
      position_neu: () => 'Bestellliste: ' + d.menge + '× „' + d.artikel + '“' + (d.uebernommen ? ' (übernommen)' : ''),
      position_geaendert: () => 'Bestellliste: „' + d.artikel + '“ geändert',
      position_gestrichen: () => 'Bestellliste: „' + d.artikel + '“ gestrichen',
      position_zurueck: () => 'Bestellliste: „' + d.artikel + '“ wieder aufgenommen',
      liste_eingereicht: () => 'Bestellliste eingereicht (' + d.positionen + ' Positionen)',
      position_entschieden: () => '„' + d.artikel + '“: ' + ({ bestellen: 'wird bestellt', lager: 'aus dem SchulLager', firma: 'über die Firma',
        ersetzen: d.ersatz ? 'ersetzt durch ' + d.ersatz : 'Ersatz gesucht', ablehnen: 'abgelehnt' })[d.entscheidung] + (d.kommentar ? ' – ' + d.kommentar : ''),
      position_status: () => '„' + d.artikel + '“: ' + (d.status || 'Status zurückgesetzt'),
      foto_neu: () => 'Foto' + (d.titel ? ': „' + d.titel + '“' : ' hochgeladen'),
      foto_verworfen: () => 'Foto entfernt' + (d.titel ? ': „' + d.titel + '“' : ''),
      mindmap: () => 'Mindmap hochgeladen: ' + d.titel,
      version: () => (d.versionsart === 'basisplan' ? 'Basisplan festgelegt' : 'Version gespeichert') + ': ' + d.name,
    };
    try { return (texte[e.art] || (() => e.art))(); } catch (f) { return e.art; }
  },

  // Warnungen und Hinweise als Banner (stufe 'warnung' rot, 'hinweis' blau)
  warnungen(liste) {
    if (!liste || !liste.length) return null;
    return T.el('div', { class: 'warnungen' }, liste.map(w =>
      T.el('div', { class: 'banner' + (w.stufe !== 'hinweis' ? ' warnung' : '') }, w.stufe !== 'hinweis' ? '⚠ ' : '', w.text)));
  },

  werText(e) { return e.wer_art === 'team' ? 'Team' : e.wer_art === 'system' ? 'System' : e.wer.toUpperCase(); },

  async kopieren(text) {
    try { await navigator.clipboard.writeText(text); T.meldung('Kopiert.'); }
    catch (e) { T.meldung('Kopieren ging nicht. Bitte den Text markieren und mit Strg+C kopieren.', true); }
  },
};
