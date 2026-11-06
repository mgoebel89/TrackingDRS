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
    // Anfragen (Lucide-Formen, ISC-Lizenz)
    eingang: 'M22 12h-6l-2 3h-4l-2-3H2M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z',
    wagen: 'M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12M8 20a1 1 0 1 0 0 2a1 1 0 1 0 0-2M19 20a1 1 0 1 0 0 2a1 1 0 1 0 0-2',
    glocke: 'M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0',
    glocke_aus: 'M8.7 3A6 6 0 0 1 18 8a21.3 21.3 0 0 0 .6 5M17 17H3s3-2 3-9a4.67 4.67 0 0 1 .3-1.7M10.3 21a1.94 1.94 0 0 0 3.4 0M2 2l20 20',
    person: 'M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2M12 3a4 4 0 1 0 0 8a4 4 0 1 0 0-8',
    frage: 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3M12 17h.01',
    liste: 'M3 17l2 2 4-4M3 7l2 2 4-4M13 6h8M13 12h8M13 18h8',
    material: 'M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73zM12 22V12M3.3 7l8.7 5 8.7-5',
    abnahme: 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M9 12l2 2 4-4',
    kalender: 'M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM16 2v4M8 2v4M3 10h18',
    // Tafel-Werkzeuge
    zeiger: 'M4.04 4.69a.5.5 0 0 1 .65-.65l16 6.5a.5.5 0 0 1-.06.95l-6.12 1.58a2 2 0 0 0-1.44 1.44l-1.58 6.12a.5.5 0 0 1-.95.06z',
    stift: 'M21.17 6.81a2.82 2.82 0 0 0-3.99-3.99L3.84 16.17a2 2 0 0 0-.5.83l-1.32 4.35a.5.5 0 0 0 .62.62l4.35-1.32a2 2 0 0 0 .83-.5zM15 5l4 4',
    marker: 'M9 11l-6 6v3h9l3-3M22 12l-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4',
    pfeil: 'M7 17 17 7M7 7h10v10',
    radierer: 'M7 21l-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21M22 21H7M5 11l9 9',
    postit: 'M16 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V8zM15 3v4a2 2 0 0 0 2 2h4',
    rahmen: 'M22 6H2M22 18H2M6 2v20M18 2v20',
    sticker: 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01',
    zurueck: 'M9 14 4 9l5-5M4 9h10.5a5.5 5.5 0 0 1 0 11H11',
    vor: 'M15 14l5-5-5-5M20 9H9.5a5.5 5.5 0 0 0 0 11H13',
    laden: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3',
    bild: 'M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM9 7a2 2 0 1 0 0 4a2 2 0 1 0 0-4M21 15l-3.09-3.09a2 2 0 0 0-2.82 0L6 21',
    // Sticker
    st_idee: 'M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5M9 18h6M10 22h4',
    st_problem: 'M21.73 18l-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3M12 9v4M12 17h.01',
    st_frage: 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3M12 17h.01',
    st_ok: 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M9 12l2 2 4-4',
    st_nein: 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M15 9l-6 6M9 9l6 6',
    st_stern: 'M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z',
    st_ziel: 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M12 6a6 6 0 1 0 0 12a6 6 0 1 0 0-12M12 10a2 2 0 1 0 0 4a2 2 0 1 0 0-4',
    st_uhr: 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M12 6v6l4 2',
    st_flagge: 'M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1zM4 22v-7',
    st_gut: 'M7 10v12M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88z',
    st_schlecht: 'M17 14V2M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88z',
    st_team: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 3a4 4 0 1 0 0 8a4 4 0 1 0 0-8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
    st_fertigung: 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94z',
    st_elektrik: 'M13 2 3 14h9l-1 8 10-12h-9z',
    st_mechanik: 'M12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6M12 5a7 7 0 1 0 0 14a7 7 0 1 0 0-14M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1',
    st_programm: 'M16 18l6-6-6-6M8 6l-6 6 6 6',
    st_material: 'M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73zM12 22V12M3.3 7l8.7 5 8.7-5',
    st_mass: 'M21.3 15.3a2.4 2.4 0 0 1 0 3.4l-2.6 2.6a2.4 2.4 0 0 1-3.4 0L2.7 8.7a2.41 2.41 0 0 1 0-3.4l2.6-2.6a2.41 2.41 0 0 1 3.4 0zM14.5 12.5l2-2M11.5 9.5l2-2M8.5 6.5l2-2M17.5 15.5l2-2',
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
  reiterZahl(leiste, n, titel, schluessel) {
    const b = leiste && leiste.querySelector(schluessel ? 'a[data-reiter="' + schluessel + '"] .reiter-zahl' : '.reiter-zahl');
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
      anfrage_wieder: () => '„' + d.titel + '“ wieder geöffnet: ' + d.text,
      sonderfenster: () => 'Sonderfenster für die Bestellliste bis ' + d.bis.slice(8, 10) + '.' + d.bis.slice(5, 7) + '., ' + d.bis.slice(11, 16),
      position_neu: () => 'Bestellliste: ' + d.menge + '× „' + d.artikel + '“' + (d.uebernommen ? ' (übernommen)' : ''),
      position_geaendert: () => 'Bestellliste: „' + d.artikel + '“ geändert',
      position_gestrichen: () => 'Bestellliste: „' + d.artikel + '“ gestrichen',
      position_zurueck: () => 'Bestellliste: „' + d.artikel + '“ wieder aufgenommen',
      liste_eingereicht: () => 'Bestellliste eingereicht (' + d.positionen + ' Positionen)',
      position_entschieden: () => '„' + d.artikel + '“: ' + ({ bestellen: 'wird bestellt', lager: 'aus dem SchulLager', firma: 'über die Firma',
        ersetzen: d.ersatz ? 'ersetzt durch ' + d.ersatz : 'Ersatz gesucht', ablehnen: 'abgelehnt' })[d.entscheidung] + (d.kommentar ? ' – ' + d.kommentar : ''),
      position_status: () => '„' + d.artikel + '“: ' + (d.status || 'Status zurückgesetzt'),
      firma_zugesagt: () => '„' + d.artikel + '“: ' + d.name + ' besorgt es über die Firma',
      firma_nein: () => '„' + d.artikel + '“: über die Firma nicht möglich',
      firma_besorgt: () => '„' + d.artikel + '“: über die Firma besorgt und mitgebracht',
      firma_nicht_besorgt: () => '„' + d.artikel + '“: Haken „besorgt“ zurückgenommen',
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
