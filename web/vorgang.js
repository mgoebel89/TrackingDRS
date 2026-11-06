// Vorgaenge mit Gespraechsverlauf (wie ein Ticket): Eingang der Lehrkraft (#anfragen, links die Liste, rechts der
// Verlauf mit Antwortfeld) und fuer das Team die Liste und der Verlauf im Reiter "Anfragen".
// Verlauf: Nachrichten (Team links, Lehrkraft rechts), interne Notizen (gelb, nur Lehrkraefte) und Ereignisse.
'use strict';

const Vorgang = (() => {
  const el = T.el;
  const ARTEN = { rueckfrage: 'Rückfrage', ausleihe: 'Ausleihe', abnahme: 'Abnahme', bestellung: 'Bestellliste' };
  const ART_SYMBOL = { rueckfrage: 'frage', ausleihe: 'material', abnahme: 'abnahme', bestellung: 'liste' };
  const STAND = { offen: 'neu', bearbeitung: 'in Bearbeitung', erledigt: 'erledigt' };   // intern heisst "neu" offen
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
      case 'stand': return n.wer_art === 'team' && d.alt === 'erledigt' ? 'Team hat wieder geschrieben: ' + STAND[d.stand]
        : wer(n) + ' hat den Status auf „' + STAND[d.stand] + '“ gesetzt';
      case 'zustaendig': return !d.kuerzel ? wer(n) + ': niemand mehr zuständig'
        : d.von ? d.von + ' hat ' + (d.name || d.kuerzel) + ' zugewiesen' : (d.name || d.kuerzel) + ' hat den Vorgang übernommen';
      case 'firma': return '„' + d.artikel + '“: ' + ({ zugesagt: d.name + ' besorgt es über die Firma',
        nein: 'über die Firma nicht möglich, bitte neu entscheiden', besorgt: 'über die Firma besorgt und mitgebracht' })[d.firma];
      case 'status': return wer(n) + ': ' + (SCHRITT[d.status] || d.status);
      case 'wieder_geoeffnet': return 'Vom Team wieder geöffnet';
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
        v.aufgabe ? el('div', { class: 'leise klein-text', text: 'Tätigkeit: ' + v.aufgabe }) : null,
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

  // Auswahl "Zustaendig" (Zeile im Eingang und Kopf des Vorgangs): "Ich übernehme" oben, darunter die anderen Lehrkraefte,
  // die das Projekt betreuen. Zuweisen setzt "in Bearbeitung", "niemand" wieder "neu".
  function zustaendigWahl(v, betreuer, danach, kurz) {
    const ich = S.konto.id, jetzt = v.zustaendig_id != null ? v.zustaendig_id : (v.zustaendig && v.zustaendig.id);
    const name = b => b.id === ich ? (kurz ? 'Ich' : 'Ich (' + b.name + ')') : b.name;
    const s = el('select', { class: 'zust-wahl' + (jetzt ? ' gesetzt' : ''), 'aria-label': 'Zuständig',
      title: 'Zuständig für diesen Vorgang', onclick: ev => ev.stopPropagation(), onkeydown: ev => ev.stopPropagation(),
      onchange: async ev => {
        try {
          await T.api('POST', '/api/projekte/' + v.projekt_id + '/vorgaenge/' + v.id, { aktion: 'zuweisen', lehrkraft_id: ev.target.value ? Number(ev.target.value) : null });
          T.meldung(ev.target.value ? (Number(ev.target.value) === ich ? 'Übernommen.' : 'Zugewiesen.') : 'Niemand mehr zuständig.');
        } catch (e) { T.meldung(e.message, true); }
        danach();
      } },
    el('option', { value: '', text: kurz ? 'niemand' : 'Zuständig: niemand' }),
    betreuer.some(b => b.id === ich) && jetzt !== ich ? el('option', { value: String(ich), text: 'Ich übernehme' }) : null,
    betreuer.filter(b => b.id !== ich || jetzt === ich).map(b => el('option', { value: String(b.id), text: name(b) })),
    jetzt && !betreuer.some(b => b.id === jetzt)
      ? el('option', { value: String(jetzt), text: (v.zustaendig && v.zustaendig.name || v.zustaendig || '?') + ' (betreut das Projekt nicht mehr)' }) : null);
    s.value = jetzt ? String(jetzt) : '';
    return s;
  }

  function vorschau(v, rolle) {
    const l = v.letzte;
    if (!l) return v.art === 'bestellung' ? (v.positionen ? v.positionen + ' Positionen' : 'eingereicht') : 'Team: ' + (v.text || v.titel);
    return (l.wer_art === 'team' ? 'Team' : l.wer.toUpperCase()) + (l.intern && rolle === 'lehrkraft' ? ' (intern)' : '') + ': ' + (l.text || 'Foto');
  }

  // --- Lehrkraft: Eingang ---

  // opt (Projektseite): {projektId, ort, ziel} – nur dieses Projekt, eingebettet, Links auf ziel/<vorgang>
  async function eingang(aid, opt = {}) {
    if (!opt.ort) titelSetzen('Anfragen');
    const ziel = opt.ziel || '#anfragen';
    // Filter: Staende einzeln an/aus (beim Oeffnen neu + in Bearbeitung), "nur meine", Art als Knoepfe, Team
    const F = opt.projektId ? { staende: ['offen', 'bearbeitung'], meine: false, projekt: String(opt.projektId), art: '' }
      : S.eingang || (S.eingang = { staende: ['offen', 'bearbeitung'], meine: false, projekt: '', art: '' });
    const liste = el('div', { class: 'vg-liste' });
    const detail = el('div', { class: 'vg-detail' });
    const filter = el('div', { class: 'vg-filter-block' });
    const rahmen = el('div', { class: 'eingang' + (aid ? ' mit-detail' : '') }, el('div', { class: 'vg-links' }, filter, liste), detail);
    let L = [], Z = { offen: 0, bearbeitung: 0 }, B = {};

    function filterZeichnen() {
      const knopf = (an, inhalt, klick, titel) => el('button', { type: 'button', class: 'fk' + (an ? ' an' : ''), 'aria-pressed': an ? 'true' : 'false',
        title: titel || null, onclick: klick }, inhalt);
      const stand = (k, t) => knopf(F.staende.includes(k), [t, k !== 'erledigt' ? el('i', { text: String(Z[k] || 0) }) : null], () => {
        F.staende = F.staende.includes(k) ? F.staende.filter(x => x !== k) : F.staende.concat(k);
        listeLaden();
      });
      const teamWahl = el('select', { class: 'klein', 'aria-label': 'Team', hidden: !!opt.projektId,
        onchange: ev => { F.projekt = ev.target.value; listeLaden(); } }, el('option', { value: '', text: 'Alle Teams' }));
      const teams = [...new Map(L.map(v => [v.projekt_id, v.projekt])).entries()];
      if (F.projekt && !teams.some(([id]) => String(id) === F.projekt)) teams.push([Number(F.projekt), 'gewähltes Team']);
      teams.sort((a, b) => a[1].localeCompare(b[1])).forEach(([id, t]) => teamWahl.appendChild(el('option', { value: String(id), text: t })));
      teamWahl.value = F.projekt;
      T.setzen(filter,
        el('div', { class: 'filter-reihe' }, el('span', { class: 'etikett', text: 'Stand' }),
          stand('offen', 'Neu'), stand('bearbeitung', 'In Bearbeitung'), stand('erledigt', 'Erledigt'),
          knopf(F.meine, [T.symbol('person'), 'nur meine'], () => { F.meine = !F.meine; listeLaden(); }, 'nur Vorgänge, für die du zuständig bist')),
        el('div', { class: 'filter-reihe' }, el('span', { class: 'etikett', text: 'Art' }),
          Object.entries(ARTEN).filter(([k]) => k !== 'bestellung').map(([k, t]) => knopf(F.art === k, [T.symbol(ART_SYMBOL[k]), t], () => { F.art = F.art === k ? '' : k; listeLaden(); })),
          el('span', { class: 'rechts' }, teamWahl)));
    }

    async function listeLaden() {
      try {
        const q = '?staende=' + (F.staende.join(',') || '-') + (F.meine ? '&meine=1' : '') + (F.projekt ? '&projekt=' + F.projekt : '') +
          (F.art ? '&art=' + F.art : '');
        const r = await T.api('GET', '/api/vorgaenge' + q);
        L = r.vorgaenge; Z = r.zahlen; B = r.betreuer;
        zaehlerZeigen(r.zaehler);
        filterZeichnen();
        listeZeichnen();
      } catch (e) { T.setzen(liste, el('div', { class: 'leer', text: e.message })); }
    }

    function listeZeichnen() {
      const oeffnen = v => { location.hash = ziel + (opt.projektId ? '/' : '/v/') + v.id; };
      T.setzen(liste, L.length ? L.map(v => el('div', { class: 'vg-zeile lk' + (v.ungelesen ? ' neu' : '') + (v.id === aid ? ' an' : ''), role: 'link', tabindex: '0',
        onclick: () => oeffnen(v), onkeydown: ev => { if (ev.key === 'Enter') oeffnen(v); } },
        el('span', { class: 'art-sym ' + v.art, title: ARTEN[v.art] }, T.symbol(ART_SYMBOL[v.art])),
        el('div', { class: 'vg-mitte' },
          el('div', { class: 'zeile' }, v.ungelesen ? el('span', { class: 'vg-punkt', title: 'ungelesen' }) : null,
            el('span', { class: 'vg-titel', text: v.titel })),
          el('div', { class: 'zeile leise klein-text' }, el('span', { text: ARTEN[v.art] + ' · ' + v.projekt }),
            v.ueberfaellig ? el('span', { class: 'chip rot', text: 'Rückgabe überfällig' }) : null, el('span', { class: 'rechts', text: wann(v.geaendert) })),
          el('div', { class: 'vg-vorschau', text: vorschau(v, 'lehrkraft') })),
        el('div', { class: 'vg-rechts' }, standChip(v), zustaendigWahl(v, B[String(v.projekt_id)] || [], () => listeLaden(), true))))
        : el('div', { class: 'leer stapel-eng' }, el('b', { text: F.staende.length ? 'Gerade nichts zu tun.' : 'Kein Stand gewählt.' }),
          el('span', { class: 'leise klein-text', text: 'Anfragen kommen von den Teams: Rückfragen, Ausleihen und Abnahmen aus dem Reiter ' +
            '„Anfragen“ ihres Team-Links. Bestelllisten stehen unter „Bestellung“.' })));
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
      if (v.art === 'bestellung') liste_.push(el('a', { class: 'knopf', href: '#bestellung/liste/' + v.bestellliste_id }, 'Liste prüfen'));
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
          el('a', { class: 'knopf klein vg-zurueck', href: ziel }, '‹ Liste'),
          el('span', { class: 'art-sym ' + v.art, title: ARTEN[v.art] }, T.symbol(ART_SYMBOL[v.art])), el('h2', { text: v.titel })),
        el('div', { class: 'zeile' }, el('a', { href: '#projekt/' + v.projekt_id, text: v.projekt + ' · ' + v.klasse }), standChip(v),
          v.status !== 'neu' && v.art !== 'bestellung' ? el('span', { class: 'chip', text: SCHRITT[v.status] }) : null,
          zustaendigWahl(v, v.betreuer || [], () => { detailLaden(); listeLaden(); }),
          v.zustaendig && v.zustaendig.ehemalig ? el('span', { class: 'warnung-text klein-text', text: v.zustaendig.name + ' betreut das Projekt nicht mehr' }) : null,
          el('span', { class: 'rechts' },
            v.stand === 'erledigt' ? el('button', { type: 'button', onclick: () => aktion({ aktion: 'stand', stand: 'offen' }, 'Wieder geöffnet.') }, 'Wieder öffnen')
              : el('button', { type: 'button', onclick: () => aktion({ aktion: 'stand', stand: 'erledigt' }, 'Erledigt.') }, 'Erledigt'))),
        aktionen(v).length ? el('div', { class: 'zeile' }, aktionen(v)) : null);
    }

    if (opt.ort) T.setzen(opt.ort, rahmen); else T.setzen(inhalt, Anfragen.kopf(), rahmen);
    filterZeichnen();
    await detailLaden();   // erst lesen, dann Liste und Zaehler (sonst zaehlt der gerade geoeffnete noch mit)
    await listeLaden();
    const timer = setInterval(() => {
      if (!rahmen.isConnected) { clearInterval(timer); return; }
      if (document.visibilityState !== 'visible' || document.querySelector('dialog[open]')) return;
      listeLaden();
      if (aid) detailLaden(true);
    }, 15000);
  }

  // Zahl im Menue (ungelesen, sonst offen)
  function zaehlerZeigen(z) {
    const reiter = document.querySelector('.gross-reiter .eingang-zahl');   // Reiter "Eingang" der Anfragen-Seite
    if (reiter) { reiter.textContent = z.ungelesen ? String(z.ungelesen) : ''; reiter.hidden = !z.ungelesen; }
    const link = document.querySelector('nav.seite a[data-ansicht="anfragen"]');
    if (!link) return;
    let b = link.querySelector('.nav-zahl');
    if (!b) { b = el('span', { class: 'nav-zahl' }); link.appendChild(b); }
    const n = z.ungelesen || z.offen;
    b.textContent = n ? String(n) : '';
    b.hidden = !n;
    b.classList.toggle('neu', !!z.ungelesen);
    b.title = z.ungelesen ? z.ungelesen + ' ungelesen' : z.offen + ' offen';
    T.titelZahl(z.ungelesen);
    letzter = z;
    projektZahlZeigen();
  }

  let letzter = null, projektLeiste = null;

  // Roter Zaehler am Reiter "Anfragen" der Projektseite: Ungelesenes dieses Projekts
  function projektZahl(leiste, pid) {
    projektLeiste = { leiste, pid };
    projektZahlZeigen();
  }

  function projektZahlZeigen() {
    if (!letzter || !projektLeiste || !projektLeiste.leiste.isConnected) return;
    const n = (letzter.neu || []).filter(v => v.projekt_id === projektLeiste.pid).length;
    T.reiterZahl(projektLeiste.leiste, n, n === 1 ? '1 ungelesen' : n + ' ungelesen');
  }

  // --- Melden: Zaehler im Menue und im Browser-Tab, Einblendung, Windows-Benachrichtigung ---
  // Abfrage jede Minute, auch wenn der Tab im Hintergrund liegt (dafuer ist die Benachrichtigung da). Die
  // Benachrichtigung kommt nur, solange die Seite irgendwo offen ist, und nur wenn sie gerade nicht vorne ist.

  const BENACHRICHTIGUNG = 'tdrs-benachrichtigung';

  function benachrichtigungAn() {
    if (!('Notification' in window) || Notification.permission !== 'granted') return false;
    try { return localStorage.getItem(BENACHRICHTIGUNG) !== 'aus'; } catch (e) { return true; }
  }

  function melden(v) {
    const text = v.projekt + ': ' + v.text;
    T.meldung('Neu bei Anfragen – ' + text, false, '#anfragen/v/' + v.id);
    if (!benachrichtigungAn() || (document.visibilityState === 'visible' && document.hasFocus())) return;
    try {
      const n = new Notification(T.NAME + ' · ' + v.projekt, { body: v.titel + '\n' + v.text, tag: 'tdrs-' + v.id });
      n.onclick = () => { window.focus(); location.hash = '#anfragen/v/' + v.id; n.close(); };
    } catch (e) { /* manche Browser erlauben das nur ueber einen Service Worker */ }
  }

  // Windows-Hinweis fuer andere Meldungen (z. B. Hilfe-Knopf), mit demselben Schalter wie bei den Anfragen
  function windowsHinweis(titel, text, ziel, tag) {
    if (!benachrichtigungAn() || (document.visibilityState === 'visible' && document.hasFocus())) return;
    try {
      const n = new Notification(T.NAME + ' · ' + titel, { body: text, tag });
      n.onclick = () => { window.focus(); location.hash = ziel; n.close(); };
    } catch (e) { /* manche Browser erlauben das nur ueber einen Service Worker */ }
  }

  let zaehlerLaden = async () => {};

  function beobachten() {
    zaehlerLaden = T.beobachten(async () => { const z = await T.api('GET', '/api/vorgaenge/zaehler'); zaehlerZeigen(z); return z; }, melden);
  }

  // Knopf im Kopf der Anfragen: Windows-Benachrichtigung ein- und ausschalten
  function glocke() {
    if (!('Notification' in window)) return null;
    const ort = el('span', { class: 'glocke' });
    function zeichnen() {
      const erlaubt = Notification.permission;
      if (erlaubt === 'denied') {
        T.setzen(ort, el('span', { class: 'leise klein-text', title: 'In den Website-Einstellungen des Browsers wieder erlauben.',
          text: 'Benachrichtigungen im Browser blockiert' }));
        return;
      }
      const an = benachrichtigungAn();
      T.setzen(ort, el('button', { type: 'button', class: 'glocke-knopf' + (an ? ' an' : ''), 'aria-pressed': an ? 'true' : 'false',
        title: an ? 'Neue Anfragen melden sich auch als Windows-Benachrichtigung, solange diese Seite offen ist.'
          : 'Neue Anfragen zusätzlich als Windows-Benachrichtigung melden', onclick: umschalten },
      T.symbol(an ? 'glocke' : 'glocke_aus'), an ? 'Windows-Hinweise: an' : 'Windows-Hinweise: aus'));
    }
    async function umschalten() {
      if (benachrichtigungAn()) {
        try { localStorage.setItem(BENACHRICHTIGUNG, 'aus'); } catch (e) { /* ohne Speicher */ }
      } else {
        if (Notification.permission !== 'granted') await Notification.requestPermission();
        try { localStorage.setItem(BENACHRICHTIGUNG, 'an'); } catch (e) { /* ohne Speicher */ }
        if (benachrichtigungAn()) T.meldung('Neue Anfragen melden sich jetzt auch als Windows-Benachrichtigung, solange die Seite offen ist.');
      }
      zeichnen();
    }
    zeichnen();
    return ort;
  }

  // --- Team ---

  function teamListe(liste, oeffnen) {
    if (!liste.length) return el('div', { class: 'leise klein-text', text: 'Noch keine Anfragen.' });
    return el('div', { class: 'vg-liste' }, liste.map(v => el('button', { type: 'button', class: 'vg-zeile' + (v.ungelesen ? ' neu' : ''), onclick: () => oeffnen(v.id) },
      el('div', { class: 'zeile' }, v.ungelesen ? el('span', { class: 'vg-punkt', title: 'neue Antwort' }) : null,
        el('span', { class: 'art-sym ' + v.art, title: ARTEN[v.art] }, T.symbol(ART_SYMBOL[v.art])), el('span', { class: 'vg-titel', text: v.titel }),
        teamStand(v), v.ueberfaellig ? el('span', { class: 'chip rot', text: 'Rückgabe überfällig' }) : null),
      el('div', { class: 'vg-vorschau', text: vorschau(v, 'team') + ' · ' + wann(v.geaendert) }))));
  }

  // Fuer das Team: Stand und, sobald jemand zustaendig ist, der Name ("In Bearbeitung · Matthias Göbel")
  function teamStand(v) {
    const name = v.zustaendig_name || (v.zustaendig && v.zustaendig.name);
    return el('span', { class: 'chip vg-stand ' + v.stand, text: STAND[v.stand].replace(/^./, c => c.toUpperCase()) + (name && v.stand !== 'offen' ? ' · ' + name : '') });
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
    // J7: erledigte Anfrage mit Grund wieder oeffnen
    async function wiederOeffnen(v) {
      const grund = el('textarea', { rows: '3', maxlength: '4000', required: true, placeholder: 'z. B. Welche Sicherung sollen wir nehmen?' });
      const name = v.zustaendig && !v.zustaendig.ehemalig ? v.zustaendig.name : null;
      const ok = await T.dialog({ titel: 'Anfrage wieder öffnen', knopf: 'Wieder öffnen',
        inhalt: el('div', { class: 'felder' }, T.feld('Was ist noch offen?', grund,
          'Ein Satz reicht. Er geht als Nachricht an ' + (name || 'eure Lehrkräfte') + '.')),
        speichern: async () => { zeichnen((await T.api('POST', basis + '/vorgaenge/' + id, { aktion: 'wieder_oeffnen', text: grund.value })).vorgang); return true; } });
      if (ok) { T.meldung('Wieder geöffnet.'); if (beiAenderung) beiAenderung(); }
    }

    function zeichnen(v) {
      const verlaufOrt = verlauf(v, basis, 'team');
      T.setzen(ort, el('section', { class: 'karte stapel-eng vg-team' },
        el('div', { class: 'zeile' }, el('button', { type: 'button', class: 'leicht', onclick: zurueck }, '‹ Alle Anfragen'),
          el('span', { class: 'art-sym ' + v.art, title: ARTEN[v.art] }, T.symbol(ART_SYMBOL[v.art])), el('h2', { text: v.titel }), teamStand(v)),
        el('div', { class: 'zeile leise klein-text' }, v.zustaendig ? 'zuständig: ' + v.zustaendig.name : 'noch niemand zuständig',
          v.stand === 'offen' && v.art !== 'bestellung' ? el('button', { type: 'button', class: 'leicht', onclick: () => senden({ aktion: 'zurueckziehen' }, 'Zurückgezogen.') }, 'Zurückziehen') : null,
          v.status === 'nachbessern' ? el('button', { type: 'button', onclick: () => senden({ aktion: 'erneut' }, 'Erneut angefragt.') }, 'Nachgebessert, erneut anfragen') : null),
        verlaufOrt,
        v.stand === 'erledigt' ? el('div', { class: 'wieder-oeffnen' }, el('span', { text: 'Ist noch etwas offen?' }),
          el('button', { type: 'button', class: 'haupt', onclick: () => wiederOeffnen(v) }, T.symbol('zurueck'), 'Wieder öffnen')) : null,
        antwortfeld('team', d => senden({ aktion: 'nachricht', text: d.text, bild: d.bild }, 'Gesendet.'))));
      verlaufOrt.scrollTop = verlaufOrt.scrollHeight;
    }
    (async () => {
      try { zeichnen((await T.api('GET', basis + '/vorgaenge/' + id)).vorgang); if (beiAenderung) beiAenderung(); }
      catch (e) { T.setzen(ort, el('div', { class: 'leer', text: e.message })); }
    })();
  }

  return { eingang, zaehlerLaden: () => zaehlerLaden(), zaehlerZeigen, beobachten, glocke, projektZahl, teamListe, teamDetail, windowsHinweis };
})();
