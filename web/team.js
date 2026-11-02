// Team-Ansicht ueber den geheimen Link /t/<token>: Uebersicht (Startseite), Tracking-Sheet, Besprechung, Anfragen,
// Projekt.
// Uebersicht = Hinweise, Besprechungstermin der aktuellen Woche (buchen), Ampeln dieser Woche und "Demnaechst"
// (entfallende Projekttage, Meilensteine, Endtermine). Ueber dem Inhalt stehen die Warnungen und Hinweise.
// Die Reiter sind eine eigene Leiste mit Symbolen, die beim Scrollen oben bleibt (am Handy unten); neue Antworten der
// Lehrkraft zeigt ein roter Zaehler an "Anfragen", die Zahl im Browser-Tab und eine kurze Einblendung.
// Beim ersten Oeffnen traegt sich das Team selbst ein ("Wer ist im Team?"); vorher gibt es nichts anderes.
'use strict';
const { el } = T;
const inhalt = document.getElementById('inhalt');
const token = location.pathname.split('/')[2] || '';
const basis = '/api/t/' + encodeURIComponent(token);
const REITER = [['uebersicht', 'Übersicht', 'Start', 'start'], ['sheet', 'Tracking-Sheet', 'Sheet', 'sheet'],
  ['besprechung', 'Besprechung', 'Bespr.', 'bespr'], ['anfragen', 'Anfragen', 'Anfr.', 'anfr'], ['fotos', 'Fotos', 'Fotos', 'fotos'],
  ['projekt', 'Projekt', 'Projekt', 'projekt']];
const U = { sheet: null, entfallen: [] };   // was "Demnaechst" braucht
let projekt = null;
const bereich = el('div', { class: 'stapel' });
const hinweise = el('div', { hidden: true });
const demOrt = el('div');
let zaehlerAbfragen = () => {};
let leiste = null;

function zaehlerZeigen(z) {
  T.reiterZahl(leiste, z.ungelesen, z.ungelesen === 1 ? '1 neue Antwort' : z.ungelesen + ' neue Antworten');
  T.titelZahl(z.ungelesen);
}

function namenFelder(m) {
  return {
    vorname: el('input', { required: true, maxlength: '60', autocomplete: 'off', placeholder: 'Vorname', 'aria-label': 'Vorname', value: m ? m.vorname : null }),
    nachname: el('input', { required: true, maxlength: '60', autocomplete: 'off', placeholder: 'Nachname', 'aria-label': 'Nachname', value: m ? m.nachname : null }),
  };
}

// Erster Besuch: Solange niemand eingetragen ist, gibt es nur "Wer ist im Team?". Liefert das Projekt danach.
function eintragen() {
  return new Promise(fertig => {
    const zeilen = el('div', { class: 'stapel-eng' });
    const fehler = el('div', { class: 'fehlertext', role: 'alert' });
    const zeile = () => {
      const f = namenFelder();
      f.vorname.required = f.nachname.required = false;
      zeilen.appendChild(el('div', { class: 'felder zwei name-zeile' }, f.vorname, f.nachname));
      return f.vorname;
    };
    [1, 2, 3].forEach(zeile);
    const form = el('form', { class: 'karte stapel eintragen', onsubmit: async ev => {
      ev.preventDefault();
      const mitglieder = [...zeilen.querySelectorAll('.name-zeile')].map(z => ({ vorname: z.children[0].value.trim(), nachname: z.children[1].value.trim() }))
        .filter(m => m.vorname || m.nachname);
      try { fertig((await T.api('POST', basis + '/mitglieder', { mitglieder })).projekt); }
      catch (e) { fehler.textContent = e.message; }
    } },
      el('h2', { class: 'dreieck', text: 'Wer ist im Team?' }),
      el('p', { text: 'Bevor es losgeht: Tragt bitte alle Teammitglieder mit Vor- und Nachnamen ein. Daraus entstehen eure Kürzel im ' +
        'Tracking-Sheet. Wer fehlt, kann später unter „Projekt“ nachgetragen werden.' }),
      zeilen, fehler,
      el('div', { class: 'zeile' }, el('button', { type: 'button', class: 'leicht', onclick: () => zeile().focus() }, '+ Weitere Person'),
        el('span', { class: 'rechts' }, el('button', { type: 'submit', class: 'haupt' }, 'Eintragen und loslegen'))));
    T.setzen(inhalt, teamKopf(), form);
    zeilen.querySelector('input').focus();
  });
}

async function mitgliedDialog(m) {
  const f = namenFelder(m);
  const r = await T.dialog({
    titel: m ? 'Schreibweise korrigieren' : 'Person nachtragen', knopf: m ? 'Speichern' : 'Eintragen',
    inhalt: el('div', { class: 'felder' }, el('div', { class: 'felder zwei' }, T.feld('Vorname', f.vorname), T.feld('Nachname', f.nachname)),
      m ? el('p', { class: 'leise klein-text', text: 'Wer nicht mehr im Team ist, trägt die Lehrkraft aus.' }) : null),
    speichern: () => T.api('POST', basis + '/mitglieder' + (m ? '/' + m.id : ''),
      m ? { vorname: f.vorname.value, nachname: f.nachname.value } : { mitglieder: [{ vorname: f.vorname.value, nachname: f.nachname.value }] }),
  });
  if (r) { projekt = r.projekt; T.meldung('Gespeichert.'); zeigen(); }
}

function nachAenderung() { warnungenLaden(); zaehlerAbfragen(); }

function warnungenZeigen(liste) {
  T.setzen(hinweise, T.warnungen(liste));
  hinweise.hidden = !(liste && liste.length);
}

function termineGeladen(antwort) {
  warnungenZeigen(antwort.warnungen);
  U.entfallen = antwort.entfallen || [];
  demnaechst();
}

async function warnungenLaden() {
  try { termineGeladen(await T.api('GET', basis + '/termine')); } catch (e) { /* zeigt die Uebersicht */ }
}

function reiterWahl() {
  const h = location.hash.slice(1);
  return REITER.some(([k]) => k === h) ? h : 'uebersicht';
}

function plusTage(text, n) { const d = T.datum(text); d.setDate(d.getDate() + n); return T.isoDatum(d); }

// Was in den naechsten zwei Wochen ansteht: entfallende Projekttage, Meilensteine, Endtermine
function demnaechst() {
  const s = U.sheet;
  if (!s) return;
  const jetzt = s.jetzt, naechste = plusTage(jetzt, 7);
  const kuerzel = id => (s.mitglieder.find(m => m.id === id) || {}).kuerzel;
  const ms = s.meilensteine.filter(m => !m.verworfen && m.woche >= jetzt).slice(0, 2);
  const enden = s.phasen.flatMap(p => p.aufgaben)
    .filter(a => !a.verworfen && !a.erledigt && a.ende && a.ende >= jetzt && a.ende <= naechste)
    .sort((a, b) => a.ende.localeCompare(b.ende));
  const gruppe = (titel, zeilen) => zeilen.length ? el('div', { class: 'dem-gruppe' }, el('div', { class: 'etikett', text: titel }), zeilen) : null;
  const teile = [
    gruppe('Projekttage entfallen', U.entfallen.map(t => el('div', { class: 'dem entfall' },
      el('span', { class: 'dem-m', text: '✕' }), el('b', { text: T.kurzTag(t.datum) }), ' entfällt: ' + t.grund))),
    gruppe('Meilensteine', ms.map(m => el('div', { class: 'dem' },
      el('span', { class: 'dem-m ms', text: '◆' }), m.titel, el('span', { class: 'leise', text: ' · ' + T.kwText(m.woche) })))),
    gruppe('Endtermine', enden.map(a => el('div', { class: 'dem' },
      el('span', { class: 'e-m', text: 'e' }), a.titel,
      el('span', { class: 'leise', text: ' · ' + T.kwText(a.ende) + (a.verantwortlich_id ? ' · ' + kuerzel(a.verantwortlich_id) : '') })))),
  ].filter(Boolean);
  T.setzen(demOrt, teile.length ? teile : el('p', { class: 'leise', text: 'In den nächsten zwei Wochen steht nichts Besonderes an.' }));
}

function uebersicht() {
  const terminOrt = el('div'), ampelOrt = el('div');
  T.setzen(bereich, el('div', { class: 'uebersicht' },
    el('div', { class: 'stapel' },
      el('section', { class: 'karte' }, el('h2', { class: 'dreieck', text: 'Besprechungstermin' }), terminOrt),
      el('section', { class: 'karte' }, el('h2', { class: 'dreieck', text: 'Demnächst' }), demOrt)),
    el('section', { class: 'karte' }, el('h2', { class: 'dreieck', text: 'Diese Woche' }), ampelOrt)));
  Termine.erzeugen({ ort: terminOrt, basis, rolle: 'team', beiAenderung: termineGeladen }).laden();
  Raster.erzeugen({ ort: ampelOrt, basis, rolle: 'team', ansicht: 'woche', beiAenderung: warnungenLaden,
    beiLaden: sheet => { U.sheet = sheet; demnaechst(); } }).laden();
}

function projektSeite(p) {
  return [
    el('section', { class: 'karte' },
      el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: 'Team' }),
        el('span', { class: 'rechts' }, el('button', { type: 'button', onclick: () => mitgliedDialog() }, '+ Person nachtragen'))),
      p.mitglieder.length ? el('div', { class: 'zeile' }, p.mitglieder.map(m => el('button', { type: 'button', class: 'chip team-name',
        title: 'Schreibweise korrigieren', onclick: () => mitgliedDialog(m) }, m.vorname + ' ' + m.nachname + ' · ' + m.kuerzel, ' ✎')))
        : el('p', { class: 'leise', text: 'Noch keine Teammitglieder eingetragen.' })),
    p.beschreibung ? el('section', { class: 'karte' }, el('h2', { class: 'dreieck', text: 'Projektbeschreibung' }), el('p', { text: p.beschreibung })) : null,
    el('section', { class: 'karte' }, el('h2', { class: 'dreieck', text: 'Betreuung' }),
      el('p', { text: p.lehrkraefte.map(l => l.name + ' (' + l.kuerzel + ')').join(', ') })),
  ];
}

function zeigen() {
  const wahl = reiterWahl();
  T.reiterAktiv(leiste, wahl);
  inhalt.classList.toggle('breit', wahl === 'sheet');
  if (wahl === 'projekt') {
    const seite = projektSeite(projekt);
    T.setzen(bereich, seite);
    Extras.teamMindmap(basis).then(k => { if (k && bereich.contains(seite[0])) bereich.insertBefore(k, bereich.firstChild); });
    return;
  }
  if (wahl === 'fotos') {
    const ort = el('div');
    T.setzen(bereich, ort);
    Extras.teamFotos({ ort, basis, aufgaben: projekt.phasen.flatMap(ph => ph.aufgaben).filter(a => !a.verworfen).map(a => ({ id: a.id, titel: a.titel })) });
    return;
  }
  if (wahl === 'uebersicht') { uebersicht(); return; }
  if (wahl === 'besprechung') {
    const ort = el('div');
    T.setzen(bereich, ort);
    Besprechung.teamErzeugen({ ort, basis, beiAenderung: warnungenLaden }).laden();
    return;
  }
  if (wahl === 'anfragen') {
    const ort = el('div');
    T.setzen(bereich, ort);
    Anfragen.teamErzeugen({ ort, basis, beiAenderung: nachAenderung }).laden();
    return;
  }
  const ort = el('div');
  T.setzen(bereich, ort);
  Raster.erzeugen({ ort, basis, rolle: 'team', ansicht: 'raster', beiAenderung: warnungenLaden }).laden();
}

function teamKopf() {
  return el('div', { class: 'team-kopf' },
    el('div', { class: 'zeile' }, el('span', { class: 'chip blau', text: projekt.klasse }), el('span', { class: 'leise', text: projekt.schuljahr })),
    el('h1', { class: 'dreieck', text: projekt.titel }),
    el('div', { class: 'leise', text: T.zeitraum(projekt.start, projekt.ende) + ' · betreut von ' + projekt.lehrkraefte.map(l => l.name).join(', ') }));
}

async function start() {
  try {
    projekt = (await T.api('GET', basis)).projekt;
  } catch (e) {
    T.setzen(inhalt, el('div', { class: 'karte' },
      el('h1', { class: 'dreieck', text: 'Link nicht gültig' }),
      el('p', { text: e.message })));
    return;
  }
  document.getElementById('unter').textContent = projekt.titel;
  T.titel(projekt.titel);
  if (!projekt.mitglieder.length) projekt = await eintragen();
  leiste = T.reiterleiste(REITER.map(([k, lang, kurz, symbol]) => ({ schluessel: k, ziel: '#' + k, lang, kurz, symbol, zahl: k === 'anfragen' })));
  T.setzen(inhalt, teamKopf(), leiste, hinweise, bereich);
  T.hoehenMerken();
  window.addEventListener('resize', T.hoehenMerken);
  window.addEventListener('hashchange', zeigen);
  zaehlerAbfragen = T.beobachten(async () => { const z = await T.api('GET', basis + '/zaehler'); zaehlerZeigen(z); return z; },
    v => T.meldung('Neue Antwort der Lehrkraft zu „' + v.titel + '“: ' + v.text, false, '#anfragen'));
  zeigen();
  if (reiterWahl() !== 'uebersicht') warnungenLaden();
}

start();
