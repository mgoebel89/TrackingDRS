// Lehrernotizen als gemeinsamer Zeitstrahl (Stufe J5), Menuepunkt "Notizen" (#notizen, #notizen/projekt/<id>).
// Nur fuer Lehrkraefte. Neueste oben, nach Tag gruppiert; kompakte Karte mit Ueberschrift, "Erweitern" zeigt den vollen
// Text. Dringlichkeit Normal oder Dringend; dringende, die man noch nicht aufgeklappt hat, zaehlen am Menuepunkt.
'use strict';

const Notizen = (() => {
  const el = T.el;
  const F = { art: 'alle', projekt: '', such: '' };   // Filter bleiben beim Wechseln der Seite erhalten
  const offen = new Set();
  let bekannt = null;

  const tagText = zeit => {
    const heute = T.isoDatum(new Date());
    const gestern = T.isoDatum(new Date(Date.now() - 864e5));
    const d = zeit.slice(0, 10);
    return d === heute ? 'Heute' : d === gestern ? 'Gestern' : T.kurzTag(d);
  };

  async function zeigen(projektId) {
    titelSetzen('Notizen');
    F.projekt = projektId ? String(projektId) : '';   // aus dem Menue: alle, von der Projektseite: dieses Projekt
    let D = await T.api('GET', '/api/notizen');
    const strahl = el('div', { class: 'n-strahl' });
    const werkzeug = el('div', { class: 'n-werkzeug' });

    async function senden(pfad, daten, meldung) {
      try { D = await T.api('POST', pfad, daten); zeichnen(); if (meldung) T.meldung(meldung); zaehlerZeigen(D.dringend_ungelesen); return true; }
      catch (e) { T.meldung(e.message, true); return false; }
    }

    function passt(n) {
      if (F.art === 'dringend' && !n.dringend) return false;
      if (F.projekt === '-' ? n.projekt_id : F.projekt && String(n.projekt_id) !== F.projekt) return false;
      if (F.such && !(n.ueberschrift + ' ' + n.text + ' ' + (n.projekt || '') + ' ' + n.wer).toLowerCase().includes(F.such)) return false;
      return true;
    }

    async function dialog(n) {
      const f = {
        ue: el('input', { required: true, maxlength: '120', value: n ? n.ueberschrift : '', placeholder: 'z. B. Klimaanlage: Lüfter erst nach Freigabe bestellen' }),
        text: el('textarea', { rows: '6', maxlength: '10000', value: n ? n.text : '', placeholder: 'Was die anderen wissen sollten …' }),
        projekt: el('select', {}, el('option', { value: '', text: 'kein Projekt (gilt für alle)' }),
          D.projekte.map(p => el('option', { value: String(p.id), text: p.titel + ' · ' + p.klasse }))),
      };
      let dringend = n ? n.dringend : false;
      const segment = el('div', { class: 'n-segment', role: 'radiogroup', 'aria-label': 'Dringlichkeit' });
      const segZeichnen = () => T.setzen(segment, [[false, 'Normal'], [true, 'Dringend']].map(([w, t]) => el('button', { type: 'button',
        role: 'radio', 'aria-checked': dringend === w ? 'true' : 'false', class: (dringend === w ? 'an' : '') + (w ? ' rot' : ''),
        onclick: () => { dringend = w; segZeichnen(); } }, t)));
      segZeichnen();
      f.projekt.value = n ? String(n.projekt_id || '') : (F.projekt && F.projekt !== '-' ? F.projekt : '');
      const ok = await T.dialog({ titel: n ? 'Notiz bearbeiten' : 'Neue Notiz', knopf: 'Speichern',
        inhalt: el('div', { class: 'felder' }, T.feld('Überschrift', f.ue), T.feld('Text', f.text),
          el('div', { class: 'felder zwei' }, T.feld('Dringlichkeit', segment), T.feld('Projekt', f.projekt)),
          el('p', { class: 'leise klein-text', text: 'Alle Lehrkräfte sehen die Notiz. Das Team sieht sie nie.' })),
        speichern: async () => {
          const daten = { ueberschrift: f.ue.value, text: f.text.value, dringend, projekt_id: f.projekt.value ? Number(f.projekt.value) : null };
          D = await T.api('POST', n ? '/api/notizen/' + n.id : '/api/notizen', n ? Object.assign({ aktion: 'aendern' }, daten) : daten);
          return true;
        } });
      if (ok) { zeichnen(); T.meldung(n ? 'Gespeichert.' : 'Notiz gespeichert. Alle Lehrkräfte sehen sie.'); }
    }

    async function verwerfen(n) {
      const ok = await T.dialog({ titel: 'Notiz verwerfen?', knopf: 'Verwerfen', gefaehrlich: true,
        inhalt: el('p', { text: '„' + n.ueberschrift + '“ verschwindet aus dem Zeitstrahl.' }),
        speichern: async () => { D = await T.api('POST', '/api/notizen/' + n.id, { aktion: 'verwerfen' }); return true; } });
      if (ok) { zeichnen(); T.meldung('Notiz verworfen.'); }
    }

    async function umschalten(n, schluessel) {
      if (offen.has(schluessel)) { offen.delete(schluessel); zeichnen(); return; }
      offen.add(schluessel);
      if (n.id && !n.gelesen) {
        n.gelesen = true;
        try { zaehlerZeigen((await T.api('POST', '/api/notizen/' + n.id, { aktion: 'gelesen' })).dringend_ungelesen); } catch (e) { /* egal */ }
        D.dringend_ungelesen = D.notizen.filter(x => x.dringend && !x.gelesen).length;
      }
      zeichnen();
    }

    function karte(n) {
      const schluessel = n.id ? 'n' + n.id : 'b' + n.projekt_id + n.woche;
      const auf = offen.has(schluessel);
      return el('article', { class: 'n-karte' + (n.dringend ? ' dringend' : '') + (n.art === 'besprechung' ? ' bespr' : '') },
        el('div', { class: 'n-kopf' },
          n.dringend ? el('span', { class: 'n-dringend', text: 'Dringend' }) : null,
          el('h3', { text: n.ueberschrift }),
          el('button', { type: 'button', class: 'n-erweitern', 'aria-expanded': auf ? 'true' : 'false', onclick: () => umschalten(n, schluessel) },
            auf ? 'Einklappen' : 'Erweitern')),
        el('div', { class: 'n-meta' },
          n.wer ? el('span', { text: n.wer }) : null, el('span', { text: n.erstellt.slice(11, 16) }),
          el('span', { class: 'chip', text: n.projekt || 'alle Projekte' }),
          n.art === 'besprechung' ? el('span', { text: 'aus der Besprechung' }) : null,
          n.geaendert ? el('span', { text: 'geändert ' + T.zeitText(n.geaendert) }) : null,
          n.dringend && !n.gelesen ? el('span', { class: 'n-neu', text: '● neu' }) : null),
        auf ? el('div', { class: 'n-voll' },
          el('div', { class: 'vortext', text: n.text || '(ohne Text)' }),
          n.eigen ? el('div', { class: 'zeile' }, el('button', { type: 'button', class: 'leicht', onclick: () => dialog(n) }, 'Bearbeiten'),
            el('button', { type: 'button', class: 'leicht', onclick: () => verwerfen(n) }, 'Verwerfen')) : null,
          n.art === 'besprechung' ? el('a', { class: 'knopf klein', href: '#projekt/' + n.projekt_id + '/besprechung' }, 'Zur Besprechung') : null) : null);
    }

    function zeichnen() {
      const dringende = D.notizen.filter(n => n.dringend).length;
      const fk = (art, text) => el('button', { type: 'button', class: 'fk' + (F.art === art ? ' an' : ''), 'aria-pressed': F.art === art ? 'true' : 'false',
        onclick: () => { F.art = art; zeichnen(); } }, text);
      const projekt = el('select', { class: 'klein', 'aria-label': 'Projekt', onchange: ev => { F.projekt = ev.target.value; zeichnen(); } },
        el('option', { value: '', text: 'Alle Projekte' }), el('option', { value: '-', text: 'ohne Projekt' }),
        D.projekte.map(p => el('option', { value: String(p.id), text: p.titel })));
      projekt.value = F.projekt;
      const such = el('input', { type: 'search', class: 'n-such', placeholder: 'Suchen …', 'aria-label': 'Notizen durchsuchen', value: F.such });
      such.addEventListener('input', () => { F.such = such.value.trim().toLowerCase(); listeZeichnen(); });
      T.setzen(werkzeug, el('button', { type: 'button', class: 'haupt', onclick: () => dialog(null) }, '+ Neue Notiz'),
        fk('alle', 'Alle'), fk('dringend', ['Nur dringende ', el('i', { text: String(dringende) })]), projekt, el('span', { class: 'rechts' }, such));
      listeZeichnen();
    }

    function listeZeichnen() {
      const liste = D.notizen.filter(passt);
      const teile = [];
      let tag = null;
      liste.forEach(n => {
        const t = tagText(n.erstellt);
        if (t !== tag) { tag = t; teile.push(el('div', { class: 'n-tag', text: t })); }
        teile.push(karte(n));
      });
      T.setzen(strahl, teile.length ? teile : el('div', { class: 'leer', text: D.notizen.length ? 'Keine Notiz passt zum Filter.'
        : 'Noch keine Notizen. Mit „+ Neue Notiz“ schreibst du etwas, das alle Lehrkräfte sehen.' }));
    }

    T.setzen(inhalt, el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Notizen' }),
      el('span', { class: 'leise', text: 'Austausch unter Lehrkräften · das Team sieht davon nichts' })), werkzeug, strahl);
    zeichnen();
    zaehlerZeigen(D.dringend_ungelesen);
  }

  function zaehlerZeigen(n) {
    const link = document.querySelector('nav.seite a[data-ansicht="notizen"]');
    if (!link) return;
    let b = link.querySelector('.nav-zahl');
    if (!b) { b = el('span', { class: 'nav-zahl neu' }); link.appendChild(b); }
    b.textContent = n ? String(n) : '';
    b.hidden = !n;
    b.title = n === 1 ? '1 dringende Notiz' : n + ' dringende Notizen';
  }

  async function abfragen() {
    let z;
    try { z = await T.api('GET', '/api/notizen/zaehler'); } catch (e) { return; }
    zaehlerZeigen(z.dringend_ungelesen);
    if (bekannt) z.neu.filter(n => !bekannt.includes(n.id)).forEach(n => {
      T.meldung('Dringende Notiz: ' + n.ueberschrift, false, '#notizen');
      Vorgang.windowsHinweis('Dringende Notiz', n.ueberschrift, '#notizen', 'tdrs-notiz-' + n.id);
    });
    bekannt = z.neu.map(n => n.id);
  }

  function beobachten() {
    abfragen();
    setInterval(abfragen, 60000);
  }

  return { zeigen, beobachten };
})();
