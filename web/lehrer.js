// Lehrerbereich: Cockpit, Kalender und Aktivitaeten (cockpit.js), Projekte, Projektseite mit Team-Link, Teammitgliedern
// und Terminen, Termine (Projektzeiten, Ausfaelle, Ferien, Wochenuebersicht), Lehrkraefte (Admin), eigenes Konto.
'use strict';
const { el } = T;
const S = { konto: null, lehrkraefte: null, vorlagen: null, teamPort: null, terminVon: null,
  klasse: '', cockpitAnsicht: 'karten', kalMonat: null, aktFilter: null };
const inhalt = document.getElementById('inhalt');


function passwortVorschlag() {
  const zeichen = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  const zufall = crypto.getRandomValues(new Uint32Array(10));
  return Array.from(zufall, z => zeichen[z % zeichen.length]).join('');
}

async function lehrkraefte() {
  if (!S.lehrkraefte) S.lehrkraefte = (await T.api('GET', '/api/lehrkraefte')).lehrkraefte;
  return S.lehrkraefte;
}

function titelSetzen(text) {
  document.getElementById('unter').textContent = text;
  document.title = text ? text + ' · ' + T.NAME : T.NAME;
}

function fehlerZeigen(e) {
  if (e.status === 401) { location.replace('/anmelden'); return; }
  T.leeren(inhalt).appendChild(el('div', { class: 'leer', text: e.message }));
}

// --- Start und Navigation ---

async function start() {
  try {
    const ich = await T.api('GET', '/api/ich');
    S.konto = ich.konto;
    S.teamPort = ich.team_port;
  } catch (e) {
    if (e.status === 401) { location.replace('/anmelden'); return; }
    fehlerZeigen(e);
    return;
  }
  document.getElementById('wer').textContent = S.konto.name + ' · ' + S.konto.kuerzel.toUpperCase();
  document.querySelectorAll('[data-admin]').forEach(e => { e.hidden = S.konto.rolle !== 'admin'; });
  document.getElementById('abmelden').addEventListener('click', async () => {
    try { await T.api('POST', '/api/abmelden', {}); } finally { location.href = '/anmelden'; }
  });
  if (S.konto.pw_vorlaeufig) await passwortPflicht();
  window.addEventListener('hashchange', zeigen);
  zeigen();
}

async function zeigen() {
  const [ansicht, id] = (location.hash.slice(1) || 'cockpit').split('/');
  const nav = ansicht === 'projekt' ? 'projekte' : ansicht === 'besprechung' ? 'cockpit' : ansicht;
  document.querySelectorAll('nav.seite a').forEach(a => a.classList.toggle('an', a.dataset.ansicht === nav));
  try {
    if (ansicht === 'cockpit') await Cockpit.cockpitZeigen();
    else if (ansicht === 'kalender') await Cockpit.kalenderZeigen(id);
    else if (ansicht === 'aktivitaeten') await Cockpit.aktivitaetenZeigen();
    else if (ansicht === 'besprechung') await Besprechung.lehrerZeigen(Number(id));
    else if (ansicht === 'projekte') await projekteZeigen(false);
    else if (ansicht === 'archiv') await projekteZeigen(true);
    else if (ansicht === 'termine') await termineZeigen();
    else if (ansicht === 'projekt') await projektZeigen(Number(id));
    else if (ansicht === 'lehrkraefte') await lehrkraefteZeigen();
    else if (ansicht === 'konto') await kontoZeigen();
    else if (ansicht === 'einstellungen') await einstellungenZeigen();
    else location.hash = 'cockpit';
  } catch (e) { fehlerZeigen(e); }
}

// --- Projekte ---

function projektkarte(p) {
  return el('a', { class: 'karte projektkarte', href: '#projekt/' + p.id },
    el('div', { class: 'zeile' }, el('span', { class: 'chip blau', text: p.klasse }), el('span', { class: 'leise', text: p.schuljahr }),
      p.warnungen && p.warnungen.length ? el('span', { class: 'chip rot', title: p.warnungen.map(w => w.text).join('\n'),
        text: '⚠ ' + p.warnungen.length }) : null),
    el('h3', { text: p.titel }),
    el('dl', { class: 'daten' },
      el('dt', { text: 'Zeitraum' }), el('dd', { text: T.zeitraum(p.start, p.ende) }),
      el('dt', { text: 'Team' }), el('dd', { text: p.mitglieder === 1 ? '1 Mitglied' : p.mitglieder + ' Mitglieder' }),
      el('dt', { text: 'Betreut von' }), el('dd', { text: p.lehrkraefte.map(k => k.toUpperCase()).join(', ') }),
      el('dt', { text: 'Zuletzt' }), el('dd', { text: T.zeitText(p.zuletzt) || '–' })));
}

async function projekteZeigen(archiv) {
  titelSetzen(archiv ? 'Archiv' : 'Projekte');
  const { projekte } = await T.api('GET', '/api/projekte' + (archiv ? '?archiv=1' : ''));
  T.setzen(inhalt, 
    el('div', { class: 'werkzeug' },
      el('h1', { class: 'dreieck', text: archiv ? 'Archiv' : 'Projekte' }),
      archiv ? null : el('button', { class: 'haupt', type: 'button', onclick: neuesProjekt }, '+ Neues Projekt')),
    projekte.length ? el('div', { class: 'raster' }, projekte.map(projektkarte))
      : el('div', { class: 'leer', text: archiv ? 'Keine archivierten Projekte.'
        : 'Noch keine Projekte. Lege mit „Neues Projekt“ das erste an.' }));
}

function lehrkraftAuswahl(alle, gewaehlt) {
  return el('fieldset', { class: 'felder', style: 'border:0;padding:0;margin:0' },
    el('legend', { class: 'etikett', text: 'Betreut von' }),
    alle.filter(l => !l.gesperrt || gewaehlt.includes(l.id)).map(l => el('label', { class: 'haken' },
      el('input', { type: 'checkbox', name: 'lehrkraft', value: String(l.id), checked: gewaehlt.includes(l.id) }),
      l.name + ' (' + l.kuerzel.toUpperCase() + ')')));
}

function gewaehlteLehrkraefte(form) {
  const ids = Array.from(form.querySelectorAll('input[name=lehrkraft]:checked'), e => Number(e.value));
  if (!ids.length) throw new Error('Bitte mindestens eine Lehrkraft auswählen.');
  return ids;
}

function namenLesen(text) {
  return text.split('\n').map(z => z.trim()).filter(Boolean).map(zeile => {
    const teile = zeile.split(/\s+/);
    if (teile.length < 2) throw new Error('Bitte Vor- und Nachnamen angeben: „' + zeile + '“');
    return { vorname: teile.slice(0, -1).join(' '), nachname: teile[teile.length - 1] };
  });
}

async function neuesProjekt() {
  const alle = await lehrkraefte();
  if (!S.vorlagen) S.vorlagen = (await T.api('GET', '/api/vorlagen')).vorlagen;
  const heute = new Date();
  const montag = new Date(heute); montag.setDate(heute.getDate() - ((heute.getDay() + 6) % 7));
  const ende = new Date(montag); ende.setDate(montag.getDate() + 7 * 20);
  const f = {
    titel: el('input', { required: true, maxlength: '80', placeholder: 'Klimaanlage' }),
    klasse: el('input', { required: true, maxlength: '30', placeholder: 'BSMT 22b' }),
    start: el('input', { type: 'date', required: true, value: T.isoDatum(montag) }),
    ende: el('input', { type: 'date', required: true, value: T.isoDatum(ende) }),
    schuljahr: el('input', { maxlength: '9', placeholder: 'automatisch' }),
    vorlage: el('select', {}, S.vorlagen.map(v => el('option', { value: v.schluessel, text: v.name }))),
    namen: el('textarea', { rows: '5', placeholder: 'Lena Schmitt\nBen Weber\nMia Klein' }),
  };
  const id = await T.dialog({
    titel: 'Neues Projekt',
    knopf: 'Projekt anlegen',
    inhalt: el('div', { class: 'felder' },
      T.feld('Projekttitel', f.titel),
      el('div', { class: 'felder zwei' }, T.feld('Klasse', f.klasse), T.feld('Schuljahr', f.schuljahr)),
      el('div', { class: 'felder zwei' }, T.feld('Start', f.start, 'zählt ab dem Montag dieser Woche'), T.feld('Ende', f.ende)),
      T.feld('Vorlage', f.vorlage),
      T.feld('Teammitglieder', f.namen, 'ein Name pro Zeile: Vorname Nachname'),
      lehrkraftAuswahl(alle, [S.konto.id])),
    speichern: async form => {
      const { projekt } = await T.api('POST', '/api/projekte', {
        titel: f.titel.value, klasse: f.klasse.value, start: f.start.value, ende: f.ende.value,
        schuljahr: f.schuljahr.value, vorlage: f.vorlage.value, mitglieder: namenLesen(f.namen.value),
        lehrkraefte: gewaehlteLehrkraefte(form),
      });
      return projekt.id;
    },
  });
  if (id) { T.meldung('Projekt angelegt.'); location.hash = 'projekt/' + id; }
}

async function projektZeigen(id) {
  const { projekt: p } = await T.api('GET', '/api/projekte/' + id);
  const alle = await lehrkraefte();
  titelSetzen(p.titel);
  // Team-Links ueber HTTP: die Schuelergeraete kennen das Stammzertifikat nicht
  const link = (S.teamPort ? 'http://' + location.hostname + (S.teamPort === 80 ? '' : ':' + S.teamPort) : location.origin) + '/t/' + p.link_token;
  const namen = p.lehrkraft_ids.map(i => (alle.find(l => l.id === i) || { name: '?' }).name);

  const ueberblick = el('section', { class: 'karte' },
    el('div', { class: 'zeile' }, el('span', { class: 'chip blau', text: p.klasse }), el('span', { class: 'leise', text: p.schuljahr }),
      p.archiviert ? el('span', { class: 'chip rot', text: 'archiviert' }) : null),
    el('dl', { class: 'daten', style: 'margin-top:10px' },
      el('dt', { text: 'Zeitraum' }), el('dd', { text: T.zeitraum(p.start, p.ende) + ' (' + T.tagText(p.start) + ' bis ' + T.tagText(p.ende) + ')' }),
      el('dt', { text: 'Betreut von' }), el('dd', { text: namen.join(', ') }),
      p.beschreibung ? [el('dt', { text: 'Beschreibung' }), el('dd', { text: p.beschreibung })] : null));

  const linkFeld = el('input', { readonly: true, value: link, 'aria-label': 'Team-Link', onfocus: e => e.target.select() });
  const teamlink = el('section', { class: 'karte' },
    el('h2', { class: 'dreieck', text: 'Team-Link' }),
    el('p', { class: 'leise', text: p.archiviert ? 'Archivierte Projekte sind über den Link nicht erreichbar.'
      : 'Diesen Link im Teams-Chat der Gruppe teilen. Wer ihn hat, kann für das Team eintragen. Erneuern macht den alten Link sofort ungültig.' }),
    el('div', { class: 'link-feld' }, linkFeld,
      el('button', { type: 'button', onclick: () => T.kopieren(link) }, 'Kopieren'),
      el('a', { class: 'knopf', href: link, target: '_blank', rel: 'noopener' }, 'Öffnen'),
      el('button', { type: 'button', class: 'warnen', onclick: () => linkErneuern(p) }, 'Erneuern')));

  const mitglieder = el('section', { class: 'karte' },
    el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: 'Teammitglieder' }),
      el('span', { class: 'rechts' }, el('button', { type: 'button', onclick: () => mitgliedDialog(p) }, '+ Mitglied'))),
    p.mitglieder.length ? el('div', { class: 'rollbar' }, el('table', { class: 'liste' },
      el('thead', {}, el('tr', {}, el('th', { text: 'Kürzel' }), el('th', { text: 'Name' }), el('th', { text: 'Status' }), el('th', {}))),
      el('tbody', {}, p.mitglieder.map(m => el('tr', {},
        el('td', {}, el('span', { class: 'chip', text: m.kuerzel })),
        el('td', { text: m.vorname + ' ' + m.nachname }),
        el('td', {}, m.aktiv ? 'aktiv' : el('span', { class: 'chip rot', text: 'nicht mehr im Team' })),
        el('td', {}, el('button', { type: 'button', class: 'leicht', onclick: () => mitgliedDialog(p, m) }, 'Bearbeiten')))))))
      : el('div', { class: 'leer', text: 'Noch keine Teammitglieder.' }));

  const terminOrt = el('div');
  const termine = el('section', { class: 'karte' }, el('h2', { class: 'dreieck', text: 'Besprechungstermine' }), terminOrt);
  const warnOrt = el('div');
  const warnungenZeigen = liste => T.setzen(warnOrt, T.warnungen((liste || []).filter(w => w.stufe !== 'hinweis')));
  warnungenZeigen(p.warnungen);

  const sheetOrt = el('div');
  const struktur = el('section', { class: 'karte' }, el('h2', { class: 'dreieck', text: 'Tracking-Sheet' }), sheetOrt);

  const verlauf = el('section', { class: 'karte' },
    el('h2', { class: 'dreieck', text: 'Verlauf' }),
    el('div', { class: 'verlauf' }, p.verlauf.map(e => el('div', {},
      el('span', { class: 'zeit', text: T.zeitText(e.zeit) }),
      el('span', {}, el('b', { text: T.werText(e) }), ' ', T.verlaufText(e))))));

  T.setzen(inhalt, 
    el('div', { class: 'werkzeug' },
      el('h1', { class: 'dreieck', text: p.titel }),
      p.archiviert ? null : el('a', { class: 'knopf', href: '#besprechung/' + p.id }, 'Besprechung ▶'),
      el('button', { type: 'button', onclick: () => projektBearbeiten(p) }, 'Bearbeiten'),
      el('button', { type: 'button', class: p.archiviert ? '' : 'warnen', onclick: () => archivieren(p) },
        p.archiviert ? 'Wieder aktivieren' : 'Archivieren')),
    warnOrt, ueberblick, struktur, p.archiviert ? null : termine, p.archiviert ? null : teamlink, mitglieder, verlauf);
  const warnungenLaden = async () => {
    try { warnungenZeigen((await T.api('GET', '/api/projekte/' + p.id + '/termine')).warnungen); } catch (e) { /* bleibt */ }
  };
  Raster.erzeugen({ ort: sheetOrt, basis: '/api/projekte/' + p.id, rolle: 'lehrkraft', beiAenderung: warnungenLaden }).laden();
  if (!p.archiviert) {
    Termine.erzeugen({ ort: terminOrt, basis: '/api/projekte/' + p.id, rolle: 'lehrkraft', beiAenderung: a => warnungenZeigen(a.warnungen) }).laden();
  }
}

async function projektBearbeiten(p) {
  const alle = await lehrkraefte();
  const f = {
    titel: el('input', { required: true, maxlength: '80', value: p.titel }),
    klasse: el('input', { required: true, maxlength: '30', value: p.klasse }),
    schuljahr: el('input', { required: true, maxlength: '9', value: p.schuljahr }),
    start: el('input', { type: 'date', required: true, value: p.start }),
    ende: el('input', { type: 'date', required: true, value: p.ende }),
    beschreibung: el('textarea', { rows: '3', maxlength: '2000', value: p.beschreibung }),
  };
  const ok = await T.dialog({
    titel: 'Projekt bearbeiten',
    inhalt: el('div', { class: 'felder' },
      T.feld('Projekttitel', f.titel),
      el('div', { class: 'felder zwei' }, T.feld('Klasse', f.klasse), T.feld('Schuljahr', f.schuljahr)),
      el('div', { class: 'felder zwei' }, T.feld('Start', f.start), T.feld('Ende', f.ende)),
      T.feld('Beschreibung', f.beschreibung),
      lehrkraftAuswahl(alle, p.lehrkraft_ids)),
    speichern: form => T.api('POST', '/api/projekte/' + p.id, {
      titel: f.titel.value, klasse: f.klasse.value, schuljahr: f.schuljahr.value, start: f.start.value, ende: f.ende.value,
      beschreibung: f.beschreibung.value, lehrkraefte: gewaehlteLehrkraefte(form) }),
  });
  if (ok) { T.meldung('Gespeichert.'); zeigen(); }
}

async function mitgliedDialog(p, m) {
  const f = {
    vorname: el('input', { required: true, maxlength: '60', value: m ? m.vorname : '' }),
    nachname: el('input', { required: true, maxlength: '60', value: m ? m.nachname : '' }),
    aktiv: el('input', { type: 'checkbox', checked: m ? m.aktiv : true }),
  };
  const ok = await T.dialog({
    titel: m ? 'Teammitglied bearbeiten' : 'Teammitglied hinzufügen',
    inhalt: el('div', { class: 'felder' },
      el('div', { class: 'felder zwei' }, T.feld('Vorname', f.vorname), T.feld('Nachname', f.nachname)),
      m ? el('label', { class: 'haken' }, f.aktiv, 'gehört noch zum Team') : null),
    speichern: () => m
      ? T.api('POST', '/api/projekte/' + p.id + '/mitglieder/' + m.id, { vorname: f.vorname.value, nachname: f.nachname.value, aktiv: f.aktiv.checked })
      : T.api('POST', '/api/projekte/' + p.id + '/mitglieder', { vorname: f.vorname.value, nachname: f.nachname.value }),
  });
  if (ok) { T.meldung('Gespeichert.'); zeigen(); }
}

async function linkErneuern(p) {
  const ok = await T.dialog({
    titel: 'Team-Link erneuern?',
    inhalt: el('p', { text: 'Der bisherige Link funktioniert danach nicht mehr. Teile den neuen Link anschließend im Teams-Chat der Gruppe.' }),
    knopf: 'Erneuern', gefaehrlich: true,
    speichern: () => T.api('POST', '/api/projekte/' + p.id + '/link-erneuern', {}),
  });
  if (ok) { T.meldung('Neuer Link erstellt.'); zeigen(); }
}

async function archivieren(p) {
  const ok = await T.dialog({
    titel: p.archiviert ? 'Projekt wieder aktivieren?' : 'Projekt archivieren?',
    inhalt: el('p', { text: p.archiviert ? 'Das Projekt erscheint wieder unter „Projekte“, der Team-Link funktioniert wieder.'
      : 'Das Projekt wandert ins Archiv und lässt sich dort nur noch ansehen. Der Team-Link funktioniert nicht mehr.' }),
    knopf: p.archiviert ? 'Aktivieren' : 'Archivieren', gefaehrlich: !p.archiviert,
    speichern: () => T.api('POST', '/api/projekte/' + p.id + '/archivieren', { archiviert: !p.archiviert }),
  });
  if (ok) { T.meldung(p.archiviert ? 'Wieder aktiv.' : 'Archiviert.'); zeigen(); }
}

// --- Termine: Projektzeiten (Regeln), Projekttage der naechsten Wochen, Ausfaelle, Ferien ---

const WOCHENTAGE = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag'];
const RHYTHMUS = { jede: 'jede Woche', gerade: 'gerade KW', ungerade: 'ungerade KW' };

function tageSpaeter(text, n) { const d = T.datum(text); d.setDate(d.getDate() + n); return T.isoDatum(d); }
function datumText(text) { return text.slice(8, 10) + '.' + text.slice(5, 7) + '.' + text.slice(0, 4); }
function spanne(von, bis) { return von === bis ? datumText(von) : datumText(von) + ' – ' + datumText(bis); }
function schlussText(tage, zeit) {
  return (tage === 0 ? 'am selben Tag' : tage === 1 ? 'am Vortag' : tage + ' Tage vorher') + ', ' + zeit;
}
function dieserMontag() {
  const d = new Date(); d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return T.isoDatum(d);
}

async function termineZeigen() {
  titelSetzen('Termine');
  if (!S.terminVon) S.terminVon = dieserMontag();
  const d = await T.api('GET', '/api/termine?von=' + S.terminVon + '&wochen=4');
  const regeln = d.regeln.filter(r => r.aktiv);
  const blaettern = n => { S.terminVon = n ? tageSpaeter(S.terminVon, 7 * n) : null; zeigen(); };

  const regelKarte = el('section', { class: 'karte' },
    el('h2', { class: 'dreieck', text: 'Projektzeiten' }),
    el('p', { class: 'leise', text: 'Eine Regel je Projektzeit und Klasse. An jedem Projekttag entstehen die Besprechungstermine von selbst, Ferien und Ausfälle fallen weg. Die Regel gilt für alle Projekte der Klasse, die du betreust.' }),
    regeln.length ? el('div', { class: 'rollbar' }, el('table', { class: 'liste' },
      el('thead', {}, el('tr', {}, ['Klasse', 'Tag', 'Zeiten', 'Buchungsschluss', 'Projekte', ''].map(t => el('th', { text: t })))),
      el('tbody', {}, regeln.map(r => el('tr', {},
        el('td', {}, el('span', { class: 'chip blau', text: r.klasse })),
        el('td', {}, WOCHENTAGE[r.wochentag] + ', ' + RHYTHMUS[r.rhythmus],
          el('div', { class: 'leise', text: spanne(r.gueltig_von, r.gueltig_bis) })),
        el('td', {}, 'Projekt ' + r.von + '–' + r.bis,
          el('div', { class: 'leise', text: 'Besprechung ' + r.fenster_von + '–' + r.fenster_bis + ', je ' + r.laenge + ' min' })),
        el('td', { text: schlussText(r.schluss_tage, r.schluss_zeit) }),
        el('td', { text: r.projekte.length ? r.projekte.join(', ') : '–' }),
        el('td', {}, el('div', { class: 'zeile' },
          el('button', { type: 'button', class: 'leicht', onclick: () => regelDialog(d, r) }, 'Bearbeiten'),
          el('button', { type: 'button', class: 'leicht', onclick: () => regelBeenden(r) }, 'Beenden'))))))))
      : el('div', { class: 'leer', text: 'Noch keine Projektzeit. Lege mit „+ Projektzeit“ die erste an, z. B. dienstags in ungeraden KW.' }));

  const wochenKarte = el('section', { class: 'karte' },
    el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: 'Projekttage' }),
      el('span', { class: 'rechts' },
        el('button', { type: 'button', title: 'frühere Wochen', 'aria-label': 'frühere Wochen', onclick: () => blaettern(-4) }, '‹'),
        el('button', { type: 'button', onclick: () => blaettern(0) }, T.kwText(d.von) + ' bis ' + T.kwText(d.bis)),
        el('button', { type: 'button', title: 'spätere Wochen', 'aria-label': 'spätere Wochen', onclick: () => blaettern(4) }, '›'))),
    d.tage.length ? el('div', { class: 'tage-raster' }, d.tage.map(t => tagKarte(t)))
      : el('div', { class: 'leer', text: regeln.length ? 'In diesen Wochen gibt es keine Projekttage.' : 'Ohne Projektzeit gibt es keine Projekttage.' }));

  const ausfallKarte = el('section', { class: 'karte stapel' },
    el('h2', { class: 'dreieck', text: 'Ausfälle' }),
    el('p', { class: 'leise', text: 'Tage, an denen deine Projektzeiten ausfallen (Exkursion, Prüfung, Fortbildung). Ohne Klasse gilt der Ausfall für alle deine Projektzeiten.' }),
    d.ausfaelle.length ? el('div', { class: 'eintraege' }, d.ausfaelle.map(a => el('div', { class: 'zeile' },
      el('span', { class: 'mono', text: spanne(a.von, a.bis) }), el('span', { class: 'chip' + (a.klasse ? ' blau' : ''), text: a.klasse || 'alle' }),
      el('span', { text: a.grund }),
      el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'leicht', onclick: () => entfernen('/api/termine/ausfaelle/' + a.id, 'Ausfall „' + a.grund + '“') }, 'Entfernen')))))
      : el('div', { class: 'leise', text: 'Keine Ausfälle eingetragen.' }),
    el('div', {}, el('button', { type: 'button', onclick: () => ausfallDialog(d) }, '+ Ausfall')));

  const ferienKarte = el('section', { class: 'karte stapel' },
    el('h2', { class: 'dreieck', text: 'Ferien' }),
    el('p', { class: 'leise', text: 'Gelten für alle Lehrkräfte. Später kommen sie automatisch aus dem Schulkalender-Abo.' }),
    d.ferien.length ? el('div', { class: 'eintraege' }, d.ferien.map(f => el('div', { class: 'zeile' },
      el('span', { class: 'mono', text: spanne(f.von, f.bis) }), el('span', { text: f.name }),
      f.quelle === 'abo' ? el('span', { class: 'chip', text: 'Abo' }) : null,
      el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'leicht', onclick: () => entfernen('/api/termine/ferien/' + f.id, f.name) }, 'Entfernen')))))
      : el('div', { class: 'leise', text: 'Keine Ferien eingetragen.' }),
    el('div', {}, el('button', { type: 'button', onclick: ferienDialog }, '+ Ferien')));

  T.setzen(inhalt,
    el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Termine' }),
      el('button', { type: 'button', class: 'haupt', onclick: () => regelDialog(d) }, '+ Projektzeit')),
    regelKarte, wochenKarte, el('div', { class: 'raster zwei-spalten' }, ausfallKarte, ferienKarte));
}

function tagKarte(t) {
  const anpassbar = !t.entfaellt || t.gestrichen;
  const kopf = el('div', { class: 'zeile' }, el('b', { text: T.kurzTag(t.datum) }), el('span', { class: 'chip blau', text: t.klasse }),
    t.angepasst ? el('span', { class: 'chip', text: 'angepasst' }) : null,
    anpassbar ? el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'leicht', onclick: () => tagDialog(t) }, 'Tag anpassen')) : null);
  if (t.entfaellt) return el('div', { class: 'termin-tag entfaellt' }, kopf, el('div', { class: 'leise', text: 'entfällt: ' + t.entfaellt }));
  return el('div', { class: 'termin-tag' }, kopf,
    el('div', { class: 'leise', text: 'Buchungsschluss ' + T.zeitpunkt(t.schluss) + (t.grund ? ' · ' + t.grund : '') }),
    el('div', { class: 'slots' }, t.plaetze.map(p => el('div', { class: 'slot' + (p.team ? ' belegt' : '') + (p.vergangen ? ' vorbei' : '') },
      el('span', { class: 'mono', text: p.uhrzeit }),
      p.team ? el('a', { href: '#projekt/' + p.projekt_id, text: p.team })
        : t.ohne_termin.length && !p.vergangen ? teamEintragen(t, p) : el('span', { class: 'leise', text: 'frei' }),
      p.von_lehrkraft ? el('span', { class: 'leise', text: 'von Lehrkraft' }) : null))),
    t.ohne_termin.length ? el('div', { class: 'ohne' }, 'Noch ohne Termin: ', t.ohne_termin.map(x => x.titel).join(', '))
      : t.projekte ? null : el('div', { class: 'leise', text: 'Du betreust kein Projekt dieser Klasse.' }));
}

function teamEintragen(t, p) {
  return el('select', { class: 'klein', 'aria-label': 'Team für ' + p.uhrzeit + ' eintragen', onchange: async ev => {
    if (!ev.target.value) return;
    try {
      await T.api('POST', '/api/projekte/' + ev.target.value + '/termin', { regel_id: t.regel_id, datum: t.datum, uhrzeit: p.uhrzeit });
      T.meldung('Eingetragen.');
      zeigen();
    } catch (e) { T.meldung(e.message, true); ev.target.value = ''; }
  } }, el('option', { value: '', text: 'frei · Team eintragen' }), t.ohne_termin.map(x => el('option', { value: String(x.id), text: x.titel })));
}

async function regelDialog(d, r) {
  const heute = new Date();
  const schuljahrEnde = (heute.getMonth() >= 7 ? heute.getFullYear() + 1 : heute.getFullYear()) + '-07-31';
  const f = {
    klasse: el('input', { required: true, maxlength: '30', list: 'klassen-liste', placeholder: 'BSMT 22b', value: r ? r.klasse : (d.klassen[0] || '') }),
    wochentag: el('select', {}, WOCHENTAGE.map((t, i) => el('option', { value: String(i), text: t }))),
    rhythmus: el('select', {}, Object.entries(RHYTHMUS).map(([k, t]) => el('option', { value: k, text: t }))),
    von: el('input', { type: 'time', required: true, value: r ? r.von : '08:00' }),
    bis: el('input', { type: 'time', required: true, value: r ? r.bis : '11:15' }),
    fenster_von: el('input', { type: 'time', required: true, value: r ? r.fenster_von : '08:30' }),
    fenster_bis: el('input', { type: 'time', required: true, value: r ? r.fenster_bis : '10:00' }),
    laenge: el('input', { type: 'number', required: true, min: '5', max: '120', step: '5', value: String(r ? r.laenge : 15) }),
    schluss_tage: el('select', {}, [0, 1, 2, 3, 4, 5, 6, 7].map(n => el('option', { value: String(n),
      text: n === 0 ? 'am Projekttag selbst' : n === 1 ? 'am Vortag' : n + ' Tage vorher' }))),
    schluss_zeit: el('input', { type: 'time', required: true, value: r ? r.schluss_zeit : '18:00' }),
    gueltig_von: el('input', { type: 'date', required: true, value: r ? r.gueltig_von : T.isoDatum(heute) }),
    gueltig_bis: el('input', { type: 'date', required: true, value: r ? r.gueltig_bis : schuljahrEnde }),
  };
  f.wochentag.value = String(r ? r.wochentag : 1);
  f.rhythmus.value = r ? r.rhythmus : 'jede';
  f.schluss_tage.value = String(r ? r.schluss_tage : 1);
  const vorschau = el('div', { class: 'leise' });
  const minuten = t => { const [h, m] = (t || '0:0').split(':').map(Number); return h * 60 + m; };
  const rechnen = () => {
    const n = Math.floor((minuten(f.fenster_bis.value) - minuten(f.fenster_von.value)) / (Number(f.laenge.value) || 1));
    vorschau.textContent = n > 0 ? n + (n === 1 ? ' Termin' : ' Termine') + ' je Projekttag' : 'Ins Fenster passt kein Termin.';
  };
  [f.fenster_von, f.fenster_bis, f.laenge].forEach(e => e.addEventListener('input', rechnen));
  rechnen();
  const ok = await T.dialog({
    titel: r ? 'Projektzeit bearbeiten' : 'Neue Projektzeit', knopf: r ? 'Speichern' : 'Anlegen',
    inhalt: el('div', { class: 'felder' },
      T.feld('Klasse', f.klasse, 'gilt für alle Projekte dieser Klasse, die du betreust'),
      el('datalist', { id: 'klassen-liste' }, d.klassen.map(k => el('option', { value: k }))),
      el('div', { class: 'felder zwei' }, T.feld('Wochentag', f.wochentag), T.feld('Rhythmus', f.rhythmus)),
      el('div', { class: 'felder zwei' }, T.feld('Projektzeit von', f.von), T.feld('bis', f.bis)),
      el('div', { class: 'felder drei' }, T.feld('Besprechungen von', f.fenster_von), T.feld('bis', f.fenster_bis), T.feld('je Termin (min)', f.laenge)),
      vorschau,
      el('div', { class: 'felder zwei' }, T.feld('Buchungsschluss', f.schluss_tage), T.feld('um', f.schluss_zeit)),
      el('div', { class: 'felder zwei' }, T.feld('Gilt ab', f.gueltig_von), T.feld('bis', f.gueltig_bis)),
      r ? el('p', { class: 'leise', text: 'Gebuchte Termine, die es danach nicht mehr gibt, entfallen. Das steht im Verlauf des Projekts.' }) : null),
    speichern: () => T.api('POST', r ? '/api/termine/regeln/' + r.id : '/api/termine/regeln', {
      klasse: f.klasse.value, wochentag: Number(f.wochentag.value), rhythmus: f.rhythmus.value, von: f.von.value, bis: f.bis.value,
      fenster_von: f.fenster_von.value, fenster_bis: f.fenster_bis.value, laenge: Number(f.laenge.value),
      schluss_tage: Number(f.schluss_tage.value), schluss_zeit: f.schluss_zeit.value,
      gueltig_von: f.gueltig_von.value, gueltig_bis: f.gueltig_bis.value }),
  });
  if (ok) { T.meldung('Gespeichert.'); zeigen(); }
}

async function regelBeenden(r) {
  const ok = await T.dialog({
    titel: 'Projektzeit beenden?', knopf: 'Beenden', gefaehrlich: true,
    inhalt: el('p', { text: r.klasse + ', ' + WOCHENTAGE[r.wochentag] + ' (' + RHYTHMUS[r.rhythmus] + '): Es entstehen keine neuen Termine mehr, künftige Buchungen entfallen. Die Regel bleibt gespeichert.' }),
    speichern: () => T.api('POST', '/api/termine/regeln/' + r.id, { aktiv: false }),
  });
  if (ok) { T.meldung('Projektzeit beendet.'); zeigen(); }
}

async function tagDialog(t) {
  const art = el('select', {},
    el('option', { value: 'anpassen', text: 'Termine an diesem Tag anpassen' }),
    el('option', { value: 'streichen', text: 'Tag streichen (keine Besprechungen)' }),
    t.angepasst || t.gestrichen ? el('option', { value: 'zuruecksetzen', text: 'Wie in der Regel' }) : null);
  art.value = t.gestrichen ? 'zuruecksetzen' : 'anpassen';
  const f = {
    fenster_von: el('input', { type: 'time', value: t.fenster_von }),
    fenster_bis: el('input', { type: 'time', value: t.fenster_bis }),
    laenge: el('input', { type: 'number', min: '5', max: '120', step: '5', value: String(t.laenge) }),
    grund: el('input', { maxlength: '120', value: t.grund || '', placeholder: 'z. B. Exkursion' }),
  };
  const zeiten = el('div', { class: 'felder drei' }, T.feld('Besprechungen von', f.fenster_von), T.feld('bis', f.fenster_bis), T.feld('je Termin (min)', f.laenge));
  const grund = T.feld('Grund', f.grund, 'beim Streichen Pflicht; Teams mit Buchung sehen ihn im Verlauf');
  const umschalten = () => { zeiten.hidden = art.value !== 'anpassen'; grund.hidden = art.value === 'zuruecksetzen'; };
  art.addEventListener('change', umschalten);
  umschalten();
  const ok = await T.dialog({
    titel: T.kurzTag(t.datum) + ' · ' + t.klasse,
    inhalt: el('div', { class: 'felder' }, T.feld('Was soll sich ändern?', art), zeiten, grund,
      el('p', { class: 'leise', text: 'Gebuchte Termine, die es danach nicht mehr gibt, entfallen.' })),
    speichern: () => T.api('POST', '/api/termine/regeln/' + t.regel_id + '/tag', {
      datum: t.datum, zuruecksetzen: art.value === 'zuruecksetzen', gestrichen: art.value === 'streichen', grund: f.grund.value,
      fenster_von: f.fenster_von.value, fenster_bis: f.fenster_bis.value, laenge: Number(f.laenge.value) }),
  });
  if (ok) { T.meldung('Gespeichert.'); zeigen(); }
}

async function ausfallDialog(d) {
  const f = {
    von: el('input', { type: 'date', required: true, value: T.isoDatum(new Date()) }),
    bis: el('input', { type: 'date' }),
    klasse: el('select', {}, el('option', { value: '', text: 'alle meine Projektzeiten' }), d.klassen.map(k => el('option', { value: k, text: k }))),
    grund: el('input', { required: true, maxlength: '120', placeholder: 'z. B. Exkursion, Prüfung, Fortbildung' }),
  };
  const ok = await T.dialog({
    titel: 'Ausfall eintragen', knopf: 'Eintragen',
    inhalt: el('div', { class: 'felder' },
      el('div', { class: 'felder zwei' }, T.feld('Von', f.von), T.feld('Bis', f.bis, 'leer = nur ein Tag')),
      T.feld('Für', f.klasse), T.feld('Grund', f.grund, 'Die Teams sehen den Grund in ihrer Übersicht.')),
    speichern: () => T.api('POST', '/api/termine/ausfaelle', { von: f.von.value, bis: f.bis.value || f.von.value, klasse: f.klasse.value, grund: f.grund.value }),
  });
  if (ok) { T.meldung('Ausfall eingetragen.'); zeigen(); }
}

async function ferienDialog() {
  const f = {
    name: el('input', { required: true, maxlength: '80', placeholder: 'z. B. Herbstferien' }),
    von: el('input', { type: 'date', required: true }),
    bis: el('input', { type: 'date', required: true }),
  };
  const ok = await T.dialog({
    titel: 'Ferien eintragen', knopf: 'Eintragen',
    inhalt: el('div', { class: 'felder' }, T.feld('Name', f.name), el('div', { class: 'felder zwei' }, T.feld('Erster Ferientag', f.von), T.feld('Letzter Ferientag', f.bis))),
    speichern: () => T.api('POST', '/api/termine/ferien', { name: f.name.value, von: f.von.value, bis: f.bis.value }),
  });
  if (ok) { T.meldung('Ferien eingetragen.'); zeigen(); }
}

async function entfernen(url, was) {
  const ok = await T.dialog({
    titel: 'Entfernen?', knopf: 'Entfernen', gefaehrlich: true,
    inhalt: el('p', { text: was + ' wird entfernt. Die Projekttage in diesem Zeitraum finden dann wieder statt.' }),
    speichern: () => T.api('POST', url + '/entfernen', {}),
  });
  if (ok) { T.meldung('Entfernt.'); zeigen(); }
}

// --- Lehrkraefte (Admin) ---

async function lehrkraefteZeigen() {
  titelSetzen('Lehrkräfte');
  S.lehrkraefte = null;
  const alle = await lehrkraefte();
  T.setzen(inhalt, 
    el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Lehrkräfte' }),
      el('button', { class: 'haupt', type: 'button', onclick: () => lehrkraftDialog() }, '+ Lehrkraft')),
    el('section', { class: 'karte rollbar' }, el('table', { class: 'liste' },
      el('thead', {}, el('tr', {}, ['Kürzel', 'Name', 'Rolle', 'Status', ''].map(t => el('th', { text: t })))),
      el('tbody', {}, alle.map(l => el('tr', {},
        el('td', {}, el('span', { class: 'chip', text: l.kuerzel.toUpperCase() })),
        el('td', { text: l.name }),
        el('td', { text: l.rolle === 'admin' ? 'Admin' : 'Lehrkraft' }),
        el('td', {}, l.gesperrt ? el('span', { class: 'chip rot', text: 'gesperrt' })
          : l.pw_vorlaeufig ? el('span', { class: 'chip', text: 'vorläufiges Passwort' }) : 'aktiv'),
        el('td', {}, el('button', { type: 'button', class: 'leicht', onclick: () => lehrkraftDialog(l) }, 'Bearbeiten'))))))));
}

async function lehrkraftDialog(l) {
  const pw = el('input', { readonly: true, value: l ? '' : passwortVorschlag(), class: 'mono' });
  const f = {
    kuerzel: el('input', { required: true, maxlength: '8', autocapitalize: 'none', value: l ? l.kuerzel : '', readonly: !!l, placeholder: 'scu' }),
    name: el('input', { required: true, maxlength: '80', value: l ? l.name : '' }),
    rolle: el('select', {}, el('option', { value: 'lehrkraft', text: 'Lehrkraft' }), el('option', { value: 'admin', text: 'Admin (verwaltet auch Konten)' })),
    gesperrt: el('input', { type: 'checkbox', checked: l ? l.gesperrt : false }),
  };
  if (l) f.rolle.value = l.rolle;
  const neuesPw = el('button', { type: 'button', onclick: () => { pw.value = passwortVorschlag(); } }, 'Neues vorläufiges Passwort');
  const ergebnis = await T.dialog({
    titel: l ? 'Lehrkraft bearbeiten' : 'Lehrkraft anlegen',
    knopf: l ? 'Speichern' : 'Anlegen',
    inhalt: el('div', { class: 'felder' },
      el('div', { class: 'felder zwei' }, T.feld('Kürzel', f.kuerzel), T.feld('Rolle', f.rolle)),
      T.feld('Name', f.name),
      l ? el('div', { class: 'zeile' }, neuesPw) : null,
      T.feld('Vorläufiges Passwort', pw, l ? 'nur ausgefüllt, wenn du ein neues erzeugst' : 'muss bei der ersten Anmeldung geändert werden'),
      l ? el('label', { class: 'haken' }, f.gesperrt, 'Konto gesperrt (beendet alle Anmeldungen)') : null),
    speichern: async () => {
      if (l) {
        await T.api('POST', '/api/lehrkraefte/' + l.id, { name: f.name.value, rolle: f.rolle.value, gesperrt: f.gesperrt.checked,
          passwort: pw.value || undefined });
      } else {
        await T.api('POST', '/api/lehrkraefte', { kuerzel: f.kuerzel.value, name: f.name.value, rolle: f.rolle.value, passwort: pw.value });
      }
      return { kuerzel: f.kuerzel.value.trim().toLowerCase(), pw: pw.value };
    },
  });
  if (!ergebnis) return;
  if (ergebnis.pw) {
    await T.dialog({
      titel: 'Zugangsdaten weitergeben',
      inhalt: el('div', { class: 'felder' },
        el('p', { text: 'Gib diese Daten persönlich weiter. Das Passwort wird nur jetzt angezeigt und muss bei der ersten Anmeldung geändert werden.' }),
        el('dl', { class: 'daten' }, el('dt', { text: 'Kürzel' }), el('dd', { class: 'mono', text: ergebnis.kuerzel }),
          el('dt', { text: 'Passwort' }), el('dd', { class: 'mono', text: ergebnis.pw }))),
      knopf: 'Fertig', abbrechen: null,
    });
  } else {
    T.meldung('Gespeichert.');
  }
  zeigen();
}

// --- Einstellungen (Admin): Schul-Logo ---

function dateiLesen(datei) {
  return new Promise((ok, fehler) => {
    const leser = new FileReader();
    leser.onload = () => ok(String(leser.result).split(',')[1] || '');
    leser.onerror = () => fehler(new Error('Die Datei konnte nicht gelesen werden.'));
    leser.readAsDataURL(datei);
  });
}

async function einstellungenZeigen() {
  titelSetzen('Einstellungen');
  const einst = await T.api('GET', '/api/einstellungen');
  const logo = einst.logo;
  const datei = el('input', { type: 'file', accept: '.svg,.png,.jpg,.jpeg,image/svg+xml,image/png,image/jpeg' });
  const vorschau = logo ? el('img', { src: '/logo?' + Date.now(), alt: 'aktuelles Logo', class: 'logo-vorschau' })
    : el('div', { class: 'leer', text: 'Noch kein Logo hinterlegt.' });
  const hochladen = async () => {
    if (!datei.files.length) { T.meldung('Bitte zuerst eine Datei wählen.', true); return; }
    try {
      await T.api('POST', '/api/einstellungen/logo', { inhalt: await dateiLesen(datei.files[0]) });
      T.meldung('Logo gespeichert.');
      location.reload();
    } catch (e) { T.meldung(e.message, true); }
  };
  const entfernen = async () => {
    try { await T.api('POST', '/api/einstellungen/logo-entfernen', {}); T.meldung('Logo entfernt.'); location.reload(); }
    catch (e) { T.meldung(e.message, true); }
  };
  T.setzen(inhalt,
    el('h1', { class: 'dreieck', text: 'Einstellungen' }),
    el('section', { class: 'karte stapel' },
      el('h2', { class: 'dreieck', text: 'Schul-Logo' }),
      el('p', { class: 'leise', text: 'Erscheint oben links auf allen Seiten, auch bei den Teams. Am besten das Querformat als SVG oder PNG (höchstens 1 MB).' }),
      vorschau,
      el('div', { class: 'zeile' }, datei, el('button', { type: 'button', class: 'haupt', onclick: hochladen }, 'Hochladen'),
        logo ? el('button', { type: 'button', class: 'warnen', onclick: entfernen }, 'Logo entfernen') : null)),
    Cockpit.schulKarte(einst));
}

// --- Eigenes Konto ---

function passwortFelder() {
  return {
    alt: el('input', { type: 'password', required: true, autocomplete: 'current-password' }),
    neu: el('input', { type: 'password', required: true, minlength: '8', autocomplete: 'new-password' }),
    neu2: el('input', { type: 'password', required: true, minlength: '8', autocomplete: 'new-password' }),
  };
}

async function passwortSpeichern(f) {
  if (f.neu.value !== f.neu2.value) throw new Error('Die beiden neuen Passwörter stimmen nicht überein.');
  S.konto = (await T.api('POST', '/api/passwort', { alt: f.alt.value, neu: f.neu.value })).konto;
  return true;
}

async function passwortPflicht() {
  const f = passwortFelder();
  await T.dialog({
    titel: 'Eigenes Passwort festlegen', knopf: 'Passwort speichern', fest: true,
    inhalt: el('div', { class: 'felder' },
      el('p', { text: 'Du hast ein vorläufiges Passwort bekommen. Bitte lege jetzt ein eigenes fest (mindestens 8 Zeichen).' }),
      T.feld('Vorläufiges Passwort', f.alt), T.feld('Neues Passwort', f.neu), T.feld('Neues Passwort wiederholen', f.neu2)),
    speichern: () => passwortSpeichern(f),
  });
}

async function kontoZeigen() {
  titelSetzen('Mein Konto');
  const f = passwortFelder();
  const fehler = el('div', { class: 'fehlertext', role: 'alert' });
  const form = el('form', { class: 'felder', style: 'max-width:420px' },
    T.feld('Bisheriges Passwort', f.alt), T.feld('Neues Passwort', f.neu, 'mindestens 8 Zeichen'), T.feld('Neues Passwort wiederholen', f.neu2),
    fehler, el('div', {}, el('button', { class: 'haupt', type: 'submit' }, 'Passwort ändern')));
  form.addEventListener('submit', async ev => {
    ev.preventDefault();
    fehler.textContent = '';
    try { await passwortSpeichern(f); form.reset(); T.meldung('Passwort geändert. Andere Anmeldungen sind beendet.'); }
    catch (e) { fehler.textContent = e.message; }
  });
  T.setzen(inhalt, 
    el('h1', { class: 'dreieck', text: 'Mein Konto' }),
    el('section', { class: 'karte' }, el('dl', { class: 'daten' },
      el('dt', { text: 'Name' }), el('dd', { text: S.konto.name }),
      el('dt', { text: 'Kürzel' }), el('dd', { text: S.konto.kuerzel }),
      el('dt', { text: 'Rolle' }), el('dd', { text: S.konto.rolle === 'admin' ? 'Admin' : 'Lehrkraft' }))),
    el('section', { class: 'karte' }, el('h2', { class: 'dreieck', text: 'Passwort ändern' }), form));
  inhalt.appendChild(await Cockpit.dienstKarte());
}

start();
