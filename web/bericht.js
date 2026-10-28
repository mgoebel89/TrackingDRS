// Projektbericht (/bericht?projekt=<id>, Lehrkraft): Raster, Meilensteine, Probleme, Besprechungen mit eingefrorenen
// Tafeln, Anfragen, Bestelllisten, Fotos und Verlauf als Druckansicht (im Browser "Als PDF speichern", z. B. fuer Moodle).
// Lehrernotizen nur, wenn ausdruecklich gewaehlt.
'use strict';

(async () => {
  const el = T.el;
  const ort = document.getElementById('bericht');
  const such = new URLSearchParams(location.search);
  const pid = Number(such.get('projekt'));
  const mitNotizen = such.get('notizen') === '1';
  const basis = '/api/projekte/' + pid;
  const AMPEL = { g: 'grün', y: 'gelb', r: 'rot' };
  const ARTEN = { rueckfrage: 'Rückfrage', ausleihe: 'Ausleihe', abnahme: 'Abnahme' };
  let B;
  try { B = (await T.api('GET', basis + '/bericht' + (mitNotizen ? '?notizen=1' : ''))).bericht; }
  catch (e) {
    if (e.status === 401) { location.replace('/anmelden'); return; }
    T.setzen(ort, el('div', { class: 'leer', text: e.message }));
    return;
  }
  const p = B.projekt, s = B.sheet;
  document.title = 'Projektbericht · ' + p.titel;
  const kuerzel = Object.fromEntries(s.mitglieder.map(m => [m.id, m.kuerzel]));
  const abschnitt = (titel, ...inhalt) => el('section', { class: 'b-abschnitt' }, el('h2', { class: 'dreieck', text: titel }), inhalt);
  const datum = text => text ? text.slice(8, 10) + '.' + text.slice(5, 7) + '.' + text.slice(0, 4) : '';

  function raster() {
    const W = s.wochen;
    const frei = new Set(s.projektwochen ? W.filter(w => !s.projektwochen.includes(w)) : []);
    const gesamt = {};
    const zeilen = [];
    for (const ph of s.phasen) {
      zeilen.push(el('tr', { class: 'b-phase' }, el('td', { colspan: String(W.length + 2), text: ph.name })));
      for (const a of ph.aufgaben) {
        zeilen.push(el('tr', { class: a.verworfen ? 'b-verworfen' : '' },
          el('td', { class: 'b-name', text: (a.erledigt ? '✓ ' : '') + a.titel }),
          el('td', { text: kuerzel[a.verantwortlich_id] || '' }),
          W.map(w => {
            const amp = a.ampel[w];
            if (amp && !a.verworfen && (!gesamt[w] || 'gyr'.indexOf(amp) > 'gyr'.indexOf(gesamt[w]))) gesamt[w] = amp;
            const klasse = amp ? 'b-' + amp : a.plan.includes(w) ? 'b-plan' : frei.has(w) ? 'b-frei' : '';
            return el('td', { class: 'b-w ' + klasse, text: a.ende === w ? 'e' : '' });
          })));
      }
    }
    zeilen.push(el('tr', { class: 'b-summe' }, el('td', { class: 'b-name', text: 'Meilensteine' }), el('td', {}),
      W.map(w => el('td', { class: 'b-w b-ms', text: s.meilensteine.some(m => !m.verworfen && m.woche === w) ? '◆' : '' }))));
    zeilen.push(el('tr', { class: 'b-summe' }, el('td', { class: 'b-name', text: 'Gesamtstatus' }), el('td', {}),
      W.map(w => el('td', { class: 'b-w ' + (gesamt[w] ? 'b-' + gesamt[w] : '') }))));
    return el('table', { class: 'b-raster' },
      el('thead', {}, el('tr', {}, el('th', { text: 'Aufgabe' }), el('th', { text: 'V.' }), W.map(w => el('th', { text: String(T.kw(T.datum(w))) })))),
      el('tbody', {}, zeilen));
  }

  function liste(eintraege, f) { return eintraege.length ? el('ul', { class: 'b-liste' }, eintraege.map(e => el('li', {}, f(e)))) : el('p', { class: 'leise', text: '–' }); }

  const protokolle = B.protokolle.slice().reverse().map(pr => {
    const rahmen = pr.tafel_daten ? el('div', { class: 'b-tafel tafel-rahmen' }) : null;
    const teil = abschnitt('Besprechung ' + T.kwText(pr.woche) + (pr.termin ? ' · ' + T.kurzTag(pr.termin.datum) + ', ' + pr.termin.uhrzeit : ''),
      pr.vorbereitung ? [el('h3', { text: 'Stand des Teams' }), el('p', { class: 'vortext', text: pr.vorbereitung })] : null,
      el('h3', { text: 'Ergebnis' }),
      liste((pr.ergebnis || []), e => e.art === 'absprache' ? 'Absprache: ' + e.text
        : e.art === 'auftrag' ? 'Auftrag: ' + e.text + ' (bis ' + datum(e.frist) + (e.verantwortlich ? ', ' + e.verantwortlich : '') + ')' +
          (e.erledigt ? ' – erledigt ' + T.zeitText(e.erledigt) : '')
          : 'Meilenstein: ' + e.text + (e.frist ? ' (' + T.kwText(e.frist) + ')' : '')),
      (pr.geklaert || []).length ? [el('h3', { text: 'Geklärt' }), liste(pr.geklaert, e => e.text)] : null,
      rahmen ? [el('h3', { text: 'Tafel' }), rahmen] : null,
      mitNotizen && pr.notizen ? [el('h3', { text: 'Lehrernotizen' }), el('p', { class: 'vortext', text: pr.notizen })] : null,
      el('p', { class: 'leise', text: 'abgeschlossen ' + T.zeitText(pr.abgeschlossen) + (pr.von ? ' von ' + pr.von.toUpperCase() : '') }));
    return { teil, rahmen, daten: pr.tafel_daten };
  });

  const team = p.mitglieder.filter(m => m.aktiv).map(m => m.vorname + ' ' + m.nachname + ' (' + m.kuerzel + ')').join(', ');
  T.setzen(ort,
    el('div', { class: 'b-leiste' },
      el('label', { class: 'haken' }, el('input', { type: 'checkbox', checked: mitNotizen, onchange: ev => {
        such.set('notizen', ev.target.checked ? '1' : '0'); location.search = such.toString(); } }), 'mit Lehrernotizen (nicht für Moodle)'),
      el('button', { type: 'button', class: 'haupt', onclick: () => window.print() }, 'Drucken / Als PDF speichern')),
    el('header', { class: 'b-kopf' },
      el('img', { class: 'b-logo', src: '/logo', alt: '', onerror: ev => ev.target.remove() }),
      el('div', {}, el('h1', { text: 'Projektbericht · ' + p.titel }),
        el('div', { text: 'Klasse ' + p.klasse + ' · Schuljahr ' + p.schuljahr + ' · ' + T.zeitraum(p.start, p.ende) }),
        el('div', { text: 'Team: ' + (team || '–') }),
        el('div', { class: 'leise', text: 'Stand ' + new Date().toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' }) }))),
    abschnitt('Tracking-Sheet', raster(),
      el('p', { class: 'leise', text: 'blau = geplante Woche, e = Endtermin, grün/gelb/rot = Ampel, ◆ = Meilenstein, schraffiert = kein Projekttag, ✓ = erledigt' })),
    abschnitt('Meilensteine', liste(s.meilensteine.filter(m => !m.verworfen), m => T.kwText(m.woche) + ': ' + m.titel)),
    abschnitt('Probleme und Korrekturmaßnahmen', B.probleme.length ? el('table', { class: 'b-tabelle' },
      el('thead', {}, el('tr', {}, ['KW', 'Aufgabe', 'Ampel', 'Problem', 'Maßnahme', 'V.'].map(t => el('th', { text: t })))),
      el('tbody', {}, B.probleme.map(pr => el('tr', {}, el('td', { text: String(T.kw(T.datum(pr.woche))) }), el('td', { text: pr.aufgabe || '' }),
        el('td', { class: 'b-' + pr.ampel, text: AMPEL[pr.ampel] }), el('td', { text: pr.problem }), el('td', { text: pr.massnahme }),
        el('td', { text: pr.verantwortlich || '' })))))
      : el('p', { class: 'leise', text: 'Keine Probleme eingetragen.' })),
    protokolle.length ? protokolle.map(x => x.teil) : abschnitt('Besprechungen', el('p', { class: 'leise', text: 'Noch keine abgeschlossene Besprechung.' })),
    abschnitt('Anfragen', liste(B.anfragen, a => ARTEN[a.art] + ': ' + a.titel + ' – ' + a.status + (a.antwort ? ' (' + a.antwort + ')' : '') +
      ' · ' + T.zeitText(a.erstellt))),
    abschnitt('Bestelllisten', B.bestellung.length ? B.bestellung.map(l => el('div', {},
      el('h3', { text: 'Liste vom ' + T.zeitText(l.eingereicht) }),
      liste(l.positionen.filter(x => !x.gestrichen), x => (x.menge_genehmigt || x.menge) + '× ' + x.artikel + (x.bestellnr ? ' (' + x.bestellnr + ')' : '') +
        ' – ' + (x.entscheidung ? ({ bestellen: 'wird bestellt', lager: 'SchulLager', firma: 'über Firma',
          ersetzen: x.ersatz_artikel ? 'ersetzt durch ' + x.ersatz_artikel : 'Ersatz gesucht', ablehnen: 'abgelehnt' })[x.entscheidung] +
          (x.status ? ', ' + x.status : '') : 'in Prüfung'))))
      : el('p', { class: 'leise', text: 'Keine eingereichten Listen.' })),
    B.mindmap && B.mindmap.typ !== 'application/pdf' ? abschnitt('Mindmap', el('img', { class: 'b-mindmap', src: basis + '/bild/' + B.mindmap.name, alt: 'Mindmap' })) : null,
    B.fotos.length ? abschnitt('Fotos', el('div', { class: 'b-fotos' }, B.fotos.map(f => el('figure', {},
      el('img', { src: basis + '/bild/' + f.name, alt: f.titel || 'Foto' }), el('figcaption', { text: (f.titel || 'Foto') + ' · ' + T.zeitText(f.erstellt) }))))) : null,
    mitNotizen && B.notizen && B.notizen.length ? abschnitt('Lehrernotizen', liste(B.notizen, n => [el('b', { text: (n.art === 'besprechung' ? 'Besprechung ' +
      T.kwText(n.woche) : T.zeitText(n.erstellt) + ' ' + n.wer.toUpperCase()) + ': ' }), n.text])) : null,
    abschnitt('Verlauf', el('table', { class: 'b-tabelle b-verlauf' }, el('tbody', {}, p.verlauf.slice().reverse().map(e => el('tr', {},
      el('td', { text: T.zeitText(e.zeit) }), el('td', { text: T.werText(e) }), el('td', { text: T.verlaufText(e) })))))));
  for (const x of protokolle) if (x.rahmen) Tafel.einbetten(x.rahmen, x.daten, basis);
})();
