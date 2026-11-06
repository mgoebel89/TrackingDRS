// Besprechung: Lehreransicht (Reiter der Projektseite, #projekt/<id>/besprechung: Kurzzusammenfassung, Ergebnis, Lehrernotizen, Abschliessen) und
// Team-Reiter "Besprechung": Termin, vier Kacheln mit gefuehrten Fenstern (Stand eintragen, Frage oder Thema, Post-it
// und Foto an die Tafel), darunter nur was schon da ist (Stand, Themen, an die Tafel Geschicktes, Auftraege, Protokolle).
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

    // Stand: "Geschafft" und "Hakt" getrennt gefragt, gespeichert als ein Text (so liest ihn die Kurzzusammenfassung)
    function standTeile(text) {
      const m = /^Geschafft:\s*([\s\S]*?)\n\s*\nHakt:\s*([\s\S]*)$/.exec(text || '');
      return m ? { geschafft: m[1].trim(), hakt: m[2].trim() } : { geschafft: (text || '').trim(), hakt: '' };
    }
    const standText = w => 'Geschafft:\n' + w.geschafft.trim() + '\n\nHakt:\n' + w.hakt.trim();

    // Gefuehrte Fenster: hoechstens drei Schritte, eine Frage je Schritt (am Handy von unten, am PC in der Mitte)
    const ABLAEUFE = {
      stand: { titel: 'Stand eintragen', fertig: 'Stand speichern', schritte: [
        { frage: 'Was habt ihr seit dem letzten Mal geschafft?', hilfe: 'Stichpunkte reichen, z. B. „Lüfter bestellt, Gehäuse gezeichnet“.',
          feld: 'text', name: 'geschafft' },
        { frage: 'Was hakt gerade?', hilfe: 'Wenn nichts hakt, tippt auf „Nichts, läuft“.', feld: 'text', name: 'hakt', schnell: 'Nichts, läuft' },
        { frage: 'Passt das so?', feld: 'pruefen' }] },
      frage: { titel: 'Frage oder Thema', fertig: 'Für die Besprechung notieren', schritte: [
        { frage: 'Was wollt ihr in der Besprechung klären?', feld: 'wahl', name: 'art', wahl: [
          ['frage', 'Eine Frage', 'Ihr braucht eine Antwort von der Lehrkraft.', 'st_frage'],
          ['thema', 'Ein Thema', 'Ihr wollt etwas zeigen oder gemeinsam besprechen.', 'st_team']] },
        { frage: 'Schreibt es in einem Satz.', feld: 'zeile', name: 'text', max: 500 },
        { frage: 'Passt das so?', feld: 'pruefen' }] },
      idee: { titel: 'Post-it an die Tafel', fertig: 'An die Tafel schicken', schritte: [
        { frage: 'Was soll auf das Post-it?', feld: 'wahl', name: 'art', wahl: [
          ['idee', 'Eine Idee', 'gelbes Post-it bei den Ideen', 'st_idee'], ['frage', 'Eine Frage', 'blaues Post-it bei den Fragen', 'st_frage']] },
        { frage: 'Kurz wie auf einem Post-it.', hilfe: 'Höchstens 200 Zeichen.', feld: 'zeile', name: 'text', max: 200 },
        { frage: 'So sieht es auf der Tafel aus.', feld: 'postit' }] },
      foto: { titel: 'Foto an die Tafel', fertig: 'An die Tafel schicken', schritte: [
        { frage: 'Fotografiert euren Aufbau.', hilfe: 'Bitte keine Personen aufs Bild.', feld: 'foto' },
        { frage: 'Wollt ihr etwas dazuschreiben?', hilfe: 'Freiwillig, z. B. „Lüfter montiert“.', feld: 'zeile', name: 'text', max: 200, frei: true },
        { frage: 'Passt das so?', feld: 'pruefen' }] },
    };
    const BEISPIEL = { frage: 'z. B. Dürfen wir 24 V nehmen?', thema: 'z. B. Wir zeigen den Gehäuseentwurf.', idee: 'z. B. 2 Lüfter parallel?' };

    function ablauf(name) {
      const a = ABLAEUFE[name];
      const w = name === 'stand' ? standTeile(B.vorbereitung) : {};
      let nr = 0, vorschau = null;
      const d = el('dialog', { class: 'blatt-dialog gefuehrt' });
      const punkte = el('div', { class: 'schritt-punkte' });
      const inhaltOrt = el('div', { class: 'stapel-eng' });
      const zurueck = el('button', { type: 'button' });
      const weiter = el('button', { type: 'button', class: 'haupt' });
      const zu = () => { if (vorschau) URL.revokeObjectURL(vorschau); d.close(); d.remove(); };
      const gueltig = s => s.feld === 'wahl' ? !!w[s.name] : s.feld === 'foto' ? !!w.bild
        : (s.feld === 'text' || s.feld === 'zeile') ? (s.frei || !!(w[s.name] || '').trim()) : true;
      const pruefZeile = (etikett, text) => el('div', {}, el('div', { class: 'etikett', text: etikett }), el('div', { class: 'vortext', text }));

      function zeigenSchritt() {
        const s = a.schritte[nr];
        T.setzen(punkte, a.schritte.map((_, i) => el('i', { class: i <= nr ? 'an' : '' })),
          el('span', { text: 'Schritt ' + (nr + 1) + ' von ' + a.schritte.length }));
        const teile = [el('div', { class: 'schritt-frage', text: s.frage }), s.hilfe ? el('div', { class: 'leise klein-text', text: s.hilfe }) : null];
        if (s.feld === 'wahl') {
          teile.push(el('div', { class: 'schritt-wahl' }, s.wahl.map(([wert, titel, text, symbol]) => el('button', { type: 'button',
            class: w[s.name] === wert ? 'an' : '', 'aria-pressed': w[s.name] === wert ? 'true' : 'false',
            onclick: () => { w[s.name] = wert; nr++; zeigenSchritt(); } }, T.symbol(symbol), el('b', { text: titel }), el('small', { text })))));
        } else if (s.feld === 'text' || s.feld === 'zeile') {
          const f = el(s.feld === 'text' ? 'textarea' : 'input', { class: 'schritt-eingabe', maxlength: String(s.max || 2000),
            rows: s.feld === 'text' ? '4' : null, value: w[s.name] || '', placeholder: s.name === 'text' ? BEISPIEL[w.art] || '' : '' });
          f.addEventListener('input', () => { w[s.name] = f.value; weiter.disabled = !gueltig(s); });
          f.addEventListener('keydown', ev => { if (ev.key === 'Enter' && s.feld === 'zeile' && gueltig(s)) { ev.preventDefault(); weiter.click(); } });
          teile.push(f);
          if (s.schnell) teile.push(el('div', { class: 'zeile' }, el('button', { type: 'button', class: 'schnell',
            onclick: () => { w[s.name] = s.schnell; nr++; zeigenSchritt(); } }, s.schnell)));
          setTimeout(() => f.focus(), 30);
        } else if (s.feld === 'foto') {
          const datei = el('input', { type: 'file', accept: 'image/*', capture: 'environment', hidden: true });
          datei.addEventListener('change', async () => {
            if (!datei.files.length) return;
            try {
              w.bild = await verkleinern(datei.files[0]);
              if (vorschau) URL.revokeObjectURL(vorschau);
              vorschau = URL.createObjectURL(datei.files[0]);
              zeigenSchritt();
            } catch (e) { T.meldung('Das Foto konnte nicht gelesen werden.', true); }
          });
          teile.push(datei, w.bild
            ? [el('img', { class: 'schritt-foto', src: vorschau, alt: 'Vorschau' }), el('button', { type: 'button', class: 'leicht', onclick: () => datei.click() }, 'Neu aufnehmen')]
            : el('button', { type: 'button', class: 'schritt-kamera', onclick: () => datei.click() }, T.symbol('bild'), 'Kamera öffnen'));
        } else if (s.feld === 'pruefen') {
          teile.push(el('div', { class: 'schritt-pruefen stapel-eng' },
            name === 'stand' ? [pruefZeile('Geschafft', w.geschafft), pruefZeile('Hakt', w.hakt)]
              : name === 'foto' ? [el('img', { class: 'schritt-foto', src: vorschau, alt: 'Vorschau' }), (w.text || '').trim() ? el('div', { text: w.text }) : null]
                : pruefZeile(w.art === 'thema' ? 'Thema' : 'Frage', w.text)));
        } else if (s.feld === 'postit') {
          teile.push(el('div', { class: 'schritt-postit' + (w.art === 'frage' ? ' frage' : ''), text: w.text }),
            el('div', { class: 'leise klein-text', text: 'Läuft gerade keine Besprechung, wartet das Post-it bis zur nächsten.' }));
        }
        T.setzen(inhaltOrt, teile);
        zurueck.textContent = nr ? 'Zurück' : 'Abbrechen';
        weiter.textContent = nr === a.schritte.length - 1 ? a.fertig : 'Weiter';
        weiter.hidden = s.feld === 'wahl';   // Auswahl geht mit einem Tipp weiter
        weiter.disabled = !gueltig(s);
      }

      async function fertig() {
        weiter.disabled = true;
        let ok;
        if (name === 'stand') ok = await senden({ aktion: 'vorbereitung', text: standText(w) }, 'Stand gespeichert.');
        else if (name === 'frage') ok = await senden({ aktion: 'eintrag_neu', art: w.art, text: w.text }, 'Für die Besprechung notiert.');
        else if (name === 'idee') ok = await anTafel({ art: w.art, text: w.text }, 'An die Tafel geschickt.');
        else ok = await anTafel({ bild: w.bild, text: w.text || '' }, 'Foto an die Tafel geschickt.');
        if (ok) zu(); else weiter.disabled = false;
      }

      zurueck.addEventListener('click', () => { if (nr) { nr--; zeigenSchritt(); } else zu(); });
      weiter.addEventListener('click', () => { if (weiter.disabled) return; if (nr === a.schritte.length - 1) fertig(); else { nr++; zeigenSchritt(); } });
      d.append(el('div', { class: 'blatt-griff' }),
        el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: a.titel }),
          el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'leicht', 'aria-label': 'Schließen', onclick: zu }, '✕'))),
        punkte, inhaltOrt, el('div', { class: 'schritt-navi' }, zurueck, weiter));
      d.addEventListener('cancel', ev => { ev.preventDefault(); zu(); });
      d.addEventListener('click', ev => { if (ev.target === d) zu(); });
      document.body.appendChild(d);
      d.showModal();
      zeigenSchritt();
    }

    function kachel(name, symbol, titel, text, farbe) {
      return el('button', { type: 'button', class: 'b-kachel ' + farbe, onclick: () => ablauf(name) },
        el('span', { class: 'b-kachel-sym' }, T.symbol(symbol)), el('b', { text: titel }), el('small', { text }));
    }

    function zeichnen() {
      const themen = B.eintraege.filter(e => e.art === 'frage' || e.art === 'thema');
      const tafel = B.eintraege.filter(e => e.art === 'idee');
      const auftraege = B.eintraege.filter(e => e.art === 'auftrag');
      const offenAuftraege = auftraege.filter(e => !e.erledigt).length;
      const st = standTeile(B.vorbereitung);
      const weg = e => e.wer_art === 'team' ? el('button', { type: 'button', class: 'leicht', title: 'zurückziehen', 'aria-label': 'zurückziehen',
        onclick: () => senden({ aktion: 'verwerfen', eintrag_id: e.id }, 'Zurückgezogen.') }, '✕') : null;
      T.setzen(ort, el('div', { class: 'stapel' },
        el('section', { class: 'karte b-termin' },
          T.symbol('kalender'),
          el('div', {}, el('div', { class: 'leise klein-text', text: 'Nächste Besprechung' }), el('b', { text: terminText(B) }),
            B.termin ? null : el('span', { class: 'leise klein-text', text: ' · Termin in der Übersicht buchen' })),
          el('div', { class: 'b-marken' },
            el('span', { class: B.vorbereitung ? 'ok' : '', text: 'Stand eingetragen' }),
            el('span', { class: themen.length ? 'ok' : '', text: 'Themen notiert' })),
          tafelStatus),
        el('div', { class: 'b-kacheln' },
          kachel('stand', 'stift', 'Stand eintragen', 'Was habt ihr geschafft, was hakt?', 'blau'),
          kachel('frage', 'st_frage', 'Frage oder Thema', 'für die Besprechung notieren', 'gruen'),
          kachel('idee', 'st_idee', 'Post-it an die Tafel', 'Idee oder Frage, kurz und knapp', 'gelb'),
          kachel('foto', 'bild', 'Foto an die Tafel', 'Aufbau zeigen, keine Personen', 'rot')),
        el('section', { class: 'karte stapel-eng' },
          el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: 'Euer Stand' }),
            B.vorbereitet ? el('span', { class: 'leise klein-text', text: T.zeitText(B.vorbereitet) }) : null,
            B.vorbereitung ? el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'leicht', onclick: () => ablauf('stand') }, 'Ändern')) : null),
          B.vorbereitung ? el('div', { class: 'b-stand' },
            el('div', {}, el('div', { class: 'etikett', text: 'Geschafft' }), el('div', { class: 'vortext', text: st.geschafft || '–' })),
            st.hakt ? el('div', {}, el('div', { class: 'etikett', text: 'Hakt' }), el('div', { class: 'vortext', text: st.hakt })) : null)
            : el('div', { class: 'leise klein-text', text: 'Noch nicht eingetragen.' })),
        el('section', { class: 'karte stapel-eng' },
          el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: 'Für die Besprechung' }), themen.length ? el('span', { class: 'chip', text: String(themen.length) }) : null),
          themen.length ? themen.map(e => el('div', { class: 'ez' }, el('span', { class: 'chip', text: ARTEN[e.art] }), el('span', { class: 'ez-text', text: e.text }), weg(e)))
            : el('div', { class: 'leise klein-text', text: 'Noch nichts notiert.' })),
        el('section', { class: 'karte stapel-eng' },
          el('h2', { class: 'dreieck', text: 'An die Tafel geschickt' }),
          tafel.length ? tafel.map(e => el('div', { class: 'ez' },
            e.bild ? el('img', { class: 'ez-bild', src: basis + '/bild/' + e.bild, alt: 'Foto', loading: 'lazy' }) : el('span', { class: 'chip', text: 'Idee' }),
            el('span', { class: 'ez-text', text: e.bild && e.text === 'Foto' ? 'Foto' : e.text }), weg(e)))
            : el('div', { class: 'leise klein-text', text: 'Noch nichts. Post-its und Fotos landen in der nächsten Besprechung bei den Ideen.' })),
        el('section', { class: 'karte stapel-eng' },
          el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: 'Aufträge' }), offenAuftraege ? el('span', { class: 'chip', text: offenAuftraege + ' offen' }) : null),
          auftraege.length ? auftraege.map(e => auftragZeile(e, (x, wert) => senden({ aktion: 'erledigt', eintrag_id: x.id, erledigt: wert },
            wert ? 'Abgehakt.' : 'Wieder offen.'))) : el('div', { class: 'leise klein-text', text: 'Keine Aufträge offen.' })),
        el('section', { class: 'karte stapel-eng' },
          el('h2', { class: 'dreieck', text: 'Protokolle' }), protokolle(B.protokolle, false, basis, B.projekt_titel))));
    }

    return { laden };
  }

  return { lehrerZeigen, teamErzeugen, verkleinern };
})();
