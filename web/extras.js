// Extras: Mindmap (Lehrkraft laedt hoch, Team sieht sie im Reiter "Projekt") und Lehrernotizen (nur Lehrkraefte).
// Lehrkraft: Karten im Reiter "Projekt & Team". Fotos gibt es nur noch ueber die Tafel (der Reiter "Fotos" ist entfallen).
'use strict';

const Extras = (() => {
  const el = T.el;

  function dateiLesen(datei) {
    return new Promise((ok, fehler) => {
      const leser = new FileReader();
      leser.onload = () => ok(String(leser.result).split(',')[1] || '');
      leser.onerror = () => fehler(new Error('Die Datei konnte nicht gelesen werden.'));
      leser.readAsDataURL(datei);
    });
  }

  function bildGross(url, titel) {
    const huelle = el('div', { class: 'tafel-ansicht bild', onclick: () => huelle.remove() },
      el('img', { src: url, alt: titel || 'Foto' }), el('div', { class: 'tafel-leiste', text: (titel || 'Foto') + ' · antippen zum Schließen' }));
    document.body.appendChild(huelle);
  }

  function mindmapAnsicht(m, basis) {
    if (!m) return el('div', { class: 'leise klein-text', text: 'Noch keine Mindmap hinterlegt.' });
    const url = basis + '/bild/' + m.name;
    return m.typ === 'application/pdf'
      ? el('div', { class: 'zeile' }, el('span', { class: 'chip', text: 'PDF' }), el('b', { text: m.titel }),
        el('a', { class: 'knopf', href: url, download: '' }, 'Herunterladen'), el('span', { class: 'leise klein-text', text: T.zeitText(m.erstellt) }))
      : el('figure', { class: 'mindmap' }, el('img', { src: url, alt: m.titel, onclick: () => bildGross(url, m.titel) }),
        el('figcaption', { class: 'leise klein-text', text: m.titel + ' · ' + T.zeitText(m.erstellt) }));
  }

  // --- Lehrkraft: Karten auf der Projektseite ---

  function lehrerKarten(pid, archiviert) {
    const basis = '/api/projekte/' + pid;
    const mindmapOrt = el('div'), notizOrt = el('div');
    let D = null;

    async function senden(pfad, daten, meldung) {
      try { D = await T.api('POST', basis + pfad, daten); zeichnen(); if (meldung) T.meldung(meldung); return true; }
      catch (e) { T.meldung(e.message, true); return false; }
    }

    function zeichnen() {
      const datei = el('input', { type: 'file', accept: 'image/png,image/jpeg,application/pdf', hidden: true });
      datei.addEventListener('change', async () => {
        if (!datei.files.length) return;
        try { await senden('/mindmap', { inhalt: await dateiLesen(datei.files[0]), titel: datei.files[0].name.replace(/\.[^.]+$/, '') }, 'Mindmap gespeichert.'); }
        catch (e) { T.meldung(e.message, true); }
      });
      T.setzen(mindmapOrt, mindmapAnsicht(D.mindmap, basis), archiviert ? null : el('div', { class: 'zeile' },
        el('button', { type: 'button', onclick: () => datei.click() }, D.mindmap ? 'Neue Mindmap hochladen' : 'Mindmap hochladen'), datei,
        el('span', { class: 'leise klein-text', text: 'Bild (PNG, JPEG) oder PDF bis 8 MB. Das Team sieht sie im Reiter „Projekt“.' })));
      const eigene = D.notizen.filter(n => n.art === 'notiz').length;
      T.setzen(notizOrt,
        el('p', { class: 'leise klein-text', text: 'Lehrernotizen stehen im gemeinsamen Zeitstrahl unter „Notizen“. Alle Lehrkräfte sehen sie, das Team nie.' }),
        el('div', { class: 'zeile' }, el('a', { class: 'knopf', href: '#notizen/projekt/' + pid },
          eigene ? 'Notizen zu diesem Projekt (' + eigene + ')' : 'Notizen zu diesem Projekt'),
          el('span', { class: 'leise klein-text', text: 'Neue Notiz dort mit „+ Neue Notiz“, das Projekt ist schon gewählt.' })));
    }

    (async () => {
      try { D = await T.api('GET', basis + '/extras'); zeichnen(); }
      catch (e) { T.setzen(mindmapOrt, el('div', { class: 'leer', text: e.message })); }
    })();

    return [
      el('section', { class: 'karte stapel-eng' }, el('h2', { class: 'dreieck', text: 'Mindmap' }), mindmapOrt),
      el('section', { class: 'karte stapel-eng notizkarte' }, el('h2', { class: 'dreieck', text: 'Lehrernotizen' }), notizOrt)];
  }

  // --- Team ---

  async function teamMindmap(basis) {
    try {
      const d = await T.api('GET', basis + '/extras');
      return el('section', { class: 'karte stapel-eng' }, el('h2', { class: 'dreieck', text: 'Mindmap' }), mindmapAnsicht(d.mindmap, basis));
    } catch (e) { return null; }
  }

  return { lehrerKarten, teamMindmap, dateiLesen };
})();
