// Team-Ansicht ueber den geheimen Link /t/<token>. Stufe A: Projekt, Team, Phasen; das Tracking-Sheet folgt in Stufe B.
'use strict';
const { el } = T;
const inhalt = document.getElementById('inhalt');
const token = location.pathname.split('/')[2] || '';

async function start() {
  let p;
  try {
    p = (await T.api('GET', '/api/t/' + encodeURIComponent(token))).projekt;
  } catch (e) {
    T.setzen(inhalt, el('div', { class: 'karte' },
      el('h1', { class: 'dreieck', text: 'Link nicht gültig' }),
      el('p', { text: e.message })));
    return;
  }
  document.getElementById('unter').textContent = p.titel;
  document.title = p.titel + ' · TrackingDRS';

  T.setzen(inhalt, 
    el('div', { class: 'team-kopf' },
      el('div', { class: 'zeile' }, el('span', { class: 'chip blau', text: p.klasse }), el('span', { class: 'leise', text: p.schuljahr })),
      el('h1', { class: 'dreieck', text: p.titel }),
      el('div', { class: 'leise', text: T.zeitraum(p.start, p.ende) + ' · betreut von ' + p.lehrkraefte.map(l => l.name).join(', ') })),
    el('nav', { class: 'reiter', 'aria-label': 'Bereiche' },
      el('span', { class: 'an', text: 'Projekt' }),
      ['Tracking-Sheet', 'Termin', 'Anfragen', 'Besprechungen'].map(t => el('span', { class: 'spaeter', title: 'folgt in einer der nächsten Stufen', text: t }))),
    el('section', { class: 'karte' },
      el('h2', { class: 'dreieck', text: 'Team' }),
      p.mitglieder.length ? el('div', { class: 'zeile' }, p.mitglieder.map(m => el('span', { class: 'chip', title: m.kuerzel },
        m.vorname + ' ' + m.nachname))) : el('p', { class: 'leise', text: 'Noch keine Teammitglieder eingetragen.' })),
    p.beschreibung ? el('section', { class: 'karte' }, el('h2', { class: 'dreieck', text: 'Projektbeschreibung' }), el('p', { text: p.beschreibung })) : null,
    el('section', { class: 'karte' },
      el('h2', { class: 'dreieck', text: 'Phasen' }),
      el('p', { class: 'leise', text: 'Hier entsteht euer Tracking-Sheet. Die Bearbeitung kommt mit der nächsten Ausbaustufe.' }),
      p.phasen.map(ph => el('div', { class: 'phase' },
        el('div', { class: 'etikett', text: ph.name }),
        ph.aufgaben.length ? el('ul', {}, ph.aufgaben.map(a => el('li', { text: a.titel })))
          : el('div', { class: 'leise', text: 'noch keine Aufgaben' })))));
}

start();
