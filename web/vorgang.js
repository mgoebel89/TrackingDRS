// Vorgaenge mit Gespraechsverlauf (wie ein Ticket): Eingang der Lehrkraft (#anfragen, links die Liste, rechts der
// Verlauf mit Antwortfeld) und fuer das Team die Liste und der Verlauf im Reiter "Anfragen".
// Verlauf: Nachrichten (Team links, Lehrkraft rechts), interne Notizen (gelb, nur Lehrkraefte) und Ereignisse.
'use strict';

const Vorgang = (() => {
  const el = T.el;
  const ARTEN = { rueckfrage: 'Rückfrage', ausleihe: 'Ausleihe', abnahme: 'Abnahme', bestellung: 'Bestellliste' };
  const STAND = { offen: 'offen', bearbeitung: 'in Bearbeitung', erledigt: 'erledigt' };
  const SCHRITT = { neu: 'erneut angefragt', beantwortet: 'beantwortet', bereitgelegt: 'bereitgelegt', ausgegeben: 'ausgegeben',
    zurueck: 'zurückgegeben', abgelehnt: 'abgelehnt', freigegeben: 'freigegeben', nachbessern: 'nachbessern', zurueckgezogen: 'zurückgezogen' };
  const WEG = { bestellen: 'wird bestellt', lager: 'aus dem SchulLager', firma: 'über die Firma', ersetzen: 'ersetzt', ablehnen: 'abgelehnt' };
  const datum = text => text ? text.slice(8, 10) + '.' + text.slice(5, 7) + '.' : '';
  const wer = n => n.wer_art === 'team' ? 'Team' : n.wer_art === 'system' ? 'System' : (n.wer || '').toUpperCase();

  function wann(zeit) {
    const heute = T.isoDatum(new Date());
    return zeit.slice(0, 10) === heute ? zeit.slice(11, 16) : T.kurzTag(zeit) + ' ' + zeit.slice(11, 16);
  }

  function ereignisText(n) {
    const d = n.daten || {};
    switch (d.was) {
      case 'stand': return n.wer_art === 'team' && d.stand === 'offen' ? 'Team hat den Vorgang wieder geöffnet'
        : wer(n) + ' hat den Status auf „' + STAND[d.stand] + '“ gesetzt';
      case 'zustaendig': return d.kuerzel ? d.kuerzel + ' hat den Vorgang übernommen' : wer(n) + ' hat den Vorgang abgegeben';
      case 'status': return wer(n) + ': ' + (SCHRITT[d.status] || d.status);
      case 'tafel': return 'Soll in der Besprechung geklärt werden (liegt als Frage auf der Tafel)';
      case 'geklaert': return 'In der Besprechung am ' + datum(d.datum) + ' geklärt';
      case 'sonderfenster': return wer(n) + ' hat ein Sonderfenster für die Bestellliste geöffnet, bis ' + T.zeitpunkt(d.bis);
      case 'position': return '„' + d.artikel + '“: ' + (d.entscheidung === 'ersetzen' ? (d.ersatz ? 'ersetzt durch ' + d.ersatz : 'Ersatz gesucht')
        : WEG[d.entscheidung]) + (d.menge ? ' (Menge ' + d.menge + ')' : '') + (d.kommentar ? ' – ' + d.kommentar : '');
      case 'position_status': return '„' + d.artikel + '“: ' + (d.status || 'Status zurückgesetzt');
      case 'geprueft': return wer(n) + ' hat die Liste fertig geprüft';
      default: return d.was || 'Änderung';
    }
  }

  // Verlauf: Eroeffnung, dann Nachrichten und Ereignisse
  function verlauf(v, bildBasis, rolle) {
    const eroeffnung = v.art === 'bestellung' ? null : el('div', { class: 'vg-n team' },
      el('div', { class: 'vg-kopf' }, el('b', { text: 'Team' }), ' hat die Anfrage gestellt · ' + wann(v.erstellt)),
      el('div', { class: 'vg-blase' },
        el('b', { text: v.titel }),
        v.art === 'ausleihe' ? el('div', { class: 'leise', text: v.menge + ' · ' + datum(v.von) + ' bis ' + datum(v.bis) }) : null,
        v.text ? el('div', { class: 'vortext', text: v.text }) : null,
        v.aufgabe ? el('div', { class: 'leise klein-text', text: 'Aufgabe: ' + v.aufgabe }) : null,
        v.bild ? el('img', { class: 'vg-bild', src: bildBasis + '/bild/' + v.bild, alt: 'Foto', onclick: () => gross(bildBasis + '/bild/' + v.bild) }) : null));
    return el('div', { class: 'vg-verlauf' }, eroeffnung, v.verlauf.map(n => n.art === 'ereignis'
      ? el('div', { class: 'vg-ereignis' }, el('span', { text: ereignisText(n) }), el('span', { class: 'leise', text: ' · ' + wann(n.zeit) }))
      : el('div', { class: 'vg-n ' + (n.art === 'intern' ? 'intern' : n.wer_art === 'team' ? 'team' : 'lehrkraft') + (rolle === n.wer_art ? ' ich' : '') },
        el('div', { class: 'vg-kopf' }, el('b', { text: wer(n) }), n.art === 'intern' ? el('span', { class: 'chip', text: 'intern' }) : null, ' · ' + wann(n.zeit)),
        el('div', { class: 'vg-blase' }, n.text ? el('div', { class: 'vortext', text: n.text }) : null,
          n.bild ? el('img', { class: 'vg-bild', src: bildBasis + '/bild/' + n.bild, alt: 'Foto', onclick: () => gross(bildBasis + '/bild/' + n.bild) }) : null))));
  }

  function gross(url) {
    const huelle = el('div', { class: 'tafel-ansicht bild', onclick: () => huelle.remove() },
      el('img', { src: url, alt: 'Foto' }), el('div', { class: 'tafel-leiste', text: 'antippen zum Schließen' }));
    document.body.appendChild(huelle);
  }

  // Antwortfeld. senden({text, intern, bild}, erledigt) -> Promise<bool>
  function antwortfeld(rolle, senden) {
    const text = el('textarea', { rows: '3', maxlength: '4000', placeholder: rolle === 'lehrkraft' ? 'Antwort an das Team …' : 'Nachricht an die Lehrkraft …',
      'aria-label': 'Nachricht' });
    const intern = el('input', { type: 'checkbox' });
    const foto = el('input', { type: 'file', accept: 'image/*', hidden: true });
    const knopf = el('button', { type: 'button', class: 'haupt' }, 'Senden');
    const markieren = () => { knopf.textContent = intern.checked ? 'Notiz speichern' : 'Senden'; text.classList.toggle('intern', intern.checked); };
    intern.addEventListener('change', markieren);
    const los = async (erledigt, bild) => {
      if (!text.value.trim() && !bild) { text.focus(); return; }
      knopf.disabled = true;
      if (await senden({ text: text.value, intern: intern.checked, bild }, erledigt)) { text.value = ''; intern.checked = false; markieren(); }
      knopf.disabled = false;
    };
    knopf.addEventListener('click', () => los(false));
    text.addEventListener('keydown', ev => { if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); los(false); } });
    foto.addEventListener('change', async () => {
      if (!foto.files.length) return;
      try { await los(false, await Besprechung.verkleinern(foto.files[0])); } catch (e) { T.meldung('Das Foto konnte nicht gelesen werden.', true); }
      foto.value = '';
    });
    return el('div', { class: 'vg-antwort' }, text,
      el('div', { class: 'zeile' },
        rolle === 'lehrkraft' ? el('label', { class: 'haken' }, intern, 'Interne Notiz (nur Lehrkräfte)') : null,
        el('button', { type: 'button', class: 'leicht', onclick: () => foto.click() }, '📷 Foto'), foto,
        el('span', { class: 'rechts' },
          rolle === 'lehrkraft' ? el('button', { type: 'button', onclick: () => los(true) }, 'Senden & erledigt') : null, knopf)),
      el('div', { class: 'leise klein-text', text: 'Strg + Enter sendet.' }));
  }

  function standChip(v) {
    return el('span', { class: 'chip vg-stand ' + v.stand, text: STAND[v.stand] });
  }

  function vorschau(v, rolle) {
    const l = v.letzte;
    if (!l) return v.art === 'bestellung' ? (v.positionen ? v.positionen + ' Positionen' : 'eingereicht') : 'Team: ' + (v.text || v.titel);
    return (l.wer_art === 'team' ? 'Team' : l.wer.toUpperCase()) + (l.intern && rolle === 'lehrkraft' ? ' (intern)' : '') + ': ' + (l.text || 'Foto');
  }

  // --- Lehrkraft: Eingang ---

  async function eingang(aid) {
    titelSetzen('Anfragen');
    const F = S.eingang || (S.eingang = { filter: 'aktiv', projekt: '', art: '' });
    const liste = el('div', { class: 'vg-liste' });
    const detail = el('div', { class: 'vg-detail' });
    const rahmen = el('div', { class: 'eingang' + (aid ? ' mit-detail' : '') }, el('div', { class: 'vg-links' }, filterLeiste(), liste), detail);
    let L = [];

    function filterLeiste() {
      const wahl = (wert, optionen, name) => {
        const s = el('select', { class: 'klein', 'aria-label': name, onchange: ev => { F[name] = ev.target.value; listeLaden(); } },
          optionen.map(([v, t]) => el('option', { value: v, text: t })));
        s.value = wert;
        return s;
      };
      const chips = el('div', { class: 'umschalter vg-filter' }, [['aktiv', 'Aktiv'], ['offen', 'Offen'], ['bearbeitung', 'In Bearbeitung'],
        ['meine', 'Meine'], ['erledigt', 'Erledigt'], ['alle', 'Alle']].map(([k, t]) => el('button', { type: 'button', class: F.filter === k ? 'an' : '',
        onclick: ev => { F.filter = k; chips.querySelectorAll('button').forEach(b => b.classList.toggle('an', b === ev.currentTarget)); listeLaden(); } }, t)));
      return el('div', { class: 'stapel-eng' }, chips,
        el('div', { class: 'zeile' }, F.projektWahl = wahl(F.projekt, [['', 'Alle Teams']], 'projekt'),
          wahl(F.art, [['', 'Alle Arten']].concat(Object.entries(ARTEN)), 'art')));
    }

    async function listeLaden() {
      try {
        const q = '?filter=' + F.filter + (F.projekt ? '&projekt=' + F.projekt : '') + (F.art ? '&art=' + F.art : '');
        const r = await T.api('GET', '/api/vorgaenge' + q);
        L = r.vorgaenge;
        zaehlerZeigen(r.zaehler);
        listeZeichnen();
      } catch (e) { T.setzen(liste, el('div', { class: 'leer', text: e.message })); }
    }

    function listeZeichnen() {
      // Teams fuer den Filter aus der Liste sammeln (einmal gefuellt bleibt die Auswahl)
      if (F.projektWahl.options.length <= 1) {
        const teams = [...new Map(L.map(v => [v.projekt_id, v.projekt])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
        teams.forEach(([id, t]) => F.projektWahl.appendChild(el('option', { value: String(id), text: t })));
        F.projektWahl.value = F.projekt;
      }
      T.setzen(liste, L.length ? L.map(v => el('a', { class: 'vg-zeile' + (v.ungelesen ? ' neu' : '') + (v.id === aid ? ' an' : ''), href: '#anfragen/v/' + v.id },
        el('div', { class: 'zeile' }, v.ungelesen ? el('span', { class: 'vg-punkt', title: 'ungelesen' }) : null,
          el('span', { class: 'chip', text: ARTEN[v.art] }), el('span', { class: 'vg-titel', text: v.titel })),
        el('div', { class: 'zeile leise klein-text' }, el('span', { text: v.projekt }), standChip(v), v.zustaendig ? el('span', { text: v.zustaendig }) : null,
          v.ueberfaellig ? el('span', { class: 'chip rot', text: 'Rückgabe überfällig' }) : null, el('span', { class: 'rechts', text: wann(v.geaendert) })),
        el('div', { class: 'vg-vorschau', text: vorschau(v, 'lehrkraft') })))
        : el('div', { class: 'leer', text: F.filter === 'aktiv' ? 'Keine offenen Vorgänge.' : 'Nichts gefunden.' }));
    }

    async function detailLaden(stumm) {
      if (!aid) { T.setzen(detail, el('div', { class: 'leer vg-leer', text: 'Links einen Vorgang wählen.' })); return; }
      try {
        const v = (await T.api('GET', '/api/vorgaenge/' + aid)).vorgang;
        detailZeichnen(v, stumm);
      } catch (e) { T.setzen(detail, el('div', { class: 'leer', text: e.message })); }
    }

    async function aktion(daten, meldung) {
      try {
        const v = (await T.api('POST', '/api/vorgaenge/' + aid, daten)).vorgang;
        detailZeichnen(v);
        if (meldung) T.meldung(meldung);
        listeLaden();
        return true;
      } catch (e) { T.meldung(e.message, true); return false; }
    }

    async function schritt(v, status, frage) {
      let text = '';
      if (frage) {
        const feld = el('textarea', { rows: '4', maxlength: '4000', required: true });
        const ok = await T.dialog({ titel: v.titel, knopf: frage, inhalt: el('div', { class: 'felder' }, T.feld('Hinweis für das Team', feld)),
          speichern: () => { text = feld.value; return true; } });
        if (!ok) return;
      }
      aktion({ aktion: 'status', status, text }, 'Gespeichert.');
    }

    function aktionen(v) {
      const k = (t, f, haupt) => el('button', { type: 'button', class: haupt ? 'haupt' : '', onclick: f }, t);
      const liste_ = [];
      if (v.art === 'ausleihe') {
        if (['neu'].includes(v.status)) liste_.push(k('Bereitlegen', () => schritt(v, 'bereitgelegt')), k('Ausgeben', () => schritt(v, 'ausgegeben')),
          k('Ablehnen', () => schritt(v, 'abgelehnt', 'Ablehnen')));
        if (v.status === 'bereitgelegt') liste_.push(k('Ausgegeben', () => schritt(v, 'ausgegeben')));
        if (v.status === 'ausgegeben') liste_.push(k('Zurückgegeben', () => schritt(v, 'zurueck')));
      }
      if (v.art === 'abnahme' && v.status === 'neu') liste_.push(k('Freigeben', () => schritt(v, 'freigegeben')), k('Nachbessern', () => schritt(v, 'nachbessern', 'Zurückgeben')));
      if (v.art === 'bestellung') liste_.push(el('a', { class: 'knopf', href: '#anfragen/liste/' + v.bestellliste_id }, 'Liste prüfen'));
      if (v.art === 'rueckfrage' && v.stand !== 'erledigt') liste_.push(k('Sonderfenster öffnen', async () => {
        const b = (await T.api('GET', '/api/anfragen')).bestellung;
        if (await Anfragen.fensterDialog(b, v.projekt_id, v.id)) detailLaden();
      }));
      return liste_;
    }

    function detailZeichnen(v, stumm) {
      const verlaufOrt = verlauf(v, '/api/projekte/' + v.projekt_id, 'lehrkraft');
      const alt = detail.querySelector('.vg-antwort');
      if (stumm && alt) {   // beim Nachladen das Antwortfeld (mit angefangenem Text) behalten
        detail.querySelector('.vg-verlauf').replaceWith(verlaufOrt);
        const kopf = detail.querySelector('.vg-detail-kopf');
        if (kopf) kopf.replaceWith(detailKopf(v));
        return;
      }
      T.setzen(detail, detailKopf(v), verlaufOrt,
        antwortfeld('lehrkraft', (d, erledigt) => aktion({ aktion: 'nachricht', text: d.text, intern: d.intern, bild: d.bild })
          .then(ok => ok && erledigt ? aktion({ aktion: 'stand', stand: 'erledigt' }, 'Gesendet und erledigt.') : ok)));
      verlaufOrt.scrollTop = verlaufOrt.scrollHeight;
    }

    function detailKopf(v) {
      return el('div', { class: 'vg-detail-kopf stapel-eng' },
        el('div', { class: 'zeile' },
          el('a', { class: 'knopf klein vg-zurueck', href: '#anfragen' }, '‹ Liste'),
          el('span', { class: 'chip', text: ARTEN[v.art] }), el('h2', { text: v.titel })),
        el('div', { class: 'zeile' }, el('a', { href: '#projekt/' + v.projekt_id, text: v.projekt + ' · ' + v.klasse }), standChip(v),
          v.status !== 'neu' && v.art !== 'bestellung' ? el('span', { class: 'chip', text: SCHRITT[v.status] }) : null,
          el('span', { class: 'leise', text: v.zustaendig ? 'zuständig: ' + v.zustaendig.name : 'noch niemand zuständig' }),
          el('span', { class: 'rechts' },
            v.zustaendig && v.zustaendig.kuerzel === S.konto.kuerzel.toUpperCase()
              ? el('button', { type: 'button', class: 'leicht', onclick: () => aktion({ aktion: 'abgeben' }, 'Abgegeben.') }, 'Abgeben')
              : el('button', { type: 'button', onclick: () => aktion({ aktion: 'uebernehmen' }, 'Übernommen.') }, 'Übernehmen'),
            v.stand === 'erledigt' ? el('button', { type: 'button', onclick: () => aktion({ aktion: 'stand', stand: 'offen' }, 'Wieder geöffnet.') }, 'Wieder öffnen')
              : el('button', { type: 'button', onclick: () => aktion({ aktion: 'stand', stand: 'erledigt' }, 'Erledigt.') }, 'Erledigt'))),
        aktionen(v).length ? el('div', { class: 'zeile' }, aktionen(v)) : null);
    }

    T.setzen(inhalt, Anfragen.kopf('eingang'), rahmen);
    await Promise.all([listeLaden(), detailLaden()]);
    const timer = setInterval(() => {
      if (!rahmen.isConnected) { clearInterval(timer); return; }
      if (document.visibilityState !== 'visible' || document.querySelector('dialog[open]')) return;
      listeLaden();
      if (aid) detailLaden(true);
    }, 15000);
  }

  // Zahl im Menue (ungelesen, sonst offen)
  function zaehlerZeigen(z) {
    const link = document.querySelector('nav.seite a[data-ansicht="anfragen"]');
    if (!link) return;
    let b = link.querySelector('.nav-zahl');
    if (!b) { b = el('span', { class: 'nav-zahl' }); link.appendChild(b); }
    const n = z.ungelesen || z.offen;
    b.textContent = n ? String(n) : '';
    b.hidden = !n;
    b.classList.toggle('neu', !!z.ungelesen);
    b.title = z.ungelesen ? z.ungelesen + ' ungelesen' : z.offen + ' offen';
  }

  async function zaehlerLaden() {
    try { zaehlerZeigen(await T.api('GET', '/api/vorgaenge/zaehler')); } catch (e) { /* naechster Versuch */ }
  }

  // --- Team ---

  function teamListe(liste, oeffnen) {
    if (!liste.length) return el('div', { class: 'leise klein-text', text: 'Noch keine Anfragen.' });
    return el('div', { class: 'vg-liste' }, liste.map(v => el('button', { type: 'button', class: 'vg-zeile' + (v.ungelesen ? ' neu' : ''), onclick: () => oeffnen(v.id) },
      el('div', { class: 'zeile' }, v.ungelesen ? el('span', { class: 'vg-punkt', title: 'neue Antwort' }) : null,
        el('span', { class: 'chip', text: ARTEN[v.art] }), el('span', { class: 'vg-titel', text: v.titel }), standChip(v),
        v.ueberfaellig ? el('span', { class: 'chip rot', text: 'Rückgabe überfällig' }) : null),
      el('div', { class: 'vg-vorschau', text: vorschau(v, 'team') + ' · ' + wann(v.geaendert) }))));
  }

  function teamDetail({ ort, basis, id, zurueck, beiAenderung }) {
    async function senden(daten, meldung) {
      try {
        zeichnen((await T.api('POST', basis + '/vorgaenge/' + id, daten)).vorgang);
        if (meldung) T.meldung(meldung);
        if (beiAenderung) beiAenderung();
        return true;
      } catch (e) { T.meldung(e.message, true); return false; }
    }
    function zeichnen(v) {
      const verlaufOrt = verlauf(v, basis, 'team');
      T.setzen(ort, el('section', { class: 'karte stapel-eng vg-team' },
        el('div', { class: 'zeile' }, el('button', { type: 'button', class: 'leicht', onclick: zurueck }, '‹ Alle Anfragen'),
          el('span', { class: 'chip', text: ARTEN[v.art] }), el('h2', { text: v.titel }), standChip(v)),
        el('div', { class: 'zeile leise klein-text' }, v.zustaendig ? 'zuständig: ' + v.zustaendig.name : 'noch niemand zuständig',
          v.stand === 'offen' && v.art !== 'bestellung' ? el('button', { type: 'button', class: 'leicht', onclick: () => senden({ aktion: 'zurueckziehen' }, 'Zurückgezogen.') }, 'Zurückziehen') : null,
          v.status === 'nachbessern' ? el('button', { type: 'button', onclick: () => senden({ aktion: 'erneut' }, 'Erneut angefragt.') }, 'Nachgebessert, erneut anfragen') : null),
        verlaufOrt,
        antwortfeld('team', d => senden({ aktion: 'nachricht', text: d.text, bild: d.bild }, 'Gesendet.'))));
      verlaufOrt.scrollTop = verlaufOrt.scrollHeight;
    }
    (async () => {
      try { zeichnen((await T.api('GET', basis + '/vorgaenge/' + id)).vorgang); if (beiAenderung) beiAenderung(); }
      catch (e) { T.setzen(ort, el('div', { class: 'leer', text: e.message })); }
    })();
  }

  return { eingang, zaehlerLaden, zaehlerZeigen, teamListe, teamDetail };
})();
