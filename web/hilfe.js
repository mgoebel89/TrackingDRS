// Hilfe-Knopf (Stufe J4). Team: roter Knopf "Wir brauchen Hilfe" auf jedem Reiter, danach "Ihr seid Nr. 2" bzw.
// "Matthias Göbel kommt"; antippen zieht die Meldung zurueck. Geht nur waehrend der Projektzeit. Lehrkraft: Hilfe-Reihe
// oben im Cockpit nach Eingang, rote Zahl am Menuepunkt, Einblendung und auf Wunsch Windows-Hinweis (Schalter der Anfragen).
'use strict';

const Hilfe = (() => {
  const el = T.el;
  const seit = zeit => {
    const min = Math.max(0, Math.round((Date.now() - new Date(zeit).getTime()) / 60000));
    return min < 1 ? 'gerade eben' : min === 1 ? 'seit 1 min' : 'seit ' + min + ' min';
  };

  // --- Team ---

  function teamKnopf(basis) {
    let H = null;
    const knopf = el('button', { type: 'button', class: 'hilfe-fab', hidden: true, onclick: () => klick() });
    document.body.appendChild(knopf);
    document.body.classList.add('mit-hilfe');   // Einblendungen ruecken ueber den Knopf

    async function laden() {
      try { H = (await T.api('GET', basis + '/hilfe')).hilfe; zeichnen(); } catch (e) { /* naechster Versuch */ }
    }

    function zeichnen() {
      const m = H.meldung;
      knopf.hidden = false;
      knopf.className = 'hilfe-fab' + (m ? ' wartet' + (m.kommt ? ' kommt' : '') : H.projektzeit ? '' : ' ruhig');
      T.setzen(knopf, T.symbol('hilfe'), m
        ? el('span', {}, m.kommt ? m.kommt + ' kommt' : 'Ihr seid Nr. ' + m.nr, el('small', { text: 'antippen zum Zurückziehen' }))
        : el('span', { text: 'Wir brauchen Hilfe' }));
      knopf.setAttribute('aria-label', m ? 'Hilfe-Meldung zurückziehen' : 'Hilfe rufen');
    }

    async function senden(daten, meldung) {
      try { H = (await T.api('POST', basis + '/hilfe', daten)).hilfe; zeichnen(); T.meldung(meldung); return true; }
      catch (e) { T.meldung(e.message, true); laden(); return false; }
    }

    async function klick() {
      if (!H) return;
      if (H.meldung) {
        const ok = await T.dialog({ titel: 'Hilfe-Meldung zurückziehen?', knopf: 'Zurückziehen',
          inhalt: el('p', { text: 'Ihr braucht doch keine Hilfe mehr? Dann verschwindet ihr aus der Reihe.' }),
          speichern: async () => { H = (await T.api('POST', basis + '/hilfe', { aktion: 'zurueckziehen' })).hilfe; return true; } });
        if (ok) { zeichnen(); T.meldung('Hilfe-Meldung zurückgezogen.'); }
        return;
      }
      blatt();
    }

    function blatt() {
      let wer = '';
      const d = el('dialog', { class: 'blatt-dialog gefuehrt' });
      const zu = () => { d.close(); d.remove(); };
      const namen = el('div', { class: 'hilfe-namen' });
      const namenZeichnen = () => T.setzen(namen, H.mitglieder.concat('ganzes Team').map(n => el('button', { type: 'button',
        class: (n === wer || (n === 'ganzes Team' && wer === '')) ? 'an' : '', 'aria-pressed': n === wer ? 'true' : 'false',
        onclick: () => { wer = n === 'ganzes Team' ? '' : n; namenZeichnen(); } }, n)));
      namenZeichnen();
      const inhalt = H.projektzeit
        ? [el('div', { class: 'schritt-frage', text: 'Wer braucht Hilfe?' }),
          el('div', { class: 'leise klein-text', text: 'Freiwillig. Die Lehrkraft sieht dann, zu wem sie kommen soll.' }), namen,
          el('div', { class: 'schritt-navi' }, el('button', { type: 'button', onclick: zu }, 'Abbrechen'),
            el('button', { type: 'button', class: 'haupt rot', onclick: async () => { if (await senden({ aktion: 'rufen', wer }, 'Hilfe gerufen.')) zu(); } },
              T.symbol('hilfe'), 'Hilfe rufen'))]
        : [el('div', { class: 'schritt-frage', text: 'Gerade ist keine Projektzeit.' }),
          el('p', { class: 'leise', text: 'Der Hilfe-Knopf geht nur an Projekttagen während der Projektzeit. Stellt eure Frage als Rückfrage, ' +
            'dann antwortet die Lehrkraft dort.' }),
          el('div', { class: 'schritt-navi' }, el('button', { type: 'button', onclick: zu }, 'Schließen'),
            el('a', { class: 'knopf haupt', href: '#anfragen', onclick: zu }, 'Zu den Anfragen'))];
      d.append(el('div', { class: 'blatt-griff' }),
        el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: 'Hilfe rufen' }),
          el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'leicht', 'aria-label': 'Schließen', onclick: zu }, '✕'))),
        el('div', { class: 'stapel-eng' }, inhalt));
      d.addEventListener('cancel', ev => { ev.preventDefault(); zu(); });
      d.addEventListener('click', ev => { if (ev.target === d) zu(); });
      document.body.appendChild(d);
      d.showModal();
    }

    laden();
    setInterval(() => { if (document.visibilityState === 'visible') laden(); }, 10000);
  }

  // --- Lehrkraft ---

  let R = [], bekannt = null;
  const orte = new Set();

  async function abfragen() {
    try { R = (await T.api('GET', '/api/hilfe')).reihe; } catch (e) { return; }
    if (bekannt) R.filter(m => !bekannt.includes(m.id)).forEach(melden);
    bekannt = R.map(m => m.id);
    allesZeigen();
  }

  function melden(m) {
    const text = m.projekt + (m.wer ? ' (' + m.wer + ')' : '') + ' braucht Hilfe';
    T.meldung('Hilfe: ' + text, false, '#cockpit');
    Vorgang.windowsHinweis('Hilfe', text, '#cockpit', 'tdrs-hilfe-' + m.id);
  }

  function allesZeigen() {
    const link = document.querySelector('nav.seite a[data-ansicht="cockpit"]');
    if (link) {
      let b = link.querySelector('.nav-zahl');
      if (!b) { b = el('span', { class: 'nav-zahl neu' }); link.appendChild(b); }
      b.textContent = R.length ? String(R.length) : '';
      b.hidden = !R.length;
      b.title = R.length === 1 ? '1 Team braucht Hilfe' : R.length + ' Teams brauchen Hilfe';
    }
    orte.forEach(ort => { if (ort.isConnected) reiheZeichnen(ort); else orte.delete(ort); });
  }

  async function aktion(m, was) {
    try { R = (await T.api('POST', '/api/hilfe/' + m.id, { aktion: was })).reihe; bekannt = R.map(x => x.id); allesZeigen(); }
    catch (e) { T.meldung(e.message, true); abfragen(); }
  }

  function reiheZeichnen(ort) {
    ort.hidden = !R.length;
    T.setzen(ort,
      el('div', { class: 'zeile' }, T.symbol('hilfe'), el('h2', { text: 'Hilfe gerade' }), el('span', { class: 'chip rot', text: String(R.length) })),
      R.map(m => el('div', { class: 'hilfe-zeile' },
        el('span', { class: 'hilfe-nr', text: String(m.nr) }),
        el('span', {}, el('a', { href: '#projekt/' + m.projekt_id, text: m.projekt }),
          el('span', { class: 'leise klein-text', text: ' · ' + [m.wer, seit(m.erstellt), m.kommt ? (m.kommt_ich ? 'du kommst' : m.kommt + ' kommt') : null]
            .filter(Boolean).join(' · ') })),
        el('span', { class: 'rechts zeile' },
          el('button', { type: 'button', class: m.kommt_ich ? 'an' : '', 'aria-pressed': m.kommt_ich ? 'true' : 'false',
            onclick: () => aktion(m, 'kommen') }, 'Ich komme'),
          el('button', { type: 'button', onclick: () => aktion(m, 'erledigt') }, 'Erledigt')))));
  }

  // Karte oben im Cockpit; versteckt, solange niemand Hilfe braucht
  function reiheKarte() {
    const ort = el('section', { class: 'karte hilfe-reihe', hidden: true });
    orte.add(ort);
    reiheZeichnen(ort);
    return ort;
  }

  function lehrerBeobachten() {
    abfragen();
    setInterval(abfragen, 10000);
  }

  return { teamKnopf, lehrerBeobachten, reiheKarte };
})();
