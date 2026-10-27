// Lehrerbereich: Projekte, Projektseite mit Team-Link und Teammitgliedern, Lehrkraefte (Admin), eigenes Konto.
'use strict';
const { el } = T;
const S = { konto: null, lehrkraefte: null, vorlagen: null };
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
  document.title = text ? text + ' · TrackingDRS' : 'TrackingDRS';
}

function fehlerZeigen(e) {
  if (e.status === 401) { location.replace('/anmelden'); return; }
  T.leeren(inhalt).appendChild(el('div', { class: 'leer', text: e.message }));
}

// --- Start und Navigation ---

async function start() {
  try {
    S.konto = (await T.api('GET', '/api/ich')).konto;
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
  const [ansicht, id] = (location.hash.slice(1) || 'projekte').split('/');
  const nav = ansicht === 'projekt' ? 'projekte' : ansicht;
  document.querySelectorAll('nav.seite a').forEach(a => a.classList.toggle('an', a.dataset.ansicht === nav));
  try {
    if (ansicht === 'projekte') await projekteZeigen(false);
    else if (ansicht === 'archiv') await projekteZeigen(true);
    else if (ansicht === 'projekt') await projektZeigen(Number(id));
    else if (ansicht === 'lehrkraefte') await lehrkraefteZeigen();
    else if (ansicht === 'konto') kontoZeigen();
    else if (ansicht === 'einstellungen') await einstellungenZeigen();
    else location.hash = 'projekte';
  } catch (e) { fehlerZeigen(e); }
}

// --- Projekte ---

function projektkarte(p) {
  return el('a', { class: 'karte projektkarte', href: '#projekt/' + p.id },
    el('div', { class: 'zeile' }, el('span', { class: 'chip blau', text: p.klasse }), el('span', { class: 'leise', text: p.schuljahr })),
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
  const link = location.origin + '/t/' + p.link_token;
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
      el('button', { type: 'button', onclick: () => projektBearbeiten(p) }, 'Bearbeiten'),
      el('button', { type: 'button', class: p.archiviert ? '' : 'warnen', onclick: () => archivieren(p) },
        p.archiviert ? 'Wieder aktivieren' : 'Archivieren')),
    ueberblick, struktur, p.archiviert ? null : teamlink, mitglieder, verlauf);
  Raster.erzeugen({ ort: sheetOrt, basis: '/api/projekte/' + p.id, rolle: 'lehrkraft' }).laden();
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
  const { logo } = await T.api('GET', '/api/einstellungen');
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
        logo ? el('button', { type: 'button', class: 'warnen', onclick: entfernen }, 'Logo entfernen') : null)));
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

function kontoZeigen() {
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
}

start();
