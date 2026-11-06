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
  T.titel(text);
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
    S.update = ich.update;
    S.vpn = ich.vpn;
  } catch (e) {
    if (e.status === 401) { location.replace('/anmelden'); return; }
    fehlerZeigen(e);
    return;
  }
  document.getElementById('wer').textContent = S.konto.name + ' · ' + S.konto.kuerzel.toUpperCase();
  document.querySelectorAll('[data-admin]').forEach(e => { e.hidden = S.konto.rolle !== 'admin'; });
  updateMarke();
  document.getElementById('abmelden').addEventListener('click', async () => {
    try { await T.api('POST', '/api/abmelden', {}); } finally { location.href = '/anmelden'; }
  });
  if (S.konto.pw_vorlaeufig) await passwortPflicht();
  window.addEventListener('hashchange', zeigen);
  zeigen();
  Vorgang.beobachten();
}

async function zeigen() {
  const [ansicht, id, id2, id3] = (location.hash.slice(1) || 'cockpit').split('/');
  if (ansicht === 'besprechung') { location.replace('#projekt/' + id + '/besprechung'); return; }   // alte Links
  document.body.classList.remove('mit-unterleiste');
  const nav = ansicht === 'projekt' ? 'projekte' : ansicht === 'besprechung' ? 'cockpit' : ansicht;
  document.querySelectorAll('nav.seite a').forEach(a => a.classList.toggle('an', a.dataset.ansicht === nav));
  try {
    if (ansicht === 'cockpit') await Cockpit.cockpitZeigen();
    else if (ansicht === 'kalender') await Cockpit.kalenderZeigen(id);
    else if (ansicht === 'aktivitaeten') await Cockpit.aktivitaetenZeigen();
    else if (ansicht === 'anfragen') await Anfragen.lehrerZeigen(id, id2);
    else if (ansicht === 'projekte') await projekteZeigen(false);
    else if (ansicht === 'archiv') await projekteZeigen(true);
    else if (ansicht === 'termine') await termineZeigen();
    else if (ansicht === 'projekt') await projektZeigen(Number(id), id2, id3);
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
      el('dt', { text: 'Team' }), el('dd', { text: !p.mitglieder ? 'noch nicht eingetragen' : p.mitglieder === 1 ? '1 Mitglied' : p.mitglieder + ' Mitglieder' }),
      el('dt', { text: 'Betreut von' }), el('dd', { text: p.lehrkraefte.map(k => k.toUpperCase()).join(', ') }),
      el('dt', { text: 'Zuletzt' }), el('dd', { text: T.zeitText(p.zuletzt) || '–' })));
}

async function projekteZeigen(archiv) {
  titelSetzen(archiv ? 'Archiv' : 'Projekte');
  const { projekte } = await T.api('GET', '/api/projekte' + (archiv ? '?archiv=1' : ''));
  const jahre = [...new Set(projekte.map(p => p.schuljahr))].sort().reverse();
  T.setzen(inhalt,
    el('div', { class: 'werkzeug' },
      el('h1', { class: 'dreieck', text: archiv ? 'Archiv' : 'Projekte' }),
      archiv || !projekte.length ? null : el('button', { type: 'button', onclick: () => schuljahrArchivieren(jahre) }, 'Schuljahr archivieren …'),
      archiv ? null : el('button', { class: 'haupt', type: 'button', onclick: neuesProjekt }, '+ Neues Projekt')),
    archiv ? el('p', { class: 'leise', text: 'Archivierte Projekte sind nur noch lesbar, der Team-Link ist aus. Endgültig löschen geht auf der Projektseite.' }) : null,
    projekte.length ? jahre.map(j => el('section', { class: 'stapel-eng' },
      jahre.length > 1 || archiv ? el('h2', { class: 'etikett schuljahr', text: 'Schuljahr ' + j }) : null,
      el('div', { class: 'raster' }, projekte.filter(p => p.schuljahr === j).map(projektkarte))))
      : el('div', { class: 'leer', text: archiv ? 'Keine archivierten Projekte.'
        : 'Noch keine Projekte. Lege mit „Neues Projekt“ das erste an.' }));
}

async function schuljahrArchivieren(jahre) {
  const wahl = el('select', {}, jahre.map(j => el('option', { value: j, text: j })));
  const ok = await T.dialog({
    titel: 'Schuljahr archivieren', knopf: 'Archivieren', gefaehrlich: true,
    inhalt: el('div', { class: 'felder' }, T.feld('Schuljahr', wahl),
      el('p', { class: 'leise', text: 'Alle laufenden Projekte dieses Schuljahres, die du betreust, werden archiviert. Die Team-Links funktionieren dann nicht mehr.' })),
    speichern: async () => (await T.api('POST', '/api/projekte/archivieren-schuljahr', { schuljahr: wahl.value })).anzahl,
  });
  if (ok !== null) { T.meldung(ok + ' Projekte archiviert.'); zeigen(); }
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
  };
  const id = await T.dialog({
    titel: 'Neues Projekt',
    knopf: 'Projekt anlegen',
    inhalt: el('div', { class: 'felder' },
      T.feld('Projekttitel', f.titel),
      el('div', { class: 'felder zwei' }, T.feld('Klasse', f.klasse), T.feld('Schuljahr', f.schuljahr)),
      el('div', { class: 'felder zwei' }, T.feld('Start', f.start, 'zählt ab dem Montag dieser Woche'), T.feld('Ende', f.ende)),
      T.feld('Vorlage', f.vorlage),
      el('p', { class: 'leise klein-text', text: 'Die Namen trägt das Team beim ersten Öffnen des Team-Links selbst ein.' }),
      lehrkraftAuswahl(alle, [S.konto.id])),
    speichern: async form => {
      const { projekt } = await T.api('POST', '/api/projekte', {
        titel: f.titel.value, klasse: f.klasse.value, start: f.start.value, ende: f.ende.value,
        schuljahr: f.schuljahr.value, vorlage: f.vorlage.value,
        lehrkraefte: gewaehlteLehrkraefte(form),
      });
      return projekt.id;
    },
  });
  if (id) { T.meldung('Projekt angelegt.'); location.hash = 'projekt/' + id; }
}

// Projektseite mit Reitern wie in der Team-Ansicht: #projekt/<id>[/<reiter>[/<vorgang>]]
const P_REITER = [['uebersicht', 'Übersicht', 'Start', 'start'], ['sheet', 'Tracking-Sheet', 'Sheet', 'sheet'],
  ['besprechung', 'Besprechung', 'Bespr.', 'bespr'], ['anfragen', 'Anfragen', 'Anfr.', 'anfr'],
  ['projekt', 'Projekt & Team', 'Projekt', 'projekt']];

async function projektZeigen(id, reiter, unter) {
  const [{ projekt: p }] = await Promise.all([T.api('GET', '/api/projekte/' + id), lehrkraefte()]);
  const reiterListe = P_REITER.filter(([k]) => !(p.archiviert && k === 'besprechung'));
  const wahl = reiterListe.some(([k]) => k === reiter) ? reiter : 'uebersicht';
  titelSetzen(p.titel);
  const leiste = T.reiterleiste(reiterListe.map(([k, lang, kurz, symbol]) =>
    ({ schluessel: k, ziel: '#projekt/' + p.id + (k === 'uebersicht' ? '' : '/' + k), lang, kurz, symbol, zahl: k === 'anfragen' })));
  T.reiterAktiv(leiste, wahl);

  const warnOrt = el('div');
  const warnungenZeigen = liste => T.setzen(warnOrt, T.warnungen((liste || []).filter(w => w.stufe !== 'hinweis')));
  warnungenZeigen(p.warnungen);
  const warnungenLaden = async () => {
    try { warnungenZeigen((await T.api('GET', '/api/projekte/' + p.id + '/termine')).warnungen); } catch (e) { /* bleibt */ }
  };
  const ort = el('div', { class: 'stapel' });
  T.setzen(inhalt,
    el('div', { class: 'werkzeug' },
      el('h1', { class: 'dreieck', text: p.titel }),
      el('span', { class: 'chip blau', text: p.klasse }),
      p.archiviert ? el('span', { class: 'chip rot', text: 'archiviert' }) : null,
      el('a', { class: 'knopf', href: '/api/projekte/' + p.id + '/export.xlsx', download: '' }, 'Excel'),
      el('a', { class: 'knopf', href: '/bericht?projekt=' + p.id, target: '_blank', rel: 'noopener' }, 'Bericht (PDF)')),
    leiste, warnOrt, ort);
  T.hoehenMerken();
  Vorgang.projektZahl(leiste, p.id);
  const basis = '/api/projekte/' + p.id;

  if (wahl === 'sheet') {
    Raster.erzeugen({ ort, basis, rolle: 'lehrkraft', beiAenderung: warnungenLaden }).laden();
  } else if (wahl === 'besprechung') {
    await Besprechung.lehrerZeigen(p.id, ort);
  } else if (wahl === 'anfragen') {
    await Vorgang.eingang(unter ? Number(unter) : null, { projektId: p.id, ort, ziel: '#projekt/' + p.id + '/anfragen' });
  } else if (wahl === 'projekt') {
    T.setzen(ort, projektVerwaltung(p), Extras.lehrerKarten(p.id, p.archiviert));
  } else {
    projektUebersicht(p, ort, warnungenZeigen, warnungenLaden);
  }
}

function projektUebersicht(p, ort, warnungenZeigen, warnungenLaden) {
  const namen = p.lehrkraft_ids.map(i => ((S.lehrkraefte || []).find(l => l.id === i) || { name: '?' }).name);
  const aktive = p.mitglieder.filter(m => m.aktiv);
  const ueberblick = el('section', { class: 'karte' },
    el('h2', { class: 'dreieck', text: 'Überblick' }),
    el('dl', { class: 'daten', style: 'margin-top:10px' },
      el('dt', { text: 'Zeitraum' }), el('dd', { text: T.zeitraum(p.start, p.ende) + ' (' + T.tagText(p.start) + ' bis ' + T.tagText(p.ende) + ')' }),
      el('dt', { text: 'Schuljahr' }), el('dd', { text: p.schuljahr }),
      el('dt', { text: 'Betreut von' }), el('dd', { text: namen.join(', ') }),
      el('dt', { text: 'Team' }), el('dd', {}, aktive.length ? aktive.map(m => m.vorname + ' ' + m.nachname + ' (' + m.kuerzel + ')').join(', ')
        : el('a', { href: '#projekt/' + p.id + '/projekt', text: 'noch niemand eingetragen – das Team trägt sich über den Team-Link selbst ein' })),
      p.beschreibung ? [el('dt', { text: 'Beschreibung' }), el('dd', { text: p.beschreibung })] : null));
  const terminOrt = el('div'), wocheOrt = el('div');
  T.setzen(ort, el('div', { class: 'uebersicht' },
    el('div', { class: 'stapel' }, ueberblick,
      p.archiviert ? null : el('section', { class: 'karte' }, el('h2', { class: 'dreieck', text: 'Besprechungstermine' }), terminOrt)),
    el('section', { class: 'karte' }, el('h2', { class: 'dreieck', text: 'Diese Woche' }), wocheOrt)));
  const basis = '/api/projekte/' + p.id;
  Raster.erzeugen({ ort: wocheOrt, basis, rolle: 'lehrkraft', ansicht: 'woche', beiAenderung: warnungenLaden }).laden();
  if (!p.archiviert) Termine.erzeugen({ ort: terminOrt, basis, rolle: 'lehrkraft', beiAenderung: a => warnungenZeigen(a.warnungen) }).laden();
}

function projektVerwaltung(p) {
  // Team-Links ueber HTTP: die Schuelergeraete kennen das Stammzertifikat nicht
  const link = (S.teamPort ? 'http://' + location.hostname + (S.teamPort === 80 ? '' : ':' + S.teamPort) : location.origin) + '/t/' + p.link_token;
  const linkFeld = el('input', { readonly: true, value: link, 'aria-label': 'Team-Link', onfocus: e => e.target.select() });
  const teamlink = el('section', { class: 'karte' },
    el('h2', { class: 'dreieck', text: 'Team-Link' }),
    el('p', { class: 'leise', text: 'Diesen Link im Teams-Chat der Gruppe teilen. Wer ihn hat, kann für das Team eintragen. Erneuern macht den alten Link sofort ungültig.' }),
    el('div', { class: 'link-feld' }, linkFeld,
      el('button', { type: 'button', onclick: () => T.kopieren(link) }, 'Kopieren'),
      el('a', { class: 'knopf', href: link, target: '_blank', rel: 'noopener' }, 'Öffnen'),
      el('button', { type: 'button', class: 'warnen', onclick: () => linkErneuern(p) }, 'Erneuern')));

  const mitglieder = el('section', { class: 'karte' },
    el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: 'Teammitglieder' }),
      el('span', { class: 'rechts' }, el('button', { type: 'button', onclick: () => mitgliedDialog(p) }, '+ Mitglied'))),
    el('p', { class: 'leise klein-text', text: 'Das Team trägt sich selbst ein und darf Schreibweisen korrigieren. Austragen kannst nur du (Bearbeiten → nicht mehr im Team).' }),
    p.mitglieder.length ? el('div', { class: 'rollbar' }, el('table', { class: 'liste' },
      el('thead', {}, el('tr', {}, el('th', { text: 'Kürzel' }), el('th', { text: 'Name' }), el('th', { text: 'Status' }), el('th', {}))),
      el('tbody', {}, p.mitglieder.map(m => el('tr', {},
        el('td', {}, el('span', { class: 'chip', text: m.kuerzel })),
        el('td', { text: m.vorname + ' ' + m.nachname }),
        el('td', {}, m.aktiv ? 'aktiv' : el('span', { class: 'chip rot', text: 'nicht mehr im Team' })),
        el('td', {}, el('button', { type: 'button', class: 'leicht', onclick: () => mitgliedDialog(p, m) }, 'Bearbeiten')))))))
      : el('div', { class: 'leer', text: 'Noch niemand eingetragen. Das Team trägt sich beim ersten Öffnen des Team-Links selbst ein.' }));

  const verwaltung = el('section', { class: 'karte' },
    el('h2', { class: 'dreieck', text: 'Projekt' }),
    el('div', { class: 'zeile', style: 'margin-top:10px' },
      el('button', { type: 'button', onclick: () => projektBearbeiten(p) }, 'Bearbeiten'),
      el('button', { type: 'button', onclick: () => vorlageSpeichern(p) }, 'Als Vorlage'),
      el('button', { type: 'button', class: p.archiviert ? '' : 'warnen', onclick: () => archivieren(p) },
        p.archiviert ? 'Wieder aktivieren' : 'Archivieren'),
      p.archiviert ? el('button', { type: 'button', class: 'warnen', onclick: () => endgueltigLoeschen(p) }, 'Endgültig löschen') : null),
    p.archiviert ? el('p', { class: 'leise', text: 'Archivierte Projekte sind über den Team-Link nicht erreichbar.' }) : null);

  const verlauf = el('section', { class: 'karte' },
    el('h2', { class: 'dreieck', text: 'Verlauf' }),
    el('div', { class: 'verlauf' }, p.verlauf.map(e => el('div', {},
      el('span', { class: 'zeit', text: T.zeitText(e.zeit) }),
      el('span', {}, el('b', { text: T.werText(e) }), ' ', T.verlaufText(e))))));

  return [verwaltung, p.archiviert ? null : teamlink, mitglieder, verlauf];
}

async function vorlageSpeichern(p) {
  const name = el('input', { required: true, maxlength: '80', value: p.titel + ' (Vorlage)' });
  const mitTeam = el('input', { type: 'checkbox' });
  const ok = await T.dialog({
    titel: 'Als Vorlage speichern', knopf: 'Speichern',
    inhalt: el('div', { class: 'felder' }, T.feld('Name der Vorlage', name),
      el('label', { class: 'haken' }, mitTeam, 'auch die Tätigkeiten des Teams übernehmen (sonst nur Phasen und Vorgaben)'),
      el('p', { class: 'leise', text: 'Die Vorlage steht danach beim Anlegen neuer Projekte zur Auswahl.' })),
    speichern: () => T.api('POST', '/api/projekte/' + p.id + '/vorlage', { name: name.value, mit_team: mitTeam.checked }),
  });
  if (ok) { S.vorlagen = null; T.meldung('Vorlage gespeichert.'); }
}

async function endgueltigLoeschen(p) {
  const titel = el('input', { required: true, autocomplete: 'off', placeholder: p.titel });
  const ok = await T.dialog({
    titel: 'Projekt endgültig löschen?', knopf: 'Endgültig löschen', gefaehrlich: true,
    inhalt: el('div', { class: 'felder' },
      el('p', { text: 'Alles zu „' + p.titel + '“ wird gelöscht: Sheet, Verlauf, Besprechungen, Tafeln, Anfragen, Bestelllisten, Fotos und Notizen. ' +
        'Das lässt sich nicht rückgängig machen. Tipp: vorher den Bericht als PDF speichern.' }),
      T.feld('Zur Bestätigung den Projekttitel eintippen', titel)),
    speichern: () => T.api('POST', '/api/projekte/' + p.id + '/loeschen', { bestaetigung: titel.value }),
  });
  if (ok) { T.meldung('Projekt gelöscht.'); location.hash = 'archiv'; }
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
  const d = await T.api('GET', '/api/termine?von=' + S.terminVon + '&wochen=1');
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

  const wochenKarte = el('section', { class: 'karte stapel-eng' },
    el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: 'Besprechungen ' + T.kwText(d.von) }),
      el('span', { class: 'leise', text: T.kurzTag(d.von) + ' bis ' + T.kurzTag(tageSpaeter(d.von, 4)) }),
      el('span', { class: 'rechts' },
        el('button', { type: 'button', title: 'Woche davor', 'aria-label': 'Woche davor', onclick: () => blaettern(-1) }, '‹'),
        el('button', { type: 'button', onclick: () => blaettern(0) }, 'Diese Woche'),
        el('button', { type: 'button', title: 'Woche danach', 'aria-label': 'Woche danach', onclick: () => blaettern(1) }, '›'))),
    regeln.length ? wochenAnsicht(d) : el('div', { class: 'leer', text: 'Ohne Projektzeit gibt es keine Projekttage.' }));

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

// Wochenansicht wie in Outlook: Spalten Mo bis Fr, Uhrzeit von oben nach unten. Nur gebuchte Besprechungen stehen als
// Kaestchen darin; das Besprechungsfenster ist blau hinterlegt, ein Klick auf eine freie Stelle traegt ein Team ein, ein
// Klick auf ein Kaestchen oeffnet das Projekt, verschiebt oder sagt ab. "⋯" am Tageskopf passt den Tag an.
const MIN = u => Number(u.slice(0, 2)) * 60 + Number(u.slice(3, 5));
const UHR = m => String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0');
const PX_JE_MIN = 1.4;

function wochenAnsicht(d) {
  const tageDerWoche = [0, 1, 2, 3, 4].map(i => tageSpaeter(d.von, i));
  const stattfinden = d.tage.filter(t => !t.entfaellt);
  const anfang = stattfinden.length ? Math.floor(Math.min(...stattfinden.map(t => MIN(t.fenster_von))) / 30) * 30 - 30 : 8 * 60;
  const ende = stattfinden.length ? Math.ceil(Math.max(...stattfinden.map(t => MIN(t.fenster_bis))) / 30) * 30 + 30 : 12 * 60;
  const hoehe = (ende - anfang) * PX_JE_MIN, y = u => (MIN(u) - anfang) * PX_JE_MIN;
  const zeiten = [];
  for (let m = anfang; m <= ende; m += 30) zeiten.push(el('span', { style: 'top:' + ((m - anfang) * PX_JE_MIN) + 'px', text: UHR(m) }));

  const kopf = datum => {
    const tage = d.tage.filter(t => t.datum === datum);
    return el('div', { class: 'wg-kopf' + (tage.length ? '' : ' leer') }, el('b', { text: T.kurzTag(datum) }),
      tage.map(t => el('span', { class: 'wg-tag-chip' }, el('span', { class: 'chip blau', text: t.klasse }),
        t.angepasst ? el('span', { class: 'chip', text: 'angepasst' }) : null,
        !t.entfaellt || t.gestrichen ? el('button', { type: 'button', class: 'leicht wg-mehr', title: 'Tag anpassen', 'aria-label': 'Tag ' + T.kurzTag(datum) + ' anpassen',
          onclick: () => tagDialog(t) }, '⋯') : null)));
  };

  const spalte = datum => {
    const tage = d.tage.filter(t => t.datum === datum);
    const s = el('div', { class: 'wg-spalte', style: 'height:' + hoehe + 'px' });
    if (!tage.length) { s.appendChild(el('div', { class: 'wg-hinweis', text: 'kein Projekttag' })); return s; }
    tage.forEach(t => {
      if (t.entfaellt) { s.classList.add('frei'); s.appendChild(el('div', { class: 'wg-hinweis', text: 'entfällt: ' + t.entfaellt })); return; }
      s.appendChild(el('div', { class: 'wg-fenster', title: t.klasse + ' · Besprechungen ' + t.fenster_von + '–' + t.fenster_bis,
        style: 'top:' + y(t.fenster_von) + 'px;height:' + (MIN(t.fenster_bis) - MIN(t.fenster_von)) * PX_JE_MIN + 'px' }));
      t.plaetze.forEach(p => {
        const lage = 'top:' + (y(p.uhrzeit) + 1) + 'px;height:' + Math.max(t.laenge * PX_JE_MIN - 2, 16) + 'px';
        if (p.team) {
          s.appendChild(el('button', { type: 'button', class: 'wg-termin' + (p.von_lehrkraft ? ' lk' : '') + (p.vergangen ? ' vorbei' : ''), style: lage,
            title: p.team + ' · ' + p.uhrzeit + (p.von_lehrkraft ? ' · von Lehrkraft eingetragen' : ''),
            onclick: () => terminDialog(d, t, p) }, el('b', { text: p.uhrzeit }), ' ', p.team));
        } else if (!p.vergangen) {
          s.appendChild(el('button', { type: 'button', class: 'wg-frei', style: lage, 'aria-label': 'frei ' + T.kurzTag(t.datum) + ', ' + p.uhrzeit,
            title: p.uhrzeit + ' frei · Team eintragen', onclick: () => eintragenDialog(t, p) }, el('span', { text: p.uhrzeit + ' frei' })));
        }
      });
    });
    return s;
  };

  // Eine Warnzeile fuer die Woche: Teams ohne Termin (aus allen Projekttagen), dazu die Buchungsschluesse
  const ohne = [...new Map(d.tage.flatMap(t => t.ohne_termin).map(x => [x.id, x])).values()];
  const schluss = [...new Set(stattfinden.map(t => T.kurzTag(t.schluss) + ', ' + t.schluss.slice(11, 16)))];
  return el('div', { class: 'stapel-eng' },
    el('div', { class: 'rollbar' }, el('div', { class: 'woche-gitter' },
      el('div', { class: 'wg-kopf ecke' }), tageDerWoche.map(kopf),
      el('div', { class: 'wg-zeit', style: 'height:' + hoehe + 'px' }, zeiten), tageDerWoche.map(spalte))),
    ohne.length ? el('div', { class: 'banner w' }, el('b', { text: 'Noch ohne Termin in ' + T.kwText(d.von) + ': ' }), ohne.map(x => x.titel).join(', '),
      schluss.length ? el('span', { class: 'leise', text: ' · Buchungsschluss ' + schluss.join(' und ') }) : null)
      : stattfinden.length ? el('div', { class: 'leise klein-text', text: 'Alle Teams haben einen Termin.' }) : null,
    el('div', { class: 'kal-leg leise klein-text' },
      el('span', {}, el('span', { class: 'wg-termin muster' }, 'Kästchen'), ' gebuchte Besprechung: Klick öffnet, verschiebt oder sagt ab'),
      el('span', {}, el('span', { class: 'wg-fenster muster' }), ' Besprechungsfenster: Klick auf eine freie Zeit trägt ein Team ein'),
      el('span', { text: '⋯ am Tageskopf: Tag anpassen oder streichen' })));
}

async function eintragenDialog(t, p) {
  if (!t.ohne_termin.length) { T.meldung(t.projekte ? 'Alle Teams dieser Klasse haben schon einen Termin. Ein Kästchen anklicken zum Verschieben.' : 'Du betreust kein Projekt dieser Klasse.', true); return; }
  const wahl = el('select', { required: true }, el('option', { value: '', text: 'Team wählen' }), t.ohne_termin.map(x => el('option', { value: String(x.id), text: x.titel })));
  const ok = await T.dialog({ titel: T.kurzTag(t.datum) + ', ' + p.uhrzeit + ' · Team eintragen', knopf: 'Eintragen',
    inhalt: el('div', { class: 'felder' }, T.feld('Team', wahl, 'Teams dieser Klasse, die in dieser Woche noch keinen Termin haben')),
    speichern: () => T.api('POST', '/api/projekte/' + wahl.value + '/termin', { regel_id: t.regel_id, datum: t.datum, uhrzeit: p.uhrzeit }) });
  if (ok) { T.meldung('Eingetragen.'); zeigen(); }
}

async function terminDialog(d, t, p) {
  // freie Zeiten derselben Klasse in dieser Woche zum Verschieben
  const frei = d.tage.filter(x => !x.entfaellt && x.klasse === t.klasse).flatMap(x => x.plaetze.filter(q => !q.team && !q.vergangen)
    .map(q => ({ wert: x.regel_id + '|' + x.datum + '|' + q.uhrzeit, text: T.kurzTag(x.datum) + ', ' + q.uhrzeit })));
  const ziel = el('select', {}, el('option', { value: '', text: frei.length ? 'nicht verschieben' : 'keine freie Zeit in dieser Woche' }),
    frei.map(f => el('option', { value: f.wert, text: f.text })));
  const r = await T.dialog({ titel: p.team + ' · ' + T.kurzTag(t.datum) + ', ' + p.uhrzeit, knopf: 'Verschieben',
    inhalt: el('div', { class: 'felder' },
      el('div', { class: 'zeile' }, el('a', { class: 'knopf', href: '#projekt/' + p.projekt_id }, 'Projekt öffnen'),
        el('button', { type: 'button', class: 'warnen', onclick: async ev => {
          ev.target.closest('dialog').querySelector('[value=nein]').click();
          try {
            await T.api('POST', '/api/projekte/' + p.projekt_id + '/termin', { stornieren: true, woche: t.woche });
            T.meldung('Termin abgesagt.'); zeigen();
          } catch (e) { T.meldung(e.message, true); }
        } }, 'Termin absagen')),
      p.von_lehrkraft ? el('p', { class: 'leise klein-text', text: 'Von einer Lehrkraft eingetragen.' }) : null,
      T.feld('Verschieben auf', ziel)),
    speichern: async () => {
      if (!ziel.value) return null;
      const [regel, datum, uhrzeit] = ziel.value.split('|');
      await T.api('POST', '/api/projekte/' + p.projekt_id + '/termin', { regel_id: Number(regel), datum, uhrzeit });
      return true;
    } });
  if (r) { T.meldung('Verschoben.'); zeigen(); }
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
  const [einst, { vorlagen }] = await Promise.all([T.api('GET', '/api/einstellungen'), T.api('GET', '/api/vorlagen')]);
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
    Cockpit.schulKarte(einst),
    el('section', { class: 'karte stapel-eng' },
      el('h2', { class: 'dreieck', text: 'Projektvorlagen' }),
      el('p', { class: 'leise', text: 'Eigene Vorlagen entstehen auf der Projektseite mit „Als Vorlage“. Die mitgelieferten Vorlagen bleiben immer.' }),
      vorlagen.map(v => el('div', { class: 'zeile' }, el('span', { text: v.name }),
        v.schluessel.startsWith('eigen-') ? el('button', { type: 'button', class: 'leicht', onclick: async () => {
          try { await T.api('POST', '/api/vorlagen/' + v.schluessel + '/entfernen', {}); S.vorlagen = null; T.meldung('Vorlage entfernt.'); zeigen(); }
          catch (e) { T.meldung(e.message, true); }
        } }, 'Entfernen') : el('span', { class: 'chip', text: 'mitgeliefert' })))),
    updateKarte(),
    vpnKarte(),
    el('section', { class: 'karte stapel-eng' },
      el('h2', { class: 'dreieck', text: 'Sicherung' }),
      el('p', { class: 'leise', text: 'ZIP mit Datenbank, Fotos, Mindmaps und Logo (ohne Zertifikate). Zusätzlich sichert Proxmox den ganzen Container. ' +
        'Die ZIP enthält personenbezogene Daten: sicher aufbewahren.' }),
      el('div', {}, el('a', { class: 'knopf haupt', href: '/api/sicherung.zip', download: '' }, 'Sicherung herunterladen'))));
}

// --- Version und Update (nur Admins) ---
// Pruefen und Installieren laufen als root ueber systemd (deploy/selbstupdate.sh); die Seite legt nur eine Anfrage ab
// und liest das Ergebnis. Waehrend des Updates startet der Dienst neu: die Karte fragt weiter, bis er wieder antwortet.

function updateMarke() {
  const link = document.querySelector('nav.seite a[data-ansicht="einstellungen"]');
  if (!link) return;
  let b = link.querySelector('.nav-zahl');
  if (!b) { b = el('span', { class: 'nav-zahl neu' }); link.appendChild(b); }
  b.textContent = S.update ? '1' : '';
  b.hidden = !S.update;
  b.title = S.update ? 'Neue Version ' + (S.update.version || '') + ' verfügbar' : '';
}

function updateKarte() {
  const ort = el('section', { class: 'karte stapel-eng update-karte' });
  let timer = null, beobachten = false;
  const kopf = () => el('h2', { class: 'dreieck', text: 'Version und Update' });
  const weiter = () => { clearTimeout(timer); timer = setTimeout(() => { if (ort.isConnected) laden(); }, 3000); };
  const anfordern = async aktion => {
    try { zeichnen(await T.api('POST', '/api/update', { aktion })); weiter(); }
    catch (e) { T.meldung(e.message, true); }
  };

  async function laden() {
    let u;
    try { u = await T.api('GET', '/api/update'); } catch (e) {
      if (beobachten) { T.setzen(ort, kopf(), el('p', { class: 'update-laeuft', text: 'Der Dienst startet neu … gleich geht es weiter.' })); weiter(); return; }
      T.setzen(ort, kopf(), el('div', { class: 'leer', text: e.message }));
      return;
    }
    if (u.laeuft || u.wartet.ausfuehren) beobachten = true;
    else if (beobachten && u.lauf && u.lauf.ende) {
      beobachten = false;
      if (u.lauf.ergebnis === 'ok') { T.meldung('Update fertig: Version ' + u.version + '. Die Seite lädt neu.'); setTimeout(() => location.reload(), 1500); }
      else T.meldung('Das Update hat nicht geklappt. Details im Protokoll.', true);
    }
    zeichnen(u);
    if (u.laeuft || u.wartet.ausfuehren || u.wartet.pruefen) weiter();
  }

  async function aktualisieren(pr) {
    const ok = await T.dialog({
      titel: 'Auf Version ' + (pr.verfuegbar.version || pr.verfuegbar.stand) + ' aktualisieren?', knopf: 'Jetzt aktualisieren',
      inhalt: el('div', { class: 'felder' },
        el('p', { text: 'Vorher wird automatisch eine Sicherung angelegt. Während der Installation ist die Seite etwa eine Minute nicht ' +
          'erreichbar, auch für die Teams. Am besten außerhalb des Unterrichts.' })),
      speichern: () => true,
    });
    if (ok) { beobachten = true; anfordern('ausfuehren'); }
  }

  function zeichnen(u) {
    const pr = u.pruefung;
    const pruefKnopf = el('button', { type: 'button', disabled: u.wartet.pruefen || u.laeuft || !u.eingerichtet,
      onclick: () => anfordern('pruefen') }, u.wartet.pruefen ? 'Prüfe …' : 'Jetzt prüfen');
    let status;
    if (!u.eingerichtet) {
      status = el('p', { class: 'leise', text: 'Das Update über diese Seite ist eingerichtet, sobald diese Version einmal über die Konsole ' +
        'installiert wurde (trackingdrs-update). Hier läuft es gerade ohne Container.' });
    } else if (u.laeuft || u.wartet.ausfuehren) {
      status = el('div', { class: 'stapel-eng' }, el('p', { class: 'update-laeuft', text: 'Update läuft: Sicherung, Installation, Neustart …' }),
        u.protokoll ? el('pre', { class: 'update-protokoll', text: u.protokoll }) : null);
    } else if (pr && pr.fehler) {
      status = el('div', { class: 'stapel-eng' }, el('span', { class: 'chip rot', text: 'Prüfung fehlgeschlagen' }),
        el('pre', { class: 'update-protokoll', text: pr.fehler }));
    } else if (pr && pr.neu) {
      status = el('div', { class: 'stapel-eng update-neu' },
        el('div', { class: 'zeile' }, el('b', { text: 'Neue Version ' + (pr.verfuegbar.version || '') + ' verfügbar' }),
          el('span', { class: 'leise', text: pr.neu === 1 ? '1 Änderung' : pr.neu + ' Änderungen' }),
          el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'haupt', onclick: () => aktualisieren(pr) }, 'Jetzt aktualisieren'))),
        el('ul', { class: 'update-liste' }, pr.aenderungen.map(a => el('li', {}, el('span', { class: 'mono leise', text: a.stand }), ' ', a.text))),
        pr.neu > pr.aenderungen.length ? el('div', { class: 'leise klein-text', text: '… und ' + (pr.neu - pr.aenderungen.length) + ' ältere' }) : null);
    } else if (pr) {
      status = el('div', { class: 'zeile' }, el('span', { class: 'chip gruen', text: '✓ aktuell' }), el('span', { class: 'leise', text: 'Es gibt keine neuere Version.' }));
    } else {
      status = el('p', { class: 'leise', text: 'Noch nicht geprüft.' });
    }
    const lauf = u.lauf && u.lauf.ende ? u.lauf : null;
    T.setzen(ort, kopf(),
      el('dl', { class: 'daten' },
        el('dt', { text: 'Installiert' }), el('dd', { text: u.version + (pr && pr.installiert.stand ? ' (' + pr.installiert.stand + ')' : '') }),
        el('dt', { text: 'Geprüft' }), el('dd', { text: pr ? T.zeitText(pr.zeit) + ' · täglich automatisch' : '–' }),
        pr && pr.quelle ? [el('dt', { text: 'Quelle' }), el('dd', { class: 'mono klein-text', text: pr.quelle })] : null),
      status,
      el('div', { class: 'zeile' }, pruefKnopf),
      lauf ? el('details', {}, el('summary', { text: 'Letztes Update: ' + T.zeitText(lauf.ende) + (lauf.ergebnis === 'ok' ? ' · erfolgreich' : ' · fehlgeschlagen') }),
        el('pre', { class: 'update-protokoll', text: u.protokoll || '(kein Protokoll)' })) : null,
      u.sicherungen.length ? el('details', {}, el('summary', { text: 'Sicherungen vor Updates (' + u.sicherungen.length + ', die letzten 5 bleiben)' }),
        el('div', { class: 'stapel-eng' }, u.sicherungen.map(sg => el('a', { href: '/api/update/sicherung/' + sg.name, download: '' },
          sg.name + ' · ' + Math.round(sg.groesse / 1024) + ' KB')))) : null);
    if (S.update && pr && !pr.neu) { S.update = null; updateMarke(); }
  }

  laden();
  return ort;
}

// --- VPN (nur Admins) ---
// Einrichten, pruefen und ausschalten laufen als root ueber systemd (deploy/vpn.sh "anfrage"); die Seite legt nur einen
// Auftrag ab und liest das Ergebnis. Beim ersten Einrichten startet der Dienst neu (Zertifikat mit der VPN-Adresse):
// die Karte fragt weiter, bis er wieder antwortet. Fuer den VPS zeigt sie Peer-Block und Befehle zum Kopieren.
// Einen privaten Schluessel nimmt die Seite nie an: der des Containers entsteht im Container, der des Servers bleibt dort.

const VPN_STATUS = {
  dicht: ['gruen', '✓ Sperre wirkt', 'Über das VPN erreicht der Container weder den Server noch dein Heimnetz.'],
  offen: ['rot', 'Sperre fehlt', 'Der Container erreicht über das VPN andere Geräte. Auf dem VPS die Sperre setzen (Schritt 2).'],
  keine_verbindung: ['', 'Keine Verbindung', 'Beim letzten Test stand keine Verbindung zum Server. Ist der Container auf dem VPS eingetragen (Schritt 1)?'],
  aus: ['', 'VPN aus', 'Die VPN-Verbindung ist ausgeschaltet.'],
};

function vorlage(titel, text, hilfe) {
  return el('div', { class: 'vorlage stapel-eng' },
    el('div', { class: 'zeile' }, el('b', { text: titel }),
      el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'leicht', onclick: () => T.kopieren(text) }, 'Kopieren'))),
    hilfe ? el('p', { class: 'leise klein-text', text: hilfe }) : null,
    el('pre', { class: 'vorlage-text', text }));
}

function vpnBefehle(e) {
  const wg = e.server_if || 'wg0', datei = '/etc/wireguard/' + wg + '.conf';
  const peer = ['[Peer]', '# TrackingDRS ' + (e.name || '') + ': nur diese eine Adresse', 'PublicKey = ' + e.container_schluessel,
    e.psk ? '# PresharedKey = derselbe wie in der Client-Datei (gehört auch hier hinein)' : null,
    'AllowedIPs = ' + e.adresse + '/32'].filter(Boolean).join('\n');
  const eintragen = 'sudo tee -a ' + datei + " >/dev/null <<'EOF'\n\n" + peer + '\nEOF\n' +
    "sudo bash -c 'wg syncconf " + wg + ' <(wg-quick strip ' + wg + ")'";
  const sperre = 'curl -fsSLO https://raw.githubusercontent.com/mgoebel89/TrackingDRS/main/vps/sperre.sh\n' +
    'sudo bash sperre.sh einrichten ' + e.adresse;
  const kontrolle = 'sudo wg show ' + wg + '\nsudo bash sperre.sh status';
  return el('div', { class: 'stapel-eng' },
    vorlage('Erweiterung für deine Server-Config', peer, 'Dieser Block gehört in ' + datei + ' auf dem VPS. Schritt 1 trägt ihn für dich ein.'),
    el('h3', { text: 'Auf dem VPS (per SSH als Benutzer mit sudo)' }),
    el('ol', { class: 'vpn-schritte' },
      el('li', {}, vorlage('Container eintragen und übernehmen', eintragen,
        (e.aus_datei ? 'Hast du die Client-Datei auf dem VPS erzeugt, steht der Container dort schon: dann diesen Schritt auslassen. ' : '') +
        'Hängt den Block an die Server-Config an und übernimmt ihn, ohne bestehende Verbindungen zu trennen. Steht der Container ' +
        'schon in der Datei (z. B. nach „Neu einrichten“), den alten Block vorher löschen: sudo nano ' + datei + '. Steht dort ' +
        '„SaveConfig = true“: erst sudo wg-quick down ' + wg + ', dann eintragen, dann sudo wg-quick up ' + wg + '.')),
      el('li', {}, vorlage('Sperre setzen (einmalig)', sperre,
        'Danach erreicht der Container über das VPN weder den Server noch dein Heimnetz. Frei ist nur HTTPS zum Container. ' +
        'Ohne öffentliches Repo: vps/sperre.sh per scp auf den VPS kopieren und nur die zweite Zeile ausführen.')),
      el('li', {}, vorlage('Kontrollieren', kontrolle,
        'Beim Peer des Containers steht „latest handshake: … seconds ago“, bei der Sperre zählen die drop-Zähler. ' +
        'Dann hier „Verbindung prüfen“.'))));
}

function vpnFormular(e) {
  e = e || {};
  const m = (e.server || '').match(/^\[?(.*?)\]?:(\d+)$/);
  const f = {
    host: el('input', { required: true, value: m ? m[1] : '', placeholder: 'z. B. 203.0.113.5 oder vpn.example.de', autocomplete: 'off' }),
    port: el('input', { type: 'number', min: '1', max: '65535', required: true, value: m ? m[2] : '51820' }),
    schluessel: el('input', { required: true, value: e.server_schluessel || '', maxlength: '60', class: 'mono', autocomplete: 'off',
      spellcheck: 'false', placeholder: '44 Zeichen, endet auf =' }),
    adresse: el('input', { required: true, value: e.adresse || '10.8.0.20', autocomplete: 'off' }),
    server_ip: el('input', { value: e.server_ip || '', placeholder: 'leer = erste Adresse im VPN-Netz (z. B. 10.8.0.1)', autocomplete: 'off' }),
    netze: el('input', { value: (e.netze || []).join(' '), placeholder: 'leer = das Netz der VPN-Adresse (/24)', autocomplete: 'off' }),
    alle: el('input', { type: 'checkbox', checked: e.alle === undefined ? true : !!e.alle }),
    server_if: el('input', { required: true, value: e.server_if || 'wg0', maxlength: '15', autocomplete: 'off' }),
    passwort: el('input', { type: 'password', required: true, autocomplete: 'current-password' }),
    conf: el('textarea', { rows: '11', required: true, class: 'mono vpn-conf', spellcheck: 'false', autocomplete: 'off',
      placeholder: '[Interface]\nPrivateKey = …\nAddress = 10.8.0.20/24\n\n[Peer]\nPublicKey = …\nEndpoint = 203.0.113.5:51820\nAllowedIPs = 10.8.0.0/24' }),
  };
  const datei = el('input', { type: 'file', accept: '.conf,text/plain', onchange: async () => {
    const d = datei.files[0];
    if (!d) return;
    if (d.size > 4000) { T.meldung('Die Datei ist zu groß für eine WireGuard-Config.', true); return; }
    f.conf.value = await d.text();
  } });
  const ohneRahmen = 'border:0;padding:0;margin:0;min-width:0';
  const werte = el('fieldset', { class: 'felder', style: ohneRahmen },
    el('p', { class: 'leise', text: 'Die Angaben stehen in der WireGuard-Config deines VPS. Einen privaten Schlüssel brauchst du ' +
      'hier nicht: Der Container erzeugt seinen eigenen, und der des Servers bleibt auf dem Server.' }),
    el('div', { class: 'felder zwei' },
      T.feld('Öffentliche IP oder Name des VPS', f.host),
      T.feld('Port', f.port, 'ListenPort in der Server-Config')),
    T.feld('Öffentlicher Schlüssel des Servers', f.schluessel, 'auf dem VPS: sudo wg show ' + (e.server_if || 'wg0') + ' public-key'),
    el('div', { class: 'felder zwei' },
      T.feld('VPN-Adresse des Containers', f.adresse, 'frei, bei keinem [Peer] unter AllowedIPs'),
      T.feld('VPN-Adresse des Servers', f.server_ip, 'Address unter [Interface]')),
    T.feld('VPN-Netz', f.netze, 'z. B. 10.8.0.0/24. Dein Heimnetz gehört nicht hierher, dafür ist der Schalter unten.'));
  const ausDatei = el('fieldset', { class: 'felder', style: ohneRahmen },
    el('p', { class: 'leise', text: 'Eine WireGuard-Datei, die du für den Container geschrieben hast: [Interface] mit PrivateKey und ' +
      'Address, [Peer] mit dem Server. Nimm nicht die Datei deines Handys, jedes Gerät braucht eigene Schlüssel. Der private ' +
      'Schlüssel darin gehört dem Container: Er geht verschlüsselt an den Container, liegt danach nur in /etc/wireguard und wird ' +
      'nie wieder angezeigt. AllowedIPs 0.0.0.0/0 heißt hier „Alle Teilnehmer meines VPN“: Der Container leitet dafür nichts um. ' +
      'DNS übernimmt er nicht.' }),
    T.feld('Datei wählen', datei),
    T.feld('… oder den Inhalt hier einfügen', f.conf));
  const umschalter = el('div', { class: 'umschalter' });
  let modus;
  const wechseln = m => {
    modus = m;
    werte.disabled = werte.hidden = m !== 'werte';
    ausDatei.disabled = ausDatei.hidden = m !== 'datei';
    T.setzen(umschalter, [['werte', 'Werte eingeben'], ['datei', 'Config-Datei']].map(([k, t]) =>
      el('button', { type: 'button', class: k === m ? 'an' : '', onclick: () => wechseln(k) }, t)));
  };
  wechseln(e.aus_datei ? 'datei' : 'werte');
  return T.dialog({
    titel: e.adresse ? 'VPN neu einrichten' : 'VPN einrichten', knopf: 'Einrichten',
    inhalt: el('div', { class: 'felder' },
      umschalter, werte, ausDatei,
      el('label', { class: 'haken' }, f.alle, el('span', {}, el('b', { text: 'Alle Teilnehmer meines VPN' }),
        el('span', { class: 'leise klein-text', style: 'display:block', text: 'Jedes Gerät im VPN und in deinem Heimnetz hinter dem VPN ' +
          'erreicht den Lehrerbereich (nur HTTPS), auch wenn das Heimnetz dieselben 192.168er-Adressen wie das Schulnetz hat. Der ' +
          'Container selbst erreicht dein Heimnetz weiterhin nicht.' }))),
      T.feld('Schnittstelle auf dem VPS', f.server_if, 'Dateiname in /etc/wireguard ohne .conf (nur für die Befehle zum Kopieren)'),
      el('p', { class: 'warnung-text', text: 'Liegt die VPN-Adresse außerhalb von 192.168.x.x, entsteht einmalig ein neues ' +
        'Stammzertifikat. Die Seite ist dann kurz weg, und alle Geräte brauchen das neue Stammzertifikat.' }),
      T.feld('Dein Passwort zur Bestätigung', f.passwort)),
    speichern: () => T.api('POST', '/api/vpn', modus === 'datei'
      ? { aktion: 'einrichten', conf: f.conf.value, server_if: f.server_if.value, alle: f.alle.checked, passwort: f.passwort.value }
      : { aktion: 'einrichten', server: f.host.value, port: f.port.value, schluessel: f.schluessel.value, adresse: f.adresse.value,
        server_ip: f.server_ip.value, netze: f.netze.value, server_if: f.server_if.value, alle: f.alle.checked, passwort: f.passwort.value }),
  });
}

function vpnKarte() {
  const ort = el('section', { class: 'karte stapel-eng vpn-karte' });
  let timer = null, beobachten = false, versuche = 0;
  const kopf = () => el('h2', { class: 'dreieck', text: 'VPN (Zugriff von zuhause)' });
  const weiter = () => { clearTimeout(timer); timer = setTimeout(() => { if (ort.isConnected) laden(); }, 2500); };
  const gestartet = v => { beobachten = true; versuche = 0; zeichnen(v); weiter(); };
  const auftrag = async (aktion, passwort) => {
    try { gestartet(await T.api('POST', '/api/vpn', { aktion, passwort })); } catch (e) { T.meldung(e.message, true); }
  };
  const ausschalten = async () => {
    const pw = el('input', { type: 'password', required: true, autocomplete: 'current-password' });
    const v = await T.dialog({
      titel: 'VPN ausschalten?', knopf: 'Ausschalten', gefaehrlich: true,
      inhalt: el('div', { class: 'felder' },
        el('p', { text: 'Von zuhause ist der Container dann nicht mehr erreichbar. Schlüssel und Config bleiben, „Wieder einschalten“ ' +
          'genügt. Den Block auf dem VPS kannst du stehen lassen oder löschen.' }),
        T.feld('Dein Passwort zur Bestätigung', pw)),
      speichern: () => T.api('POST', '/api/vpn', { aktion: 'aus', passwort: pw.value }),
    });
    if (v) gestartet(v);
  };

  async function laden() {
    let v;
    try { v = await T.api('GET', '/api/vpn'); } catch (e) {
      if (beobachten && ++versuche < 40) {
        T.setzen(ort, kopf(), el('p', { class: 'update-laeuft', text: 'Der Dienst startet neu (Zertifikat mit der VPN-Adresse) … gleich geht es weiter.' }),
          versuche > 8 ? el('p', { class: 'leise', text: 'Dauert es länger? Dann ist das Stammzertifikat neu und der Browser traut der ' +
            'Seite noch nicht: Seite neu laden, das neue Stammzertifikat über http://<Container>/ca.crt installieren.' }) : null);
        weiter();
        return;
      }
      T.setzen(ort, kopf(), el('div', { class: 'leer', text: e.message }));
      return;
    }
    if (v.laeuft || v.wartet) beobachten = true;
    else if (beobachten && v.lauf && v.lauf.ende) {
      beobachten = false;
      T.meldung(v.lauf.ergebnis === 'ok' ? 'VPN: erledigt.' : 'VPN: Das hat nicht geklappt. Details im Protokoll.', v.lauf.ergebnis !== 'ok');
    }
    zeichnen(v);
    if (v.laeuft || v.wartet) weiter();
  }

  function zeichnen(v) {
    const e = v.einrichtung, t = v.sperrtest, laeuft = v.laeuft || v.wartet, gesperrt = laeuft || !v.eingerichtet;
    S.vpn = t;
    const knopf = (text, klick, klasse) => el('button', { type: 'button', class: klasse || '', disabled: gesperrt, onclick: klick }, text);
    const einrichten = async () => {
      const r = await vpnFormular(e);
      if (!r) return;
      gestartet(r);
      if (r.hinweise && r.hinweise.length) T.meldung('Aus der Datei: ' + r.hinweise.join(' '));
    };
    let status = null;
    if (e && !e.aktiv) status = el('div', { class: 'zeile' }, el('span', { class: 'chip', text: 'VPN aus' }));
    else if (e && t) {
      const [farbe, chip, text] = VPN_STATUS[t.ergebnis] || ['', t.ergebnis, ''];
      status = el('div', { class: 'stapel-eng' },
        el('div', { class: 'zeile' }, el('span', { class: 'chip ' + farbe, text: chip }), el('span', { class: 'leise', text })),
        t.durch.length ? el('ul', { class: 'update-liste' }, t.durch.map(d => el('li', { class: 'mono', text: d }))) : null,
        t.alt ? el('p', { class: 'warnung-text', text: 'Seit mehr als drei Tagen kein Sperrtest. Läuft der Timer? „Verbindung prüfen“ testet sofort.' }) : null);
    }
    const lauf = v.lauf && v.lauf.ende ? v.lauf : null;
    T.setzen(ort, kopf(),
      !v.eingerichtet ? el('p', { class: 'leise', text: 'Das Einrichten über diese Seite geht, sobald diese Version einmal über die ' +
        'Konsole installiert wurde (trackingdrs-update). Hier läuft es gerade ohne Container.' }) : null,
      laeuft ? el('div', { class: 'stapel-eng' }, el('p', { class: 'update-laeuft', text: 'Auftrag läuft …' }),
        v.protokoll ? el('pre', { class: 'update-protokoll', text: v.protokoll }) : null) : null,
      !e ? el('p', { class: 'leise', text: 'Der Container wird Teilnehmer in deinem WireGuard-VPN. Von zuhause ist dann nur diese Seite ' +
        'über HTTPS erreichbar, sonst nichts im Schulnetz. Du gibst die Daten deines VPS ein und bekommst die Erweiterung für die ' +
        'Server-Config und die Befehle für den VPS zum Kopieren.' }) : null,
      status,
      e ? el('dl', { class: 'daten' },
        el('dt', { text: 'Adresse' }), el('dd', {}, el('span', { class: 'mono', text: e.adresse }), e.aktiv ? [' · ',
          el('a', { href: 'https://' + e.adresse + '/', target: '_blank', rel: 'noopener', text: 'https://' + e.adresse }), ' (von zuhause)'] : null),
        el('dt', { text: 'Server' }), el('dd', { class: 'mono', text: e.server || '–' }),
        el('dt', { text: 'Erreichbar für' }), el('dd', { text: e.alle ? 'alle Teilnehmer deines VPN, auch dein Heimnetz' :
          'nur Geräte mit einer Adresse im VPN-Netz ' + (e.netze || []).join(', ') }),
        t ? [el('dt', { text: 'Getestet' }), el('dd', { text: T.zeitText(t.zeit) + ' · täglich automatisch' })] : null,
        t && t.ziele.length ? [el('dt', { text: 'Versucht' }), el('dd', { class: 'mono klein-text', text: t.ziele.join(', ') })] : null) : null,
      el('div', { class: 'zeile' },
        !e ? knopf('VPN einrichten', einrichten, 'haupt') : e.aktiv
          ? [knopf('Verbindung prüfen', () => auftrag('sperrtest'), 'haupt'), knopf('Neu einrichten', einrichten), knopf('VPN aus', ausschalten, 'warnen')]
          : [knopf('Wieder einschalten', einrichten, 'haupt')],
        e ? el('a', { class: 'knopf leicht', href: '/ca.crt', download: '' }, 'Stammzertifikat') : null),
      e && e.aktiv ? vpnBefehle(e) : null,
      e ? el('details', {}, el('summary', { text: 'Config des Containers (/etc/wireguard/wg0.conf)' }),
        vorlage('wg0.conf', e.konf, 'Ist im Container schon aktiv. Der private Schlüssel liegt getrennt in /etc/wireguard/trackingdrs.key ' +
          'und wird nie angezeigt.')) : null,
      lauf ? el('details', {}, el('summary', { text: 'Letzter Auftrag: ' + T.zeitText(lauf.ende) + ' · ' + lauf.aktion +
        (lauf.ergebnis === 'ok' ? ' · erledigt' : ' · fehlgeschlagen') }),
        el('pre', { class: 'update-protokoll', text: v.protokoll || '(kein Protokoll)' })) : null);
  }

  laden();
  return ort;
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
