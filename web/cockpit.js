// Lehrerbereich: Cockpit (Startseite), Kalender (Monat, Halbjahr), Aktivitaeten, Kalender-Abos (Dienst, Schule).
// Wird vor lehrer.js geladen und benutzt zur Laufzeit dessen S, inhalt, titelSetzen und zeigen.
'use strict';

const Cockpit = (() => {
  const el = T.el;
  const MONATE = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'];
  const AMPEL = { g: 'grün', y: 'gelb', r: 'rot' };

  const plus = (text, n) => { const d = T.datum(text); d.setDate(d.getDate() + n); return T.isoDatum(d); };
  const heuteIso = () => T.isoDatum(new Date());
  const zahl = (n, eins, mehr) => n + ' ' + (n === 1 ? eins : mehr);
  const zuProjekt = id => () => { location.hash = 'projekt/' + id; };

  function klassenWahl(klassen) {
    if (klassen.length < 2) return null;
    const wahl = el('select', { class: 'klein', 'aria-label': 'Klasse', onchange: ev => { S.klasse = ev.target.value; zeigen(); } },
      el('option', { value: '', text: 'Alle Klassen' }), klassen.map(k => el('option', { value: k, text: k })));
    wahl.value = S.klasse || '';
    return wahl;
  }

  // Ein Eintrag im Kalender als kurzer Text
  function eintragText(e) {
    if (e.art === 'dienst') return (e.zeit ? e.zeit + ' ' : '') + e.titel;
    if (e.art === 'meilenstein') return '◆ ' + e.projekt + ': ' + e.titel;
    if (e.art === 'besprechung') return e.zeit + ' Besprechung ' + e.titel;
    if (e.art === 'projekttag') return 'Projekttag ' + e.titel + (e.fehlen.length ? ' · Termine fehlen: ' + e.fehlen.join(', ') : '');
    if (e.art === 'ausfall') return 'Ausfall: ' + e.titel;
    return e.titel;
  }

  // Eintraege je Tag; mehrtaegige (Ferien, Ausfall, ganztaegiger Dienst) an jedem Tag
  function jeTag(eintraege, von, bis) {
    const tage = {};
    for (const e of eintraege) {
      const bisTag = e.bis && e.bis > e.datum ? e.bis : e.datum;
      for (let t = e.datum < von ? von : e.datum; t <= bisTag && t <= bis; t = plus(t, 1)) (tage[t] = tage[t] || []).push(e);
    }
    return tage;
  }

  function dienstStand(dienst) {
    if (!dienst) return el('a', { href: '#konto', class: 'leise', text: 'Dienstkalender verbinden' });
    if (dienst.fehler) return el('a', { href: '#konto', class: 'fehlertext', text: 'Dienstkalender: Abruf fehlgeschlagen' });
    return el('span', { class: 'leise', text: 'Dienstkalender abgeglichen ' + (dienst.stand ? dienst.stand.slice(11, 16) : '–') });
  }

  // --- Cockpit ---

  function gruppe(titel, liste, zeile, leer) {
    return el('div', { class: 'hb-gruppe' },
      el('div', { class: 'zeile' }, el('span', { class: 'etikett', text: titel }), el('span', { class: 'chip' + (liste.length ? ' blau' : ''), text: String(liste.length) })),
      liste.length ? liste.map(zeile) : el('div', { class: 'leise klein-text', text: leer }));
  }

  function handlungsbedarf(c) {
    return el('section', { class: 'karte stapel-eng' },
      el('h2', { class: 'dreieck', text: 'Handlungsbedarf' }),
      gruppe('Heute', c.heute, h => el('div', { class: 'hb' },
        el('span', { class: 'mono', text: h.uhrzeit }),
        el('div', {}, el('b', { text: h.titel }), el('div', { class: 'leise', text: 'Besprechung · ' + h.text +
          (h.warnungen ? ' · ' + zahl(h.warnungen, 'Warnung', 'Warnungen') : '') })),
        el('a', { class: 'knopf haupt', href: '#projekt/' + h.projekt_id + '/besprechung' }, 'Besprechen ▶')), 'Heute keine Besprechungen.'),
      gruppe('Jetzt erledigen', c.erledigen, e => el('div', { class: 'hb' },
        el('span', { class: 'hb-m', text: '›' }),
        el('div', {}, el('b', { text: e.titel }), el('div', { class: 'leise', text: e.text })),
        e.art === 'anfrage' ? el('a', { class: 'knopf', href: '#anfragen/v/' + e.anfrage_id }, 'Öffnen')
          : e.art === 'liste' ? el('a', { class: 'knopf', href: '#anfragen/liste/' + e.liste_id }, 'Prüfen')
            : el('button', { type: 'button', onclick: e.projekt_id ? zuProjekt(e.projekt_id) : () => { location.hash = 'termine'; } },
              e.projekt_id ? 'Öffnen' : 'Termine')), 'Nichts offen.'),
      gruppe('Im Blick behalten', c.blick, b => el('a', { class: 'hb blick', href: '#projekt/' + b.projekt_id },
        el('span', { class: 'hb-m warn', text: '!' }),
        el('div', {}, el('b', { text: b.titel }), el('div', { class: 'leise', text: b.text }))), 'Keine Warnungen.'));
  }

  function zweiWochen(c) {
    const von = c.von, bis = plus(von, 13), heute = heuteIso();
    const tage = jeTag(c.kalender, von, bis);
    const zeilen = [];
    for (let t = von; t <= bis; t = plus(t, 1)) {
      const d = T.datum(t), wt = d.getDay(), liste = tage[t] || [];
      if ((wt === 0 || wt === 6) && !liste.some(e => e.art === 'dienst')) continue;
      const frei = liste.filter(e => e.art === 'ferien' || e.art === 'ausfall');
      const bespr = liste.filter(e => e.art === 'besprechung');
      const rest = liste.filter(e => !['ferien', 'ausfall', 'besprechung'].includes(e.art) && !(e.art === 'projekttag' && !e.fehlen.length));
      zeilen.push(el('div', { class: 'kt' + (t === heute ? ' heute' : '') + (frei.length ? ' frei' : '') },
        el('div', { class: 'kt-tag' }, wt === 1 ? el('span', { class: 'leise', text: 'KW ' + T.kw(d) + ' · ' }) : null,
          T.TAGE[wt] + ' ' + t.slice(8, 10) + '.', t === heute ? el('b', { text: ' heute' }) : null),
        el('div', { class: 'kt-inhalt' },
          frei.map(e => el('span', { class: 'ke ' + e.art, text: eintragText(e) })),
          bespr.length ? el('span', { class: 'ke besprechung', title: bespr.map(eintragText).join('\n'),
            text: zahl(bespr.length, 'Besprechung', 'Besprechungen') }) : null,
          rest.map(e => el('span', { class: 'ke ' + e.art + (e.art === 'projekttag' ? ' fehlt' : ''),
            title: e.ort ? e.ort : null, text: e.art === 'projekttag' ? 'Termine fehlen: ' + e.fehlen.join(', ') : eintragText(e) })))));
    }
    return el('section', { class: 'karte' },
      el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: 'Nächste zwei Wochen' }),
        el('span', { class: 'rechts' }, dienstStand(c.dienst),
          el('a', { class: 'knopf klein', href: '#kalender/monat' }, 'Monat'), el('a', { class: 'knopf klein', href: '#kalender/halbjahr' }, 'Halbjahr'))),
      el('div', { class: 'kt-liste' }, zeilen), legende());
  }

  function legende() {
    return el('div', { class: 'legende' },
      [['dienst', 'Dienst (Outlook)'], ['besprechung', 'Besprechungen'], ['meilenstein', '◆ Meilenstein'], ['fehlt', 'Termine fehlen'],
        ['ferien', 'Ferien'], ['ausfall', 'Ausfall']].map(([k, t]) => el('span', {}, el('span', { class: 'ke-m ' + k }), t)));
  }

  function verlaufPunkte(verlauf) {
    return el('span', { class: 'punkte' }, verlauf.map(v => el('span', { class: 'punkt ' + (v.ampel || 'ohne'),
      title: T.kwText(v.woche) + ': ' + (AMPEL[v.ampel] || 'keine Ampel') })));
  }

  function projektkarte(k) {
    const termin = !k.termin ? el('span', { class: 'fehlertext', text: 'nicht gebucht' })
      : k.termin.datum === heuteIso() ? el('b', { text: 'heute ' + k.termin.uhrzeit }) : T.kurzTag(k.termin.datum) + ' ' + k.termin.uhrzeit;
    const prozent = k.aufgaben ? Math.round(100 * k.erledigt / k.aufgaben) : 0;
    return el('a', { class: 'karte projektkarte pk' + (k.warnungen.length ? ' achtung' : ''), href: '#projekt/' + k.id },
      el('div', { class: 'zeile' }, el('span', { class: 'punkt gross ' + (k.ampel ? k.ampel.ampel : 'ohne'),
        title: k.ampel ? 'Gesamtstatus ' + T.kwText(k.ampel.woche) + ': ' + AMPEL[k.ampel.ampel] : 'noch keine Ampel' }),
        el('h3', { text: k.titel }), el('span', { class: 'chip blau', text: k.klasse })),
      k.warnungen.length ? el('div', { class: 'pk-warn', text: '⚠ ' + k.warnungen[0].text + (k.warnungen.length > 1 ? ' (+' + (k.warnungen.length - 1) + ')' : '') }) : null,
      el('dl', { class: 'daten' },
        el('dt', { text: 'Verlauf' }), el('dd', {}, verlaufPunkte(k.verlauf.slice(-5))),
        el('dt', { text: 'Fortschritt' }), el('dd', {}, el('span', { class: 'balken' }, el('span', { style: 'width:' + prozent + '%' })),
          ' ' + k.erledigt + '/' + k.aufgaben),
        el('dt', { text: 'Meilenstein' }), el('dd', { text: k.meilenstein ? '◆ ' + k.meilenstein.titel + ' · ' + T.kwText(k.meilenstein.woche) : '–' }),
        el('dt', { text: 'Termin' }), el('dd', {}, termin),
        el('dt', { text: 'Seit gestern' }), el('dd', { text: k.seit_gestern ? zahl(k.seit_gestern, 'Änderung', 'Änderungen') : 'keine Änderung' })));
  }

  function matrix(karten) {
    const wochen = [...new Set(karten.flatMap(k => k.verlauf.map(v => v.woche)))].sort();
    return el('div', { class: 'rollbar' }, el('table', { class: 'liste matrix' },
      el('thead', {}, el('tr', {}, el('th', { text: 'Team' }), wochen.map(w => el('th', { text: String(T.kw(T.datum(w))) })))),
      el('tbody', {}, karten.map(k => {
        const je = Object.fromEntries(k.verlauf.map(v => [v.woche, v.ampel]));
        return el('tr', { class: k.warnungen.length ? 'achtung' : '' },
          el('td', {}, el('a', { href: '#projekt/' + k.id, text: k.titel }), el('span', { class: 'leise', text: ' ' + k.klasse })),
          wochen.map(w => el('td', { class: 'mz', title: T.kwText(w) + ': ' + (AMPEL[je[w]] || (w in je ? 'keine Ampel' : 'kein Projekt')) },
            el('span', { class: 'punkt ' + (je[w] || (w in je ? 'ohne' : 'aus')) }))));
      }))));
  }

  async function cockpitZeigen() {
    titelSetzen('Cockpit');
    const c = await T.api('GET', '/api/cockpit' + (S.klasse ? '?klasse=' + encodeURIComponent(S.klasse) : ''));
    const heute = new Date();
    const projekte = el('section', { class: 'karte stapel-eng' },
      el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: 'Projekte' }),
        el('span', { class: 'leise', text: zahl(c.karten.length, 'Team', 'Teams') + ' · sortiert nach Handlungsbedarf' }),
        el('span', { class: 'rechts umschalter' },
          ['karten', 'matrix'].map(a => el('button', { type: 'button', class: S.cockpitAnsicht === a ? 'an' : '',
            onclick: () => { S.cockpitAnsicht = a; zeigen(); } }, a === 'karten' ? 'Karten' : 'Ampel-Matrix')))),
      !c.karten.length ? el('div', { class: 'leer', text: 'Keine laufenden Projekte.' })
        : S.cockpitAnsicht === 'matrix' ? matrix(c.karten) : el('div', { class: 'raster' }, c.karten.map(projektkarte)));
    T.setzen(inhalt,
      el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Cockpit' }),
        el('span', { class: 'leise', text: heute.toLocaleDateString('de-DE', { weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric' }) +
          ' · KW ' + T.kw(heute) }), klassenWahl(c.klassen)),
      el('div', { class: 'cockpit' }, handlungsbedarf(c), el('div', { class: 'stapel' }, zweiWochen(c), projekte)));
  }

  // --- Kalender: Monat und Halbjahr ---

  async function kalenderZeigen(ansicht) {
    ansicht = ansicht === 'halbjahr' ? 'halbjahr' : 'monat';
    titelSetzen('Kalender');
    const heute = new Date();
    if (!S.kalMonat) S.kalMonat = T.isoDatum(new Date(heute.getFullYear(), heute.getMonth(), 1));
    const erster = T.datum(S.kalMonat);
    const monate = ansicht === 'halbjahr' ? 6 : 1;
    const ende = new Date(erster.getFullYear(), erster.getMonth() + monate, 0);
    const von = T.isoDatum(erster), bis = T.isoDatum(ende);
    const k = (S.klasse ? '&klasse=' + encodeURIComponent(S.klasse) : '');
    const d = await T.api('GET', '/api/kalender?von=' + von + '&bis=' + bis + k);
    const tage = jeTag(d.eintraege, von, bis);
    const blaettern = n => { S.kalMonat = T.isoDatum(new Date(erster.getFullYear(), erster.getMonth() + n, 1)); zeigen(); };
    const titel = ansicht === 'monat' ? MONATE[erster.getMonth()] + ' ' + erster.getFullYear()
      : MONATE[erster.getMonth()] + ' ' + erster.getFullYear() + ' bis ' + MONATE[ende.getMonth()] + ' ' + ende.getFullYear();
    T.setzen(inhalt,
      el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Kalender' }),
        el('span', { class: 'umschalter' }, [['monat', 'Monat'], ['halbjahr', 'Halbjahr']].map(([a, t]) =>
          el('a', { class: 'knopf' + (a === ansicht ? ' an' : ''), href: '#kalender/' + a }, t))),
        el('button', { type: 'button', 'aria-label': 'zurück', onclick: () => blaettern(-monate) }, '‹'),
        el('button', { type: 'button', onclick: () => { S.kalMonat = null; zeigen(); } }, 'Heute'),
        el('button', { type: 'button', 'aria-label': 'weiter', onclick: () => blaettern(monate) }, '›')),
      el('section', { class: 'karte stapel-eng' },
        el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: titel }), el('span', { class: 'rechts' }, dienstStand(d.dienst))),
        ansicht === 'monat' ? monatsRaster(erster, tage) : halbjahr(erster, tage), legende()));
  }

  function monatsRaster(erster, tage) {
    const heute = heuteIso();
    const start = new Date(erster); start.setDate(1 - ((erster.getDay() + 6) % 7));
    const zellen = [];
    for (let i = 0; i < 42; i++) {
      const d = new Date(start); d.setDate(start.getDate() + i);
      if (i >= 35 && d.getMonth() !== erster.getMonth()) break;
      const t = T.isoDatum(d), liste = tage[t] || [];
      const frei = liste.find(e => e.art === 'ferien' || e.art === 'ausfall');
      const sichtbar = liste.filter(e => e.art !== 'ferien' && !(e.art === 'projekttag' && !e.fehlen.length) && e.art !== 'ausfall');
      zellen.push(el('div', { class: 'mt' + (d.getMonth() !== erster.getMonth() ? ' fremd' : '') + (t === heute ? ' heute' : '') +
        (frei ? ' frei ' + frei.art : '') + (d.getDay() === 0 || d.getDay() === 6 ? ' we' : ''), title: liste.map(eintragText).join('\n') },
        el('div', { class: 'mt-kopf' }, el('b', { text: String(d.getDate()) }), d.getDay() === 1 ? el('span', { class: 'leise', text: 'KW ' + T.kw(d) }) : null),
        frei ? el('div', { class: 'ke ' + frei.art, text: frei.titel }) : null,
        sichtbar.slice(0, 4).map(e => e.projekt_id
          ? el('a', { class: 'ke ' + e.art, href: '#projekt/' + e.projekt_id, text: eintragText(e) })
          : el('div', { class: 'ke ' + e.art + (e.art === 'projekttag' ? ' fehlt' : ''), text: e.art === 'projekttag' ? 'Termine fehlen' : eintragText(e) })),
        sichtbar.length > 4 ? el('div', { class: 'leise klein-text', text: '+' + (sichtbar.length - 4) + ' weitere' }) : null));
    }
    return el('div', { class: 'monat' }, ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'].map(t => el('div', { class: 'mt-wt', text: t })), zellen);
  }

  function halbjahr(erster, tage) {
    const heute = heuteIso();
    const spalten = [];
    for (let m = 0; m < 6; m++) {
      const anfang = new Date(erster.getFullYear(), erster.getMonth() + m, 1);
      const zeilen = [];
      for (let d = new Date(anfang); d.getMonth() === anfang.getMonth(); d.setDate(d.getDate() + 1)) {
        const t = T.isoDatum(d), liste = tage[t] || [], wt = d.getDay();
        const frei = liste.find(e => e.art === 'ferien' || e.art === 'ausfall');
        const zaehle = art => liste.filter(e => e.art === art).length;
        const fehlt = liste.some(e => e.art === 'projekttag' && e.fehlen.length);
        zeilen.push(el('div', { class: 'hj' + (wt === 0 || wt === 6 ? ' we' : '') + (frei ? ' frei ' + frei.art : '') + (t === heute ? ' heute' : ''),
          title: [T.kurzTag(t)].concat(liste.map(eintragText)).join('\n') },
          el('span', { class: 'hj-tag', text: T.TAGE[wt].slice(0, 2) + ' ' + d.getDate() }),
          el('span', { class: 'hj-m' },
            zaehle('projekttag') ? el('span', { class: 'ke-m projekttag' + (fehlt ? ' fehlt' : '') }) : null,
            zaehle('besprechung') ? el('span', { class: 'hj-n', text: String(zaehle('besprechung')) }) : null,
            zaehle('meilenstein') ? el('span', { class: 'hj-ms', text: '◆' }) : null,
            zaehle('dienst') ? el('span', { class: 'ke-m dienst' }) : null),
          frei && d.getDate() === 1 || frei && wt === 1 ? el('span', { class: 'hj-frei', text: frei.titel }) : null));
      }
      spalten.push(el('div', { class: 'hj-spalte' }, el('div', { class: 'hj-monat', text: MONATE[anfang.getMonth()] }), zeilen));
    }
    return el('div', { class: 'halbjahr' }, spalten);
  }

  // --- Aktivitaeten: je Team zusammengefasst ---

  const BEREICHE = [['raster', 'Raster & Ampeln'], ['anfragen', 'Anfragen & Bestellungen'], ['besprechung', 'Besprechung & Termine'],
    ['sonstiges', 'Fotos & Sonstiges']];
  const ZEITRAEUME = [['besuch', 'Seit letztem Besuch'], ['heute', 'Heute'], ['woche', 'Diese Woche'], ['30', '30 Tage']];
  const ZAHL_TEXT = { raster: ['Änderung im Raster', 'Änderungen im Raster'], anfragen: ['Eintrag bei Anfragen', 'Einträge bei Anfragen'],
    besprechung: ['Eintrag zu Besprechung/Termin', 'Einträge zu Besprechung/Termin'], sonstiges: ['sonstige Änderung', 'sonstige Änderungen'] };
  const SYMBOL = { ampel_r: '●', ampel_y: '●', nachricht: '✉', anfrage: '✉', verschoben: '↦', liste: '🛒', entfallen: '✕', meilenstein: '◆', besprechung: '▣' };

  function aktivitaetenEinstellungen() {
    if (!S.akt) {
      let gespeichert = null;
      try { gespeichert = JSON.parse(localStorage.getItem('tdrs-akt') || 'null'); } catch (e) { /* ohne Speicher */ }
      S.akt = Object.assign({ zeitraum: 'besuch', bereiche: ['raster', 'anfragen'] }, gespeichert || {});
    }
    return S.akt;
  }

  function aktivitaetenMerken() {
    try { localStorage.setItem('tdrs-akt', JSON.stringify({ zeitraum: S.akt.zeitraum, bereiche: S.akt.bereiche })); } catch (e) { /* egal */ }
  }

  function hinweisZeile(h, k) {
    const text = h.art === 'verschoben' ? h.text + ' (' + T.kwText(h.alt) + ' → ' + T.kwText(h.neu) + ')'
      : h.art === 'meilenstein' && h.woche ? h.text + ' · ' + T.kwText(h.woche) : h.text;
    const inhalt = [el('span', { class: 'akt-sym ' + h.art, text: SYMBOL[h.art] || '•' }), el('span', { text })];
    return h.anfrage_id ? el('a', { class: 'akt-hinweis ' + h.art, href: '#anfragen/v/' + h.anfrage_id }, inhalt)
      : el('a', { class: 'akt-hinweis ' + h.art, href: '#projekt/' + k.id }, inhalt);
  }

  function ereignisZeile(e) {
    return el('div', { class: 'akt-ereignis' },
      el('span', { class: 'mono leise', text: T.zeitText(e.zeit) }),
      el('span', {}, el('b', { text: T.werText(e) }), ' ', T.verlaufText(e), e.anzahl > 1 ? el('span', { class: 'leise', text: ' (' + e.anzahl + '×)' }) : null));
  }

  function aktivitaetKarte(k) {
    const zahlen = Object.entries(k.zahlen).map(([b, n]) => n + ' ' + ZAHL_TEXT[b][n === 1 ? 0 : 1]);
    if (k.erledigt) zahlen.push('✓ ' + k.erledigt + ' erledigt');
    return el('section', { class: 'karte akt-karte' + (k.hinweise.some(h => h.art === 'ampel_r' || h.art === 'nachricht') ? ' achtung' : '') },
      el('div', { class: 'zeile' }, el('span', { class: 'punkt gross ' + (k.ampel || 'ohne'), title: k.ampel ? 'Gesamtstatus: ' + AMPEL[k.ampel] : 'noch keine Ampel' }),
        el('a', { class: 'akt-titel', href: '#projekt/' + k.id, text: k.titel }), el('span', { class: 'chip blau', text: k.klasse })),
      k.hinweise.length ? el('div', { class: 'akt-hinweise' }, k.hinweise.slice(0, 6).map(h => hinweisZeile(h, k)),
        k.hinweise.length > 6 ? el('div', { class: 'leise klein-text', text: '+ ' + (k.hinweise.length - 6) + ' weitere Hinweise' }) : null) : null,
      el('div', { class: 'akt-zahlen leise', text: zahlen.join(' · ') + (k.ausgeblendet ? ' · ' + k.ausgeblendet + ' ausgeblendet' : '') }),
      el('details', { class: 'akt-details' }, el('summary', { text: 'Einzelheiten (' + k.ereignisse.length + ')' }),
        el('div', { class: 'akt-liste' }, k.ereignisse.map(ereignisZeile))));
  }

  async function aktivitaetenZeigen() {
    titelSetzen('Aktivitäten');
    const E = aktivitaetenEinstellungen();
    const url = '/api/aktivitaeten?zeitraum=' + E.zeitraum + '&bereiche=' + E.bereiche.join(',') + (S.klasse ? '&klasse=' + encodeURIComponent(S.klasse) : '');
    const d = await T.api('GET', url);
    const neu = (aendern) => { aendern(); aktivitaetenMerken(); zeigen(); };
    const seitText = E.zeitraum === 'besuch' ? 'Neu seit deinem letzten Besuch: ' + T.zeitText(d.seit) : 'seit ' + T.zeitText(d.seit);
    T.setzen(inhalt,
      el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Aktivitäten' }), klassenWahl(d.klassen)),
      el('div', { class: 'akt-filter' },
        el('span', { class: 'umschalter' }, ZEITRAEUME.map(([k, t]) => el('button', { type: 'button', class: E.zeitraum === k ? 'an' : '',
          onclick: () => neu(() => { E.zeitraum = k; }) }, t))),
        el('span', { class: 'akt-bereiche' }, BEREICHE.map(([k, t]) => el('label', { class: 'haken chip-haken' + (E.bereiche.includes(k) ? ' an' : '') },
          el('input', { type: 'checkbox', checked: E.bereiche.includes(k), onchange: ev => neu(() => {
            E.bereiche = ev.target.checked ? E.bereiche.concat(k) : E.bereiche.filter(b => b !== k);
            if (!E.bereiche.length) E.bereiche = ['raster'];
          }) }), t)))),
      el('p', { class: 'leise', text: seitText }),
      d.karten.length ? el('div', { class: 'akt-raster' }, d.karten.map(aktivitaetKarte))
        : el('div', { class: 'leer', text: 'In diesem Zeitraum hat sich in den gewählten Bereichen nichts getan.' }),
      d.ruhig.length ? el('p', { class: 'leise akt-ruhig' }, 'Ohne Änderung: ',
        d.ruhig.map((r, i) => [i ? ', ' : '', el('a', { href: '#projekt/' + r.id, text: r.titel }),
          r.ausgeblendet ? el('span', { class: 'klein-text', text: ' (' + r.ausgeblendet + ' ausgeblendet)' }) : null])) : null);
  }

  // --- Abos: Dienstkalender (Mein Konto), Schulkalender (Einstellungen) ---

  function aboStatus(a) {
    if (!a) return el('p', { class: 'leise', text: 'Noch kein Kalender hinterlegt.' });
    return el('dl', { class: 'daten' },
      el('dt', { text: 'Adresse' }), el('dd', { class: 'mono', text: a.adresse }),
      el('dt', { text: 'Letzter Abruf' }), el('dd', { text: a.stand ? T.zeitText(a.stand) + ' · ' + zahl(a.anzahl, 'Eintrag', 'Einträge') : '–' }),
      a.fehler ? [el('dt', { text: 'Fehler' }), el('dd', { class: 'fehlertext', text: a.fehler + ' (' + T.zeitText(a.versuch) + ')' })] : null);
  }

  function aboKarte({ titel, text, status, basis, zusatz, speichernDaten }) {
    const url = el('input', { type: 'url', placeholder: 'https://outlook.office365.com/owa/calendar/…/calendar.ics', autocomplete: 'off' });
    const ort = el('div');
    const fertig = (a, meldung) => {
      T.setzen(ort, aboStatus(a));
      url.value = '';
      if (a && a.fehler) T.meldung(a.fehler, true); else T.meldung(meldung);
    };
    const senden = async (pfad, daten, meldung) => {
      try { const r = await T.api('POST', pfad, daten); fertig(Object.values(r)[0], meldung); }
      catch (e) { T.meldung(e.message, true); }
    };
    T.setzen(ort, aboStatus(status));
    return el('section', { class: 'karte stapel' },
      el('h2', { class: 'dreieck', text: titel }), el('p', { class: 'leise', text: text }), ort,
      T.feld(status ? 'Neuer ICS-Link (ersetzt den bisherigen)' : 'ICS-Link', url), zusatz || null,
      el('div', { class: 'zeile' },
        el('button', { type: 'button', class: 'haupt', onclick: () => senden(basis, Object.assign({ url: url.value }, speichernDaten ? speichernDaten() : {}),
          'Gespeichert und abgerufen.') }, 'Speichern'),
        el('button', { type: 'button', onclick: () => senden(basis + (basis.endsWith('schulkalender') ? '' : '/abrufen'),
          speichernDaten ? speichernDaten() : {}, 'Abgerufen.') }, 'Jetzt abrufen'),
        el('button', { type: 'button', class: 'warnen', onclick: () => senden(basis + '/entfernen', {}, 'Entfernt.') }, 'Entfernen')));
  }

  async function dienstKarte() {
    const { dienst } = await T.api('GET', '/api/dienstkalender');
    return aboKarte({ titel: 'Dienstkalender (Outlook)', status: dienst, basis: '/api/dienstkalender',
      text: 'Deine Termine erscheinen im Cockpit und im Kalender, nur für dich: weder Teams noch andere Lehrkräfte sehen sie. ' +
        'In Outlook im Web: Einstellungen → Kalender → Freigegebene Kalender → Kalender veröffentlichen, Kalender wählen, ' +
        '„Kann alle Details anzeigen“, Veröffentlichen, dann den ICS-Link kopieren. Der Server holt ihn alle 30 Minuten, nur lesend.' });
  }

  function schulKarte(einst) {
    const woerter = el('input', { value: einst.stichwoerter, maxlength: '300' });
    return aboKarte({ titel: 'Schulkalender (Ferien)', status: einst.schulkalender, basis: '/api/einstellungen/schulkalender',
      text: 'Aus dem Schulkalender kommen die Ferien für alle Projektzeiten: ganztägige Einträge, deren Titel eines der Stichwörter enthält. ' +
        'Abruf alle 30 Minuten. Von Hand eingetragene Ferien bleiben zusätzlich bestehen.',
      zusatz: T.feld('Stichwörter für Ferien', woerter, 'durch Komma getrennt, Groß-/Kleinschreibung egal'),
      speichernDaten: () => ({ stichwoerter: woerter.value }) });
  }

  return { cockpitZeigen, kalenderZeigen, aktivitaetenZeigen, dienstKarte, schulKarte };
})();
