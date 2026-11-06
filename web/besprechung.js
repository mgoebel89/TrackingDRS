// Besprechung: Lehreransicht (Reiter der Projektseite, #projekt/<id>/besprechung: Kurzzusammenfassung, Ergebnis, Lehrernotizen, Abschliessen) und
// Team-Reiter "Besprechung" (Stand vorbereiten, Fragen und Themen, Post-its und Fotos an die Tafel, Auftraege
// abhaken, Protokolle mit eingefrorener Tafel).
// Lehrernotizen kommen nur ueber die Lehrer-Schnittstelle und erscheinen nie beim Team.
'use strict';

const Besprechung = (() => {
  const el = T.el;
  const AMPEL = { g: 'grün', y: 'gelb', r: 'rot' };
  const ARTEN = { frage: 'Frage', thema: 'Thema', idee: 'Idee', auftrag: 'Auftrag', absprache: 'Absprache', meilenstein: 'Meilenstein' };

  const datumText = text => text.slice(8, 10) + '.' + text.slice(5, 7) + '.';
  const terminText = b => b.termin ? T.kurzTag(b.termin.datum) + ', ' + b.termin.uhrzeit : T.kwText(b.woche) + ' · kein Termin gebucht';
  const fokusInEingabe = ort => ort.contains(document.activeElement) && document.activeElement.matches('input, textarea, select');

  function auftragZeile(e, abhaken) {
    const status = e.erledigt ? el('span', { class: 'leise', text: '✓ ' + T.zeitText(e.erledigt) })
      : e.ueberfaellig ? el('span', { class: 'fehlertext', text: 'überfällig seit ' + datumText(e.frist) })
        : el('span', { class: 'leise', text: 'bis ' + datumText(e.frist) });
    return el('div', { class: 'ez' + (e.erledigt ? ' erl' : '') },
      abhaken ? el('input', { type: 'checkbox', checked: !!e.erledigt, 'aria-label': 'erledigt', onchange: ev => abhaken(e, ev.target.checked) })
        : el('span', { class: 'ez-m', text: e.erledigt ? '✓' : '•' }),
      el('span', { class: 'ez-text' }, e.text, e.verantwortlich ? el('span', { class: 'chip', text: e.verantwortlich }) : null), status);
  }

  function protokolle(liste, lehrkraft, basis, titel) {
    if (!liste.length) return el('div', { class: 'leise', text: 'Noch keine abgeschlossene Besprechung.' });
    return el('div', { class: 'stapel-eng' }, liste.map(p => {
      const nach = art => (p.ergebnis || []).filter(e => e.art === art);
      const teil = (titel, eintraege, f) => eintraege.length ? el('div', {}, el('div', { class: 'etikett', text: titel }), eintraege.map(f)) : null;
      return el('details', { class: 'protokoll' },
        el('summary', {}, el('b', { text: T.kwText(p.woche) }), ' · ' + (p.termin ? T.kurzTag(p.termin.datum) + ', ' + p.termin.uhrzeit : 'ohne Termin') +
          ' · ' + (p.ergebnis || []).length + ((p.ergebnis || []).length === 1 ? ' Ergebnis' : ' Ergebnisse')),
        el('div', { class: 'stapel-eng' },
          teil('Absprachen', nach('absprache'), e => el('div', { class: 'ez' }, el('span', { class: 'ez-m', text: '•' }), el('span', { text: e.text }))),
          teil('Aufträge', nach('auftrag'), e => auftragZeile(e)),
          teil('Meilensteine', nach('meilenstein'), e => el('div', { class: 'ez' }, el('span', { class: 'ez-m ms', text: '◆' }),
            el('span', { text: e.text + (e.frist ? ' · ' + T.kwText(e.frist) : '') }))),
          teil('Geklärt', p.geklaert || [], e => el('div', { class: 'ez' }, el('span', { class: 'ez-m', text: '✓' }),
            el('span', { text: ARTEN[e.art] + ': ' + e.text }))),
          p.vorbereitung ? el('div', {}, el('div', { class: 'etikett', text: 'Stand des Teams' }), el('p', { class: 'vortext', text: p.vorbereitung })) : null,
          lehrkraft && p.notizen ? el('div', { class: 'notiz-alt' }, el('div', { class: 'etikett', text: 'Lehrernotizen (nur Lehrkräfte)' }),
            el('p', { class: 'vortext', text: p.notizen })) : null,
          el('div', { class: 'zeile' },
            p.tafel ? el('button', { type: 'button', onclick: () => Tafel.ansehen(basis + '/tafel/' + p.id, basis) }, 'Tafel ansehen') : null,
            Tafel.downloadKnoepfe(basis, p, titel || 'Projekt')),
          el('div', { class: 'leise klein-text', text: 'abgeschlossen ' + T.zeitText(p.abgeschlossen) + (p.von ? ' von ' + p.von.toUpperCase() : '') })));
    }));
  }

  // --- Lehreransicht ---

  async function lehrerZeigen(pid, ort) {
    const basis = '/api/projekte/' + pid;
    const [{ projekt }, start] = await Promise.all([T.api('GET', basis), T.api('GET', basis + '/besprechung')]);
    let B = start.besprechung;
    if (!ort) titelSetzen('Besprechung · ' + projekt.titel);
    const links = el('div', { class: 'stapel' }), ergebnisOrt = el('div'), frueher = el('div');
    const unter = el('span', { class: 'leise' });
    const notizen = el('textarea', { rows: '10', maxlength: '20000', 'aria-label': 'Lehrernotizen', value: B.notizen });
    const notizStand = el('span', { class: 'leise klein-text' });
    let notizTimer = null;

    async function senden(daten, meldung) {
      try {
        const r = await T.api('POST', basis + '/besprechung', Object.assign({ woche: B.woche }, daten));
        B = r.besprechung;
        zeichnen();
        if (meldung) T.meldung(meldung);
        return r.ergebnis || {};
      } catch (e) { T.meldung(e.message, true); return null; }
    }

    async function notizenSpeichern() {
      clearTimeout(notizTimer);
      try {
        await T.api('POST', basis + '/besprechung', { aktion: 'notizen', woche: B.woche, text: notizen.value });
        notizStand.textContent = 'gespeichert ' + new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
      } catch (e) { notizStand.textContent = e.message; }
    }
    notizen.addEventListener('input', () => { notizStand.textContent = 'ungespeichert …'; clearTimeout(notizTimer); notizTimer = setTimeout(notizenSpeichern, 900); });
    notizen.addEventListener('blur', () => { if (notizTimer) notizenSpeichern(); });

    function zusammenfassung() {
      const z = B.zusammenfassung;
      const abschnitt = (titel, inhalt, leer) => el('div', { class: 'zf' }, el('div', { class: 'etikett', text: titel }),
        inhalt && (!Array.isArray(inhalt) || inhalt.length) ? inhalt : el('div', { class: 'leise klein-text', text: leer }));
      return el('section', { class: 'karte stapel-eng' },
        el('h2', { class: 'dreieck', text: 'Kurzzusammenfassung' }),
        el('div', { class: 'zeile' },
          el('span', { class: 'punkt gross ' + (z.ampel ? z.ampel.ampel : 'ohne') }),
          el('b', { text: z.ampel ? 'Gesamtstatus ' + T.kwText(z.ampel.woche) + ': ' + AMPEL[z.ampel.ampel] : 'Noch keine Ampel' }),
          z.verlauf.length ? el('span', { class: 'leise' }, ' · letzte Besprechungen ', el('span', { class: 'punkte' },
            z.verlauf.map(v => el('span', { class: 'punkt ' + (v.ampel || 'ohne'), title: T.kwText(v.woche) + ': ' + (AMPEL[v.ampel] || 'keine Ampel') })))) : null),
        abschnitt('Stand des Teams', z.vorbereitung ? [el('p', { class: 'vortext', text: z.vorbereitung }),
          el('div', { class: 'leise klein-text', text: 'eingetragen ' + T.zeitText(z.vorbereitet) })] : null, 'Das Team hat nichts vorbereitet.'),
        abschnitt('Fragen und Themen des Teams', z.fragen.map(e => el('label', { class: 'ez' },
          el('input', { type: 'checkbox', onchange: ev => senden({ aktion: 'erledigt', eintrag_id: e.id, erledigt: ev.target.checked }, 'Als geklärt markiert.') }),
          el('span', { class: 'chip', text: ARTEN[e.art] }), el('span', { class: 'ez-text', text: e.text }),
          el('span', { class: 'leise klein-text', text: (e.wer_art === 'team' ? 'Team' : e.wer.toUpperCase()) + ' · ' + T.zeitText(e.erstellt) }))),
          'Keine offenen Fragen.'),
        abschnitt('Seit der letzten Besprechung', z.aenderungen.map(a => el('div', { class: 'ez' },
          el('span', { class: 'ez-m', text: '›' }), el('span', { text: a.text }))), 'Am Raster hat sich nichts geändert.'),
        abschnitt('Probleme', z.probleme.map(p => el('div', { class: 'ez' },
          el('span', { class: 'punkt ' + p.ampel }), el('span', { class: 'ez-text' }, el('b', { text: p.aufgabe }), ': ' + p.problem,
            el('div', { class: 'leise klein-text', text: '→ ' + p.massnahme + (p.verantwortlich ? ' (' + p.verantwortlich + ')' : '') + ' · seit ' + T.kwText(p.seit) })))),
          'Keine offenen Probleme.'),
        abschnitt('Aufträge', z.auftraege.map(e => auftragZeile(e)), 'Keine Aufträge offen.'),
        abschnitt('Ausblick', z.ausblick ? el('div', { text: '◆ ' + z.ausblick.titel + ' · ' + T.kwText(z.ausblick.woche) + ' · noch ' +
          z.ausblick.projektwochen + (z.ausblick.projektwochen === 1 ? ' Projektwoche' : ' Projektwochen') }) : null, 'Kein Meilenstein geplant.'),
        abschnitt('Basisplan', z.basisplan ? el('div', { text: z.basisplan }) : null, 'Noch kein Basisplan festgelegt.'));
    }

    function ergebnis() {
      return el('section', { class: 'karte stapel-eng' },
        el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: 'Ergebnis' })),
        el('div', { class: 'zeile' },
          el('button', { type: 'button', onclick: () => eintragDialog('absprache') }, '+ Absprache'),
          el('button', { type: 'button', onclick: () => eintragDialog('auftrag') }, '+ Auftrag'),
          el('button', { type: 'button', onclick: meilensteinDialog }, '+ Meilenstein')),
        B.ergebnis.length ? B.ergebnis.map(e => el('div', { class: 'ez' },
          el('span', { class: 'chip' + (e.art === 'auftrag' ? ' blau' : ''), text: ARTEN[e.art] }),
          el('span', { class: 'ez-text', text: e.text }),
          el('span', { class: 'leise klein-text', text: e.art === 'auftrag' ? 'bis ' + datumText(e.frist) + (e.verantwortlich ? ' · ' + e.verantwortlich : '')
            : e.art === 'meilenstein' && e.frist ? T.kwText(e.frist) : '' }),
          e.art !== 'meilenstein' ? el('button', { type: 'button', class: 'leicht', title: 'verwerfen', 'aria-label': 'verwerfen',
            onclick: () => senden({ aktion: 'verwerfen', eintrag_id: e.id }, 'Verworfen.') }, '✕') : null))
          : el('div', { class: 'leise klein-text', text: 'Noch nichts festgehalten. Absprachen, Aufträge und Meilensteine stehen nach dem Abschließen im Protokoll.' }));
    }

    async function eintragDialog(art) {
      const naechste = new Date(); naechste.setDate(naechste.getDate() + 7);
      const f = {
        text: el('input', { required: true, maxlength: '500', placeholder: art === 'auftrag' ? 'z. B. 2 Lüfter vergleichen' : 'z. B. 24 V ist freigegeben' }),
        frist: el('input', { type: 'date', required: true, value: T.isoDatum(naechste) }),
        wer: el('select', {}, el('option', { value: '', text: 'ganzes Team' }), B.mitglieder.map(m => el('option', { value: String(m.id), text: m.name }))),
      };
      await T.dialog({
        titel: art === 'auftrag' ? 'Auftrag' : 'Absprache', knopf: 'Festhalten',
        inhalt: el('div', { class: 'felder' }, T.feld(art === 'auftrag' ? 'Was ist zu tun?' : 'Was wurde abgesprochen?', f.text),
          art === 'auftrag' ? el('div', { class: 'felder zwei' }, T.feld('Frist', f.frist), T.feld('Verantwortlich', f.wer)) : null),
        speichern: async () => {
          const r = await T.api('POST', basis + '/besprechung', { aktion: 'eintrag_neu', woche: B.woche, art, text: f.text.value,
            frist: art === 'auftrag' ? f.frist.value : null, verantwortlich_id: f.wer.value ? Number(f.wer.value) : null });
          B = r.besprechung;
          return true;
        },
      });
      zeichnen();
    }

    async function meilensteinDialog() {
      const wochen = (B.projektwochen || []).filter(w => w >= B.woche);
      const f = {
        titel: el('input', { required: true, maxlength: '120', placeholder: 'z. B. Konstruktion fertig' }),
        woche: wochen.length ? el('select', {}, wochen.map(w => el('option', { value: w, text: T.kwText(w) + ' · ' + T.tagText(w) })))
          : el('input', { type: 'date', required: true, value: B.woche }),
      };
      await T.dialog({
        titel: 'Meilenstein', knopf: 'Setzen',
        inhalt: el('div', { class: 'felder' }, T.feld('Name', f.titel), T.feld('Woche', f.woche, 'erscheint sofort im Tracking-Sheet')),
        speichern: async () => {
          const r = await T.api('POST', basis + '/besprechung', { aktion: 'meilenstein', woche: B.woche, titel: f.titel.value,
            meilenstein_woche: f.woche.value });
          B = r.besprechung;
          return true;
        },
      });
      zeichnen();
    }

    async function abschliessen() {
      if (notizTimer) await notizenSpeichern();
      const ok = await T.dialog({
        titel: 'Besprechung abschließen?', knopf: 'Abschließen',
        inhalt: el('p', { text: B.ergebnis.length + (B.ergebnis.length === 1 ? ' Ergebnis geht' : ' Ergebnisse gehen') + ' ins Protokoll, das auch das Team sieht (ohne Lehrernotizen). ' +
          'Offene Aufträge, Fragen und Ideen wandern zur nächsten Besprechung.' }),
        speichern: async () => {
          const r = await T.api('POST', basis + '/besprechung', { aktion: 'abschliessen', woche: B.woche });
          B = r.besprechung;
          return true;
        },
      });
      if (ok) { T.meldung('Abgeschlossen. Das Protokoll steht unten.'); notizen.value = B.notizen; notizStand.textContent = ''; zeichnen(); }
    }

    function zeichnen() {
      unter.textContent = terminText(B);
      T.setzen(links, zusammenfassung());
      T.setzen(ergebnisOrt, ergebnis());
      T.setzen(frueher, el('section', { class: 'karte stapel-eng' }, el('h2', { class: 'dreieck', text: 'Frühere Besprechungen' }),
        protokolle(B.protokolle, true, basis, B.projekt_titel)));
    }

    T.setzen(ort || inhalt,
      el('div', { class: 'werkzeug' }, ort ? el('h2', { class: 'dreieck', text: 'Besprechung' }) : el('h1', { class: 'dreieck', text: 'Besprechung · ' + projekt.titel }), unter,
        ort ? null : el('a', { class: 'knopf', href: '#projekt/' + pid }, 'Zum Projekt'),
        el('button', { type: 'button', onclick: () => Tafel.aufsBoard(pid) }, 'Tafel aufs Board ▶'),
        el('button', { type: 'button', class: 'haupt', onclick: abschliessen }, 'Abschließen')),
      el('div', { class: 'bespr' }, links, el('div', { class: 'stapel' }, ergebnisOrt,
        el('section', { class: 'karte stapel-eng' }, el('h2', { class: 'dreieck', text: 'Lehrernotizen' }),
          el('p', { class: 'leise klein-text', text: 'Nur für Lehrkräfte dieses Projekts. Das Team sieht sie nie, auch nicht im Protokoll.' }),
          notizen, notizStand))),
      frueher);
    zeichnen();

    // Fragen des Teams kommen auch waehrend der Besprechung dazu: alle 20 s nachladen
    const timer = setInterval(async () => {
      if (!links.isConnected) { clearInterval(timer); return; }
      if (document.visibilityState !== 'visible' || fokusInEingabe(inhalt) || document.querySelector('dialog[open]')) return;
      try { B = (await T.api('GET', basis + '/besprechung')).besprechung; zeichnen(); } catch (e) { /* naechster Versuch */ }
    }, 20000);
  }

  // --- Team ---

  // Foto vom Handy verkleinern (hoechstens 1600 px, JPEG), damit es schnell und klein ankommt
  async function verkleinern(datei) {
    const bild = await createImageBitmap(datei);
    const s = Math.min(1, 1600 / Math.max(bild.width, bild.height));
    const c = document.createElement('canvas');
    c.width = Math.round(bild.width * s);
    c.height = Math.round(bild.height * s);
    c.getContext('2d').drawImage(bild, 0, 0, c.width, c.height);
    return c.toDataURL('image/jpeg', 0.8).split(',')[1];
  }

  function geraetKennung() {
    try {
      let k = sessionStorage.getItem('tdrs-geraet');
      if (!k) { k = Math.random().toString(36).slice(2, 12); sessionStorage.setItem('tdrs-geraet', k); }
      return k;
    } catch (e) { return 'x' + Math.random().toString(36).slice(2, 10); }
  }

  function teamErzeugen({ ort, basis, beiAenderung }) {
    let B = null;
    const kennung = geraetKennung();
    const tafelStatus = el('div', { class: 'leise klein-text' });

    // Anwesenheit an der Tafel melden, solange der Reiter offen ist
    const melden = async () => {
      if (!ort.isConnected) { clearInterval(timer); return; }
      if (document.visibilityState !== 'visible') return;
      try {
        const a = (await T.api('GET', basis + '/tafel?geraet=' + kennung)).anwesend;
        tafelStatus.textContent = a.tafel ? 'Die Tafel ist gerade offen: Post-its und Fotos erscheinen sofort.'
          : 'Post-its und Fotos landen in der nächsten Besprechung bei den Ideen.';
        tafelStatus.classList.toggle('live', a.tafel);
      } catch (e) { /* naechster Versuch */ }
    };
    const timer = setInterval(melden, 5000);
    setTimeout(melden, 300);

    async function anTafel(daten, meldung) {
      try {
        B = (await T.api('POST', basis + '/tafel', daten)).besprechung;
        zeichnen();
        T.meldung(meldung);
        return true;
      } catch (e) { T.meldung(e.message, true); return false; }
    }

    async function senden(daten, meldung) {
      try {
        const r = await T.api('POST', basis + '/besprechung', Object.assign({ woche: B.woche }, daten));
        B = r.besprechung;
        zeichnen();
        if (meldung) T.meldung(meldung);
        if (beiAenderung) beiAenderung();
        return true;
      } catch (e) { T.meldung(e.message, true); laden(); return false; }
    }

    async function laden() {
      try { B = (await T.api('GET', basis + '/besprechung')).besprechung; zeichnen(); }
      catch (e) { T.setzen(ort, el('div', { class: 'leer', text: e.message })); }
    }

    function zeichnen() {
      const stand = el('textarea', { rows: '5', maxlength: '4000', value: B.vorbereitung,
        placeholder: 'Was habt ihr seit der letzten Besprechung geschafft? Was hakt?' });
      const art = el('select', { class: 'klein', 'aria-label': 'Art' }, ['frage', 'thema', 'idee'].map(a => el('option', { value: a, text: ARTEN[a] })));
      const text = el('input', { maxlength: '500', placeholder: 'z. B. Dürfen wir 24 V nehmen?', 'aria-label': 'Text' });
      const hinzu = async () => {
        if (!text.value.trim()) { text.focus(); return; }
        if (await senden({ aktion: 'eintrag_neu', art: art.value, text: text.value }, 'Für die Besprechung notiert.')) text.focus();
      };
      text.addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); hinzu(); } });
      const fragen = B.eintraege.filter(e => e.art !== 'auftrag');
      const auftraege = B.eintraege.filter(e => e.art === 'auftrag');
      T.setzen(ort, el('div', { class: 'stapel' },
        el('section', { class: 'karte stapel-eng' },
          el('h2', { class: 'dreieck', text: 'Nächste Besprechung' }),
          el('div', {}, el('b', { text: terminText(B) }), B.termin ? null : el('span', { class: 'leise', text: ' · Termin in der Übersicht buchen' })),
          T.feld('Stand seit dem letzten Mal', stand, B.vorbereitet ? 'zuletzt gespeichert ' + T.zeitText(B.vorbereitet) : 'kurz und stichpunktartig reicht'),
          el('div', {}, el('button', { type: 'button', class: 'haupt', onclick: () => senden({ aktion: 'vorbereitung', text: stand.value }, 'Stand gespeichert.') }, 'Speichern'))),
        el('section', { class: 'karte stapel-eng' },
          el('h2', { class: 'dreieck', text: 'Fragen und Themen' }),
          fragen.length ? fragen.map(e => el('div', { class: 'ez' },
            el('span', { class: 'chip', text: ARTEN[e.art] }), el('span', { class: 'ez-text', text: e.text }),
            e.wer_art === 'team' ? el('button', { type: 'button', class: 'leicht', title: 'zurückziehen', 'aria-label': 'zurückziehen',
              onclick: () => senden({ aktion: 'verwerfen', eintrag_id: e.id }, 'Zurückgezogen.') }, '✕') : null))
            : el('div', { class: 'leise klein-text', text: 'Noch nichts für die Besprechung notiert.' }),
          el('div', { class: 'neu-eintrag' }, art, text, el('button', { type: 'button', onclick: hinzu }, 'Hinzufügen'))),
        tafelKarte(),
        el('section', { class: 'karte stapel-eng' },
          el('h2', { class: 'dreieck', text: 'Aufträge' }),
          auftraege.length ? auftraege.map(e => auftragZeile(e, (x, wert) => senden({ aktion: 'erledigt', eintrag_id: x.id, erledigt: wert },
            wert ? 'Abgehakt.' : 'Wieder offen.'))) : el('div', { class: 'leise klein-text', text: 'Keine Aufträge offen.' })),
        el('section', { class: 'karte stapel-eng' },
          el('h2', { class: 'dreieck', text: 'Protokolle' }), protokolle(B.protokolle, false, basis, B.projekt_titel))));
    }

    function tafelKarte() {
      const art = el('select', { class: 'klein', 'aria-label': 'Art' }, ['idee', 'frage'].map(a => el('option', { value: a, text: ARTEN[a] })));
      const text = el('input', { maxlength: '200', placeholder: 'z. B. 2 Lüfter parallel?', 'aria-label': 'Text für die Tafel' });
      const foto = el('input', { type: 'file', accept: 'image/*', capture: 'environment', hidden: true });
      const senden = async () => {
        if (!text.value.trim()) { text.focus(); return; }
        if (await anTafel({ art: art.value, text: text.value }, 'An die Tafel geschickt.')) text.value = '';
      };
      text.addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); senden(); } });
      foto.addEventListener('change', async () => {
        if (!foto.files.length) return;
        try {
          const bild = await verkleinern(foto.files[0]);
          if (await anTafel({ bild, text: text.value }, 'Foto an die Tafel geschickt.')) text.value = '';
        } catch (e) { T.meldung('Das Foto konnte nicht gelesen werden.', true); }
        foto.value = '';
      });
      return el('section', { class: 'karte stapel-eng' },
        el('h2', { class: 'dreieck', text: 'An die Tafel' }), tafelStatus,
        el('div', { class: 'neu-eintrag' }, art, text, el('button', { type: 'button', onclick: senden }, 'Senden')),
        el('div', { class: 'zeile' }, el('button', { type: 'button', onclick: () => foto.click() }, '📷 Foto'), foto,
          el('span', { class: 'leise klein-text', text: 'Aufbau fotografieren, keine Personen.' })));
    }

    return { laden };
  }

  return { lehrerZeigen, teamErzeugen, verkleinern };
})();
