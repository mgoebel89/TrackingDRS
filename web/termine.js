// Besprechungstermine eines Projekts buchen: Team (Uebersicht, Buchungsfenster "Termin buchen") und Lehrkraft (Projektseite).
// Je Woche ein Termin. Das Team bucht und bucht um bis zum Buchungsschluss des Tages und sieht fremde Termine nur als
// "belegt"; die Lehrkraft sieht, wer gebucht hat, und darf jederzeit aendern.
'use strict';

const Termine = (() => {
  const { el } = T;

  function erzeugen({ ort, basis, rolle, beiAenderung }) {
    const S = { daten: null };
    const lehrkraft = rolle === 'lehrkraft';
    const ihr = lehrkraft ? 'Termin des Teams' : 'Euer Termin';

    async function laden() {
      try {
        const antwort = await T.api('GET', basis + '/termine');
        S.daten = antwort.termine;
        zeichnen();
        if (beiAenderung) beiAenderung(antwort);
      } catch (e) { T.setzen(ort, el('div', { class: 'leer', text: e.message })); }
    }

    async function senden(daten, meldung) {
      try {
        const antwort = await T.api('POST', basis + '/termin', daten);
        S.daten = antwort.termine;
        zeichnen();
        T.meldung(meldung);
        if (beiAenderung) beiAenderung(antwort);
      } catch (e) { T.meldung(e.message, true); laden(); }
    }

    async function buchen(w, tag, platz) {
      const ziel = T.kurzTag(tag.datum) + ', ' + platz.uhrzeit;
      const b = w.buchung;
      if (b) {
        const ok = await T.dialog({
          titel: 'Termin umbuchen?', knopf: 'Umbuchen',
          inhalt: el('p', { text: 'Von ' + T.kurzTag(b.datum) + ', ' + b.uhrzeit + ' auf ' + ziel + '. Der bisherige Termin wird frei.' }),
        });
        if (!ok) return;
      }
      senden({ regel_id: tag.regel_id, datum: tag.datum, uhrzeit: platz.uhrzeit }, (b ? 'Umgebucht: ' : 'Gebucht: ') + ziel);
    }

    async function absagen(w) {
      const b = w.buchung;
      const ok = await T.dialog({
        titel: 'Termin absagen?', knopf: 'Absagen', gefaehrlich: true,
        inhalt: el('p', { text: T.kurzTag(b.datum) + ', ' + b.uhrzeit + ' wird wieder frei. ' +
          (lehrkraft ? '' : 'Ohne Termin gibt es ab dem Buchungsschluss eine Warnung.') }),
      });
      if (ok) senden({ stornieren: true, woche: w.woche }, 'Termin abgesagt.');
    }

    function platzKnopf(w, tag, p) {
      const text = p.status === 'eigen' ? '✓ ' + (lehrkraft ? (p.team || 'gebucht') : 'euer Termin')
        : p.status === 'belegt' ? (lehrkraft && p.team ? p.team : 'belegt') : 'frei';
      return el('button', {
        type: 'button', class: 'platz ' + p.status, disabled: !p.buchbar,
        title: p.buchbar ? (w.buchung ? 'hierhin umbuchen' : 'buchen') : '',
        onclick: () => buchen(w, tag, p) }, el('span', { class: 'mono', text: p.uhrzeit }), el('span', { text }));
    }

    function woche(w) {
      const b = w.buchung;
      const status = b ? el('span', { class: 'chip blau', text: '✓ gebucht' })
        : w.schluss > S.daten.jetzt ? el('span', { class: 'chip', text: 'noch offen' }) : el('span', { class: 'chip rot', text: 'kein Termin' });
      return el('div', { class: 'termin-woche' + (lehrkraft ? ' karte' : '') },
        el('div', { class: 'zeile' }, el('h3', { text: T.kwText(w.woche) }), status,
          el('span', { class: 'leise', text: 'Buchungsschluss ' + T.zeitpunkt(w.schluss) })),
        b ? el('div', { class: 'banner' }, ihr + ': ', el('b', { text: T.kurzTag(b.datum) + ', ' + b.uhrzeit }),
          w.fest ? ' · steht fest' : lehrkraft ? '' : ' · umbuchen bis ' + T.zeitpunkt(w.schluss),
          (lehrkraft || !w.fest) ? el('button', { type: 'button', class: 'leicht', onclick: () => absagen(w) }, 'Absagen') : null) : null,
        w.tage.map(tag => el('div', { class: 'termin-tag' },
          el('div', { class: 'zeile' }, el('b', { text: T.kurzTag(tag.datum) }),
            el('span', { class: 'leise', text: 'Projektzeit ' + tag.von + '–' + tag.bis + ' · ' + tag.lehrkraft }),
            tag.offen || lehrkraft ? null : el('span', { class: 'chip', text: 'Buchung geschlossen' })),
          el('div', { class: 'plaetze' }, tag.plaetze.map(p => platzKnopf(w, tag, p))))));
    }

    // Team: der eigene Termin oder "Termin buchen"; gebucht wird in einem kleinen Fenster (am Handy von unten), das
    // erst die Projekttage der Woche und dann nur die freien Zeiten des gewaehlten Tags zeigt
    function teamKompakt(w) {
      const b = w.buchung;
      const frei = t => t.plaetze.filter(p => p.buchbar);
      const buchbar = w.tage.some(t => frei(t).length);
      if (b) {
        return el('div', { class: 'banner termin-banner' }, 'Euer Termin: ', el('b', { text: T.kurzTag(b.datum) + ', ' + b.uhrzeit + ' Uhr' }),
          w.fest ? el('span', { class: 'leise', text: ' · steht fest' })
            : [el('span', { class: 'leise', text: ' · ändern bis ' + T.zeitpunkt(w.schluss) }),
              el('span', { class: 'rechts' }, buchbar ? el('button', { type: 'button', onclick: () => blatt(w) }, 'Ändern') : null,
                el('button', { type: 'button', class: 'leicht', onclick: () => absagen(w) }, 'Absagen'))]);
      }
      return el('div', { class: 'banner w termin-banner' }, el('b', { text: 'Noch kein Termin für ' + T.kwText(w.woche) + '.' }),
        buchbar ? el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'haupt', onclick: () => blatt(w) }, 'Termin buchen'))
          : el('span', { class: 'leise', text: ' Der Buchungsschluss ist vorbei, bitte die Lehrkraft fragen.' }));
    }

    function blatt(w) {
      const frei = t => t.plaetze.filter(p => p.buchbar);
      let tag = w.tage.find(t => frei(t).length) || w.tage[0];
      const d = el('dialog', { class: 'blatt-dialog' });
      const zu = () => { d.close(); d.remove(); };
      const inhalt = el('div', { class: 'stapel-eng' });
      function zeichnenBlatt() {
        T.setzen(inhalt,
          el('div', { class: 'etikett', text: 'Tag' }),
          el('div', { class: 'tag-wahl' }, w.tage.map(t => el('button', { type: 'button', class: t === tag ? 'an' : '', disabled: !frei(t).length,
            onclick: () => { tag = t; zeichnenBlatt(); } }, T.kurzTag(t.datum),
          el('small', { text: frei(t).length ? (frei(t).length === 1 ? '1 frei' : frei(t).length + ' frei') : t.offen ? 'voll' : 'geschlossen' })))),
          el('div', { class: 'etikett', text: 'Noch frei am ' + T.kurzTag(tag.datum) }),
          frei(tag).length ? el('div', { class: 'frei-zeiten' }, frei(tag).map(p => el('button', { type: 'button', onclick: () => {
            zu();
            senden({ regel_id: tag.regel_id, datum: tag.datum, uhrzeit: p.uhrzeit }, (w.buchung ? 'Geändert: ' : 'Gebucht: ') + T.kurzTag(tag.datum) + ', ' + p.uhrzeit);
          } }, p.uhrzeit))) : el('div', { class: 'leise', text: 'An diesem Tag ist nichts mehr frei.' }),
          el('p', { class: 'leise klein-text', text: 'Antippen bucht. Buchen, ändern und absagen geht bis ' + T.zeitpunkt(tag.schluss) +
            ', danach nur noch über die Lehrkraft.' }));
      }
      zeichnenBlatt();
      d.append(el('div', { class: 'blatt-griff' }),
        el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: w.buchung ? 'Termin ändern' : 'Termin buchen' }),
          el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'leicht', 'aria-label': 'Schließen', onclick: zu }, '✕'))), inhalt);
      d.addEventListener('cancel', ev => { ev.preventDefault(); zu(); });
      d.addEventListener('click', ev => { if (ev.target === d) zu(); });   // Klick neben das Fenster
      document.body.appendChild(d);
      d.showModal();
    }

    function zeichnen() {
      const d = S.daten;
      if (!d.regeln) {
        return T.setzen(ort, el('div', { class: 'leer', text: lehrkraft
          ? 'Für dieses Projekt gilt noch keine Projektzeit. Lege unter „Termine“ eine für die Klasse des Projekts an.'
          : 'Für euer Projekt gibt es noch keine Besprechungstermine. Die Lehrkraft legt sie an.' }));
      }
      if (!d.wochen.length) {
        return T.setzen(ort, el('div', { class: 'leer', text: 'In den nächsten Wochen gibt es keine Projekttage (Ferien oder Projektende).' }));
      }
      if (!lehrkraft) return T.setzen(ort, teamKompakt(d.wochen[0]));   // Team: aktuelle Woche, Buchen im Fenster
      T.setzen(ort, el('div', { class: 'stapel' }, d.wochen.map(woche),
        el('p', { class: 'leise', text: lehrkraft ? 'Freien Termin anklicken, um ihn für das Team einzutragen oder umzubuchen. Du darfst auch nach dem Buchungsschluss ändern.'
          : 'Freien Termin antippen zum Buchen oder Umbuchen. Je Woche ein Termin. Bis zum Termin Raster und Ampeln aktualisieren.' })));
    }

    return { laden };
  }

  return { erzeugen };
})();
