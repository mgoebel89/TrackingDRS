// Team-Ansicht ueber den geheimen Link /t/<token>: Uebersicht (Startseite), Tracking-Sheet, Projekt.
// Uebersicht = Hinweise, Besprechungstermin der aktuellen Woche (buchen), Ampeln dieser Woche und "Demnaechst"
// (entfallende Projekttage, Meilensteine, Endtermine). Ueber dem Inhalt stehen die Warnungen und Hinweise.
'use strict';
const { el } = T;
const inhalt = document.getElementById('inhalt');
const token = location.pathname.split('/')[2] || '';
const basis = '/api/t/' + encodeURIComponent(token);
const REITER = [['uebersicht', 'Übersicht'], ['sheet', 'Tracking-Sheet'], ['projekt', 'Projekt']];
const U = { sheet: null, entfallen: [] };   // was "Demnaechst" braucht
let projekt = null;
const bereich = el('div', { class: 'stapel' });
const hinweise = el('div', { hidden: true });
const demOrt = el('div');

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
      el('h2', { class: 'dreieck', text: 'Team' }),
      p.mitglieder.length ? el('div', { class: 'zeile' }, p.mitglieder.map(m => el('span', { class: 'chip', title: m.kuerzel },
        m.vorname + ' ' + m.nachname + ' · ' + m.kuerzel))) : el('p', { class: 'leise', text: 'Noch keine Teammitglieder eingetragen.' })),
    p.beschreibung ? el('section', { class: 'karte' }, el('h2', { class: 'dreieck', text: 'Projektbeschreibung' }), el('p', { text: p.beschreibung })) : null,
    el('section', { class: 'karte' }, el('h2', { class: 'dreieck', text: 'Betreuung' }),
      el('p', { text: p.lehrkraefte.map(l => l.name + ' (' + l.kuerzel + ')').join(', ') })),
  ];
}

function zeigen() {
  const wahl = reiterWahl();
  document.querySelectorAll('.reiter a').forEach(a => a.classList.toggle('an', a.dataset.reiter === wahl));
  inhalt.classList.toggle('breit', wahl === 'sheet');
  if (wahl === 'projekt') { T.setzen(bereich, projektSeite(projekt)); return; }
  if (wahl === 'uebersicht') { uebersicht(); return; }
  const ort = el('div');
  T.setzen(bereich, ort);
  Raster.erzeugen({ ort, basis, rolle: 'team', ansicht: 'raster', beiAenderung: warnungenLaden }).laden();
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
  document.title = projekt.titel + ' · TrackingDRS';
  T.setzen(inhalt,
    el('div', { class: 'team-kopf' },
      el('div', { class: 'zeile' }, el('span', { class: 'chip blau', text: projekt.klasse }), el('span', { class: 'leise', text: projekt.schuljahr })),
      el('h1', { class: 'dreieck', text: projekt.titel }),
      el('div', { class: 'leise', text: T.zeitraum(projekt.start, projekt.ende) + ' · betreut von ' + projekt.lehrkraefte.map(l => l.name).join(', ') })),
    el('nav', { class: 'reiter', 'aria-label': 'Bereiche' },
      REITER.map(([k, t]) => el('a', { href: '#' + k, 'data-reiter': k, text: t })),
      ['Anfragen', 'Besprechungen'].map(t => el('span', { class: 'spaeter', title: 'folgt in einer der nächsten Stufen', text: t }))),
    hinweise, bereich);
  window.addEventListener('hashchange', zeigen);
  zeigen();
  if (reiterWahl() !== 'uebersicht') warnungenLaden();
}

start();
