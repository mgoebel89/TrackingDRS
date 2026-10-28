// Team-Ansicht ueber den geheimen Link /t/<token>: Diese Woche (Handy), Tracking-Sheet, Termin, Projekt.
// Ueber den Reitern stehen die Warnungen und Hinweise (Termin buchen, Ampeln setzen, Endtermine).
'use strict';
const { el } = T;
const inhalt = document.getElementById('inhalt');
const token = location.pathname.split('/')[2] || '';
const basis = '/api/t/' + encodeURIComponent(token);
const REITER = [['woche', 'Diese Woche'], ['sheet', 'Tracking-Sheet'], ['termin', 'Termin'], ['projekt', 'Projekt']];
let projekt = null;
let raster = null;
const bereich = el('div', { class: 'stapel' });
const hinweise = el('div', { hidden: true });

function warnungenZeigen(liste) {
  T.setzen(hinweise, T.warnungen(liste));
  hinweise.hidden = !(liste && liste.length);
}

async function warnungenLaden() {
  try { warnungenZeigen((await T.api('GET', basis + '/termine')).warnungen); } catch (e) { /* zeigt der Reiter */ }
}

function reiterWahl() {
  const h = location.hash.slice(1);
  if (REITER.some(([k]) => k === h)) return h;
  return window.matchMedia('(max-width: 760px)').matches ? 'woche' : 'sheet';
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
  if (wahl === 'termin') {
    const ort = el('div');
    T.setzen(bereich, ort);
    Termine.erzeugen({ ort, basis, rolle: 'team', beiAenderung: warnungenZeigen }).laden();
    return;
  }
  if (!raster || !bereich.contains(raster.ort)) {
    const ort = el('div');
    T.setzen(bereich, ort);
    raster = Raster.erzeugen({ ort, basis, rolle: 'team', ansicht: wahl === 'woche' ? 'woche' : 'raster', beiAenderung: warnungenLaden });
    raster.ort = ort;
    raster.laden();
  } else {
    raster.ansicht(wahl === 'woche' ? 'woche' : 'raster');
  }
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
  warnungenLaden();
}

start();
