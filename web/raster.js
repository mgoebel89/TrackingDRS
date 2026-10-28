// Tracking-Sheet: Raster (PC, Tablet) und "Diese Woche" (Handy). Das Team bearbeitet es ueber seinen Link, die
// Lehrkraft sieht es auf der Projektseite nur an (lesen, vergleichen, Verlauf, Basisplan festlegen).
//
// Ebenen je Zelle: Plan (b = geplante Woche, als blauer Balken), Endtermin (e, Marke) und Ampel (g/y/r faerbt den
// Balken der Woche). Eingabe: Zelle anklicken und Taste druecken (wie in Excel), ueber Wochen ziehen plant b.
// Wochen ohne Projekttag sind schraffiert (sobald fuer das Projekt eine Projektzeit gilt); erledigte Aufgaben tragen ein ✓.
'use strict';

const Raster = (() => {
  const { el } = T;
  const AMPEL = { g: 'grün', y: 'gelb', r: 'rot' };
  const LABEL = { neu: 'neu', weg: 'verworfen', verschoben: 'verschoben', person: 'Person', ampel: 'Ampel' };

  function erzeugen({ ort, basis, rolle, ansicht = 'raster', beiAenderung, beiLaden }) {
    const S = { sheet: null, gew: null, sel: null, zieh: null, vgl: null, vglId: '', diff: [], verlauf: {}, menue: null };
    const lehrkraft = rolle === 'lehrkraft';
    const nurLesen = () => lehrkraft || S.sheet.projekt.archiviert;

    // --- Hilfen ---
    const wochen = () => S.sheet.wochen;
    const alleAufgaben = () => S.sheet.phasen.flatMap(p => p.aufgaben);
    const aufgabe = id => alleAufgaben().find(a => a.id === id);
    const mitglied = id => S.sheet.mitglieder.find(m => m.id === id);
    const kuerzel = id => (mitglied(id) || {}).kuerzel || '?';
    const name = id => { const m = mitglied(id); return m ? m.vorname + ' ' + m.nachname : 'niemand'; };
    const braucht = a => !a.verworfen && !a.verantwortlich_id && (a.plan.length > 0 || a.ende !== null);
    const frei = w => S.sheet.projektwochen !== null && !S.sheet.projektwochen.includes(w);
    const ausfall = w => (S.sheet.ausfallwochen || {})[w];
    const offenerDialog = () => document.querySelector('dialog[open]') !== null;

    async function senden(aktion, daten) {
      try {
        const antwort = await T.api('POST', basis + '/sheet', Object.assign({ aktion }, daten));
        S.sheet = antwort.sheet;
        S.verlauf = {};
        zeichnen();
        if (beiLaden) beiLaden(S.sheet);
        if (beiAenderung) beiAenderung();
        return antwort.ergebnis || {};
      } catch (e) {
        T.meldung(e.message, true);
        if (e.status === 404) laden();
        return null;
      }
    }

    async function laden(nurWennNeu) {
      try {
        const url = basis + '/sheet' + (nurWennNeu && S.sheet ? '?stand=' + S.sheet.stand : '');
        const antwort = await T.api('GET', url);
        if (antwort.unveraendert) return;
        S.sheet = antwort.sheet;
        S.verlauf = {};
        if (S.gew && !aufgabe(S.gew)) S.gew = null;
        zeichnen();
        if (beiLaden) beiLaden(S.sheet);
      } catch (e) {
        if (!nurWennNeu) T.setzen(ort, el('div', { class: 'leer', text: e.message }));
      }
    }

    // --- Zeichnen ---
    function zeichnen() {
      if (!S.sheet) return;
      S.diff = S.vgl ? unterschiede(S.vgl.daten) : [];
      if (ansicht === 'woche') return T.setzen(ort, dieseWoche());
      T.setzen(ort, el('div', { class: 'sheet' },
        el('div', { class: 'sheet-haupt' }, werkzeugleiste(), el('div', { class: 'r-scroll' }, tabelle()), legende()),
        el('aside', { class: 'pc-panel', 'aria-label': 'Details' }, panel())));
    }

    function werkzeugleiste() {
      const auswahl = el('select', { 'aria-label': 'Vergleichen mit', onchange: ev => vergleichWaehlen(ev.target.value) },
        el('option', { value: '', text: 'kein Vergleich' }),
        S.sheet.versionen.map(v => el('option', { value: String(v.id), text: v.name + (v.art === 'basisplan' && !v.aktiv ? ' (abgelöst)' : '') })));
      auswahl.value = S.vglId;
      return el('div', { class: 'r-leiste' },
        nurLesen() ? null : el('span', { class: 'r-palette', role: 'toolbar', 'aria-label': 'Gewählte Zelle setzen' },
          el('span', { class: 'etikett', text: 'Zelle' }),
          [['b', 'b: geplante Woche', el('span', { class: 'm-b' }), 'b'],
            ['e', 'e: Endtermin', el('span', { class: 'e-m', text: 'e' })],
            ['g', 'Ampel grün: alles im Plan', el('span', { class: 'm-b st-g' }), 'g'],
            ['y', 'Ampel gelb: Problem mit Lösungsansatz', el('span', { class: 'm-b st-y' }), 'y'],
            ['r', 'Ampel rot: Erfolg gefährdet', el('span', { class: 'm-b st-r' }), 'r'],
            ['Delete', 'Zelle leeren (Entf)', '✕']].map(([taste, titel, ...inhalt]) =>
            el('button', { type: 'button', title: titel, 'aria-label': titel, onclick: () => tasteAnZelle(taste) }, inhalt))),
        el('label', { class: 'r-vergl' }, 'Vergleichen mit', auswahl),
        lehrkraft ? el('button', { type: 'button', onclick: basisplanSetzen }, 'Als Basisplan festlegen') : null,
        nurLesen() ? null : el('button', { type: 'button', onclick: () => meilensteinDialog() }, '+ Meilenstein'),
        lehrkraft ? el('span', { class: 'leise', text: 'Nur ansehen: Das Sheet bearbeitet das Team.' }) : null);
    }

    function legende() {
      return el('div', { class: 'legende' },
        el('span', {}, el('span', { class: 'm-b' }), 'b geplante Woche'),
        el('span', {}, el('span', { class: 'e-m', text: 'e' }), ' Endtermin'),
        el('span', {}, el('span', { class: 'e-m alt', text: 'e' }), ' ursprünglicher Endtermin'),
        el('span', {}, el('span', { class: 'm-b st-g' }), el('span', { class: 'm-b st-y' }), el('span', { class: 'm-b st-r' }), 'Ampel der Woche'),
        el('span', { text: '◆ Meilenstein' }),
        el('span', { text: 'blau hinterlegt: laufende Woche' }),
        el('span', { text: '✓ erledigt' }),
        S.sheet.projektwochen !== null ? el('span', {}, el('span', { class: 'm-frei' }), 'kein Projekttag') : null,
        Object.keys(S.sheet.ausfallwochen || {}).length ? el('span', {}, el('span', { class: 'm-frei m-ausfall' }), 'Ferien / Ausfall') : null,
        S.vgl ? el('span', {}, el('span', { class: 'm-geist' }), 'Plan der Vergleichsversion') : null);
    }

    function zelleKlassen(a, k) {
      const w = wochen()[k], st = a.ampel[w];
      const balken = j => j >= 0 && j < wochen().length && (a.plan.includes(wochen()[j]) || !!a.ampel[wochen()[j]]);
      const c = ['c'];
      if (balken(k)) {
        c.push('b');
        if (st) c.push('st-' + st);
        if (st && !a.plan.includes(w)) c.push('ungeplant');
        if (!balken(k - 1)) c.push('b-anf');
        if (!balken(k + 1)) c.push('b-end');
      }
      return c.join(' ');
    }

    function zelle(a, k) {
      const w = wochen()[k];
      const inhalt = [];
      const alt = S.vgl ? S.vgl.daten.aufgaben[String(a.id)] : null;
      if (alt && alt.plan.includes(w)) {
        const vorher = k > 0 && alt.plan.includes(wochen()[k - 1]), nachher = alt.plan.includes(wochen()[k + 1]);
        inhalt.push(el('span', { class: 'geist' + (vorher ? '' : ' g-anf') + (nachher ? '' : ' g-end') }));
      }
      const eAlt = S.vgl ? (alt ? alt.ende : null) : a.ende_ursprung;
      if (eAlt && eAlt === w && a.ende !== w) {
        inhalt.push(el('span', { class: 'e-m alt', title: S.vgl ? 'Endtermin in der Vergleichsversion' : 'ursprünglicher Endtermin', text: 'e' }));
      }
      if (a.ende === w) inhalt.push(el('span', { class: 'e-m', title: 'Endtermin', text: 'e' }));
      const titel = a.ampel[w] ? T.kwText(w) + ': ' + AMPEL[a.ampel[w]] : T.kwText(w);
      const klassen = ['w'];
      if (w === S.sheet.jetzt) klassen.push('jetzt');
      if (frei(w)) klassen.push(ausfall(w) ? 'frei ausfall' : 'frei');
      if (S.sel && S.sel.a === a.id && S.sel.k === k) klassen.push('sel');
      return el('td', { class: klassen.join(' '), 'data-k': String(k), title: titel },
        el('div', { class: zelleKlassen(a, k) }, inhalt));
    }

    function verantwortlichChip(a) {
      if (a.verantwortlich_id) return el('button', { type: 'button', class: 'vchip', title: name(a.verantwortlich_id), 'data-v': String(a.id) }, kuerzel(a.verantwortlich_id));
      if (braucht(a)) return el('button', { type: 'button', class: 'vchip fehlt', title: 'Verantwortlich fehlt', 'data-v': String(a.id) }, '?');
      return el('button', { type: 'button', class: 'vchip leer', title: 'noch nicht geplant', 'data-v': String(a.id) }, '–');
    }

    function marken(a) {
      const arten = [...new Set(S.diff.filter(x => x.a === a && x.art !== 'ampel').map(x => x.art))];
      return arten.map(art => el('span', { class: 'd-tag ' + art, text: LABEL[art] }));
    }

    function tabelle() {
      const W = wochen();
      const breite = 3 + W.length;
      let nr = 0;
      const kopf = el('tr', {}, el('th', {}), el('th', { class: 'links', text: 'Aufgabe' }), el('th', { class: 'links', text: 'Verantw.' }),
        W.map(w => el('th', { class: (w === S.sheet.jetzt ? 'jetzt' : '') + (frei(w) ? (ausfall(w) ? ' frei ausfall' : ' frei') : ''),
          title: T.tagText(w) + (ausfall(w) ? ' · ' + ausfall(w) : frei(w) ? ' · kein Projekttag' : ''), text: String(T.kw(T.datum(w))) })));
      const zeilen = [];
      for (const ph of S.sheet.phasen) {
        zeilen.push(el('tr', { class: 'phase' }, el('td', { colspan: String(breite) }, ph.name,
          nurLesen() ? null : el('button', { type: 'button', class: 'neu-auf', onclick: () => aufgabeNeu(ph) }, '+ Aufgabe'))));
        for (const a of ph.aufgaben) {
          nr += 1;
          const klassen = [a.verworfen ? 'verworfen' : '', a.erledigt ? 'erledigt' : '', a.id === S.gew ? 'gewaehlt' : ''].join(' ').trim();
          zeilen.push(el('tr', { class: klassen, 'data-a': String(a.id) },
            el('td', { class: 'nr', text: String(nr) }),
            el('td', { class: 'name', title: a.titel + (a.erledigt ? ' · erledigt ' + T.zeitText(a.erledigt) : '') },
              el('span', { class: 'nm' }, a.erledigt ? el('span', { class: 'erl', text: '✓' }) : null, marken(a), a.titel)),
            el('td', { class: 'vw' }, verantwortlichChip(a)),
            W.map((_, k) => zelle(a, k))));
        }
      }
      const ms = S.sheet.meilensteine.filter(m => !m.verworfen);
      const altMs = S.vgl ? Object.values(S.vgl.daten.meilensteine).filter(m => !m.verworfen) : [];
      zeilen.push(el('tr', { class: 'ms-r' }, el('td', {}), el('td', { class: 'name', text: '◆ Meilensteine' }), el('td', {}),
        W.map((w, k) => {
          const hier = ms.filter(m => m.woche === w);
          const geist = altMs.some(m => m.woche === w) && !hier.length;
          return el('td', { class: 'w ms-zelle' + (w === S.sheet.jetzt ? ' jetzt' : ''), 'data-mk': String(k),
            title: hier.length ? hier.map(m => m.titel).join(', ') : 'Meilenstein in ' + T.kwText(w) + ' setzen' },
          el('div', { class: 'c' }, hier.length ? el('span', { class: 'ms', text: '◆' }) : geist ? el('span', { class: 'ms geist-ms', text: '◇' }) : null));
        })));
      zeilen.push(el('tr', { class: 'gesamt' }, el('td', {}), el('td', { class: 'name', text: 'Gesamtstatus' }), el('td', {}),
        W.map((w, k) => {
          const g = gesamt(w);
          const c = g ? 'c b st-' + g + (gesamt(W[k - 1]) ? '' : ' b-anf') + (gesamt(W[k + 1]) ? '' : ' b-end') : 'c';
          return el('td', { class: 'w' + (w === S.sheet.jetzt ? ' jetzt' : ''), title: g ? T.kwText(w) + ': ' + AMPEL[g] : '' }, el('div', { class: c }));
        })));
      const tab = el('table', { class: 'r-tab' }, el('thead', {}, kopf), el('tbody', {}, zeilen));
      ereignisse(tab);
      return tab;
    }

    function gesamt(w) {
      if (!w) return '';
      const s = alleAufgaben().filter(a => !a.verworfen).map(a => a.ampel[w]);
      return s.includes('r') ? 'r' : s.includes('y') ? 'y' : s.includes('g') ? 'g' : '';
    }

    // --- Seitenleiste ---
    function panel() {
      const teile = [];
      if (S.vgl) {
        teile.push(el('div', {}, el('div', { class: 'etikett', text: 'Änderungen seit ' + S.vgl.name }),
          el('div', { class: 'diff-liste' }, S.diff.length ? S.diff.map(x => el('div', {},
            el('span', { class: 'd-tag ' + x.art, text: LABEL[x.art] }), el('b', { text: x.a.titel }), ': ' + x.t))
            : el('div', { class: 'leise', text: 'keine Änderungen' }))));
      }
      const a = S.gew ? aufgabe(S.gew) : null;
      if (!a) {
        teile.push(el('p', { class: 'leise', text: nurLesen() ? 'Aufgabe oder Zelle anklicken, um Details und Verlauf zu sehen.'
          : 'Aufgabe oder Zelle anklicken, um Details zu sehen. Tasten: b, e, g, y, r, Entf, Pfeile.' }));
        return teile;
      }
      const darfTitel = !nurLesen() && !a.verworfen && !a.aus_vorlage;
      const titel = el('input', { class: 'titel', value: a.titel, maxlength: '120', 'aria-label': 'Name der Aufgabe', readonly: !darfTitel });
      titel.addEventListener('change', () => { if (titel.value.trim() && titel.value !== a.titel) senden('titel', { aufgabe_id: a.id, titel: titel.value }); });
      titel.addEventListener('keydown', ev => { if (ev.key === 'Enter') titel.blur(); });
      const plan = a.plan.length ? T.kwText(a.plan[0]) + ' bis ' + T.kwText(a.plan[a.plan.length - 1]) : 'noch nicht geplant';
      const ende = a.ende ? T.kwText(a.ende) + (a.ende_ursprung && a.ende_ursprung !== a.ende ? ' (ursprünglich ' + T.kwText(a.ende_ursprung) + ')' : '') : 'kein Endtermin';
      teile.push(el('div', {}, el('div', { class: 'etikett', text: a.verworfen ? 'Aufgabe · verworfen' : a.aus_vorlage ? 'Vorgabe der Lehrkraft' : 'Aufgabe' }), titel));
      teile.push(el('div', {}, el('div', { class: 'etikett', text: 'Verantwortlich · genau einer' }),
        el('div', { class: 'v-wahl' + (braucht(a) ? ' pflicht' : '') },
          S.sheet.mitglieder.filter(m => m.aktiv || m.id === a.verantwortlich_id).map(m => el('button', {
            type: 'button', class: a.verantwortlich_id === m.id ? 'an' : '', 'aria-pressed': String(a.verantwortlich_id === m.id),
            disabled: a.verworfen || nurLesen(), onclick: () => verantwortlichSetzen(a, m.id) }, m.vorname + ' ' + m.nachname))),
        braucht(a) ? el('div', { class: 'r-hinweis', text: 'Pflicht, weil die Aufgabe geplant ist' }) : null,
        S.sheet.mitglieder.length ? null : el('div', { class: 'leise', text: 'Noch keine Teammitglieder eingetragen.' })));
      teile.push(el('div', {}, el('div', { class: 'etikett', text: 'Plan' }), plan, el('br'), 'Ende: ' + ende));
      if (!a.verworfen && !nurLesen()) {
        teile.push(el('div', {}, el('div', { class: 'etikett', text: 'Erledigt' }),
          el('label', { class: 'haken' }, el('input', { type: 'checkbox', checked: !!a.erledigt,
            onchange: ev => senden('erledigt', { aufgabe_id: a.id, erledigt: ev.target.checked }) }),
          a.erledigt ? 'erledigt ' + T.zeitText(a.erledigt) : 'Aufgabe ist erledigt')));
      } else if (a.erledigt) {
        teile.push(el('div', { class: 'leise', text: '✓ erledigt ' + T.zeitText(a.erledigt) }));
      }
      if (a.probleme.length) {
        teile.push(el('div', {}, el('div', { class: 'etikett', text: 'Probleme' }), a.probleme.map(p => el('div', { class: 'problem' },
          el('span', { class: 'm-b st-' + p.ampel }), T.kwText(p.woche) + ': ' + p.problem,
          el('div', { class: 'leise', text: '→ ' + p.massnahme + ' (' + kuerzel(p.verantwortlich_id) + ')' })))));
      }
      if (!nurLesen()) {
        const darfVerwerfen = !a.aus_vorlage;
        teile.push(el('div', { class: 'zeile' },
          a.verworfen ? null : el('button', { type: 'button', title: 'nach oben', 'aria-label': 'nach oben', onclick: () => senden('verschieben', { aufgabe_id: a.id, richtung: -1 }) }, '↑'),
          a.verworfen ? null : el('button', { type: 'button', title: 'nach unten', 'aria-label': 'nach unten', onclick: () => senden('verschieben', { aufgabe_id: a.id, richtung: 1 }) }, '↓'),
          darfVerwerfen ? el('button', { type: 'button', class: a.verworfen ? '' : 'warnen',
            onclick: () => senden('verwerfen', { aufgabe_id: a.id, verworfen: !a.verworfen }) }, a.verworfen ? 'Wiederherstellen' : 'Verwerfen') : null));
      }
      const verlauf = el('div', { class: 'log' }, el('span', { class: 'leise', text: 'lädt …' }));
      teile.push(el('div', {}, el('div', { class: 'etikett', text: 'Verlauf' }), verlauf));
      verlaufLaden(a.id, verlauf);
      return teile;
    }

    async function verlaufLaden(aid, ziel) {
      try {
        if (!S.verlauf[aid]) S.verlauf[aid] = (await T.api('GET', basis + '/aufgabe/' + aid + '/verlauf')).verlauf;
        T.setzen(ziel, S.verlauf[aid].length ? S.verlauf[aid].map(e => el('div', {},
          el('span', { class: 'mono', text: T.zeitText(e.zeit) }), el('span', {}, el('b', { text: T.werText(e) }), ' ', T.verlaufText(e))))
          : el('span', { class: 'leise', text: 'noch nichts' }));
      } catch (e) { T.setzen(ziel, el('span', { class: 'leise', text: e.message })); }
    }

    // --- Aktionen ---
    async function verantwortlichSetzen(a, mid) {
      menueZu();
      if (a.verantwortlich_id === mid) return;
      const ok = await senden('verantwortlich', { aufgabe_id: a.id, mitglied_id: mid });
      if (ok) T.meldung(name(mid) + ' ist verantwortlich.');
    }

    function nachAenderung(aid) {
      S.gew = aid;
      const a = aufgabe(aid);
      if (a && braucht(a)) {
        T.meldung('Wer ist verantwortlich? Bitte genau einen Schüler wählen.');
        menueAuf(a);
      }
    }

    async function tasteAnZelle(taste) {
      if (!S.sel) { T.meldung('Erst eine Zelle im Raster anklicken.', true); return; }
      const a = aufgabe(S.sel.a), w = wochen()[S.sel.k];
      if (!a) return;
      if (a.verworfen) { T.meldung('Diese Aufgabe ist verworfen.', true); return; }
      let ok = null;
      if (taste === 'b') ok = await senden('plan', { aufgabe_id: a.id, wochen: [w], wert: !a.plan.includes(w) });
      else if (taste === 'e') ok = a.ende === w ? {} : await senden('ende', { aufgabe_id: a.id, woche: w });
      else if (taste === 'g') ok = await ampelSetzen(a, w, 'g');
      else if (taste === 'y' || taste === 'r') ok = await problemDialog(a, w, taste);
      else if (taste === 'Delete') {
        if (a.ampel[w]) ok = await senden('ampel', { aufgabe_id: a.id, woche: w, ampel: null });
        else if (a.ende === w) ok = await senden('ende', { aufgabe_id: a.id, woche: null });
        else if (a.plan.includes(w)) ok = await senden('plan', { aufgabe_id: a.id, wochen: [w], wert: false });
      }
      if (ok) nachAenderung(a.id);
    }

    function ampelSetzen(a, w, ampel) {
      if (w > S.sheet.jetzt) { T.meldung('Eine Ampel gibt es nur für die laufende und vergangene Wochen.', true); return null; }
      return senden('ampel', { aufgabe_id: a.id, woche: w, ampel });
    }

    async function problemDialog(a, w, ampel) {
      if (w > S.sheet.jetzt) { T.meldung('Eine Ampel gibt es nur für die laufende und vergangene Wochen.', true); return null; }
      const aktive = S.sheet.mitglieder.filter(m => m.aktiv);
      if (!aktive.length) { T.meldung('Erst Teammitglieder eintragen (Lehrkraft).', true); return null; }
      const f = {
        problem: el('textarea', { rows: '2', required: true, maxlength: '500' }),
        massnahme: el('textarea', { rows: '2', required: true, maxlength: '500' }),
        wer: el('select', {}, aktive.map(m => el('option', { value: String(m.id), text: m.vorname + ' ' + m.nachname }))),
      };
      if (a.verantwortlich_id && aktive.some(m => m.id === a.verantwortlich_id)) f.wer.value = String(a.verantwortlich_id);
      return T.dialog({
        titel: a.titel + ' · ' + T.kwText(w) + ' · ' + (ampel === 'y' ? 'Gelb' : 'Rot'),
        inhalt: el('div', { class: 'felder' },
          el('p', { class: 'leise', text: ampel === 'y' ? 'Gelb: Problem mit Lösungsansatz, das Projekt ist nicht gefährdet.' : 'Rot: Das Problem gefährdet den Erfolg.' }),
          T.feld('Problem', f.problem), T.feld('Korrekturmaßnahme', f.massnahme), T.feld('Verantwortlich für die Maßnahme', f.wer)),
        speichern: async () => {
          const antwort = await T.api('POST', basis + '/sheet', { aktion: 'ampel', aufgabe_id: a.id, woche: w, ampel,
            problem: f.problem.value, massnahme: f.massnahme.value, verantwortlich_id: Number(f.wer.value) });
          S.sheet = antwort.sheet; S.verlauf = {};
          return true;
        },
      }).then(ok => { zeichnen(); if (ok && beiAenderung) beiAenderung(); return ok; });
    }

    async function aufgabeNeu(ph) {
      const titel = el('input', { required: true, maxlength: '120', placeholder: 'z. B. Lüfter auslegen' });
      const aid = await T.dialog({
        titel: 'Neue Aufgabe · ' + ph.name, knopf: 'Anlegen',
        inhalt: el('div', { class: 'felder' }, T.feld('Name der Aufgabe', titel)),
        speichern: async () => {
          const antwort = await T.api('POST', basis + '/sheet', { aktion: 'aufgabe_neu', phase_id: ph.id, titel: titel.value });
          S.sheet = antwort.sheet; S.verlauf = {};
          return antwort.ergebnis.aufgabe_id;
        },
      });
      if (aid) { S.gew = aid; S.sel = null; zeichnen(); T.meldung('Angelegt. Jetzt über die Wochen ziehen, um sie zu planen.'); }
    }

    async function meilensteinDialog(m, woche) {
      const W = wochen();
      const f = {
        titel: el('input', { required: true, maxlength: '120', value: m ? m.titel : '', placeholder: 'z. B. Konstruktion fertig' }),
        woche: el('select', {}, W.map(w => el('option', { value: w, text: T.kwText(w) + ' · ' + T.tagText(w) }))),
      };
      f.woche.value = m ? m.woche : (woche || (W.includes(S.sheet.jetzt) ? S.sheet.jetzt : W[0]));
      let verwerfen = false;
      const ok = await T.dialog({
        titel: m ? 'Meilenstein bearbeiten' : 'Neuer Meilenstein', knopf: m ? 'Speichern' : 'Anlegen',
        inhalt: el('div', { class: 'felder' }, T.feld('Name', f.titel), T.feld('Woche', f.woche),
          m ? el('div', {}, el('button', { type: 'button', class: 'warnen', onclick: ev => {
            verwerfen = true;
            ev.target.form.requestSubmit();
          } }, 'Meilenstein verwerfen')) : null),
        speichern: async () => {
          const antwort = await T.api('POST', basis + '/sheet', verwerfen
            ? { aktion: 'meilenstein_verwerfen', meilenstein_id: m.id, verworfen: true }
            : m ? { aktion: 'meilenstein_aendern', meilenstein_id: m.id, titel: f.titel.value, woche: f.woche.value }
              : { aktion: 'meilenstein_neu', titel: f.titel.value, woche: f.woche.value });
          S.sheet = antwort.sheet; S.verlauf = {};
          return true;
        },
      });
      zeichnen();
      if (ok && beiAenderung) beiAenderung();
    }

    async function basisplanSetzen() {
      const ok = await T.dialog({
        titel: 'Als Basisplan festlegen?',
        inhalt: el('p', { text: 'Der jetzige Stand wird als Basisplan eingefroren. Team und Lehrkraft können ihn danach jederzeit mit dem aktuellen Stand vergleichen. Ein früherer Basisplan bleibt als Version erhalten.' }),
        knopf: 'Festlegen',
        speichern: async () => { S.sheet = (await T.api('POST', basis + '/basisplan', {})).sheet; return true; },
      });
      if (ok) { T.meldung('Basisplan festgelegt.'); zeichnen(); }
    }

    async function vergleichWaehlen(id) {
      S.vglId = id;
      if (!id) { S.vgl = null; zeichnen(); return; }
      try {
        const v = (await T.api('GET', basis + '/version/' + id)).version;
        S.vgl = { name: v.name, daten: v.daten };
      } catch (e) { T.meldung(e.message, true); S.vgl = null; S.vglId = ''; }
      zeichnen();
    }

    function unterschiede(alt) {
      const liste = [];
      const gleich = (x, y) => x.slice().sort().join() === y.slice().sort().join();
      for (const a of alleAufgaben()) {
        const v = alt.aufgaben[String(a.id)];
        if (!v) { liste.push({ a, art: 'neu', t: 'neu angelegt' }); continue; }
        if (a.verworfen && !v.verworfen) liste.push({ a, art: 'weg', t: 'verworfen' });
        if (v.ende !== a.ende) liste.push({ a, art: 'verschoben', t: !v.ende ? 'Endtermin ' + T.kwText(a.ende) + ' gesetzt'
          : !a.ende ? 'Endtermin entfernt' : 'Ende ' + T.kwText(v.ende) + ' → ' + T.kwText(a.ende) });
        else if (!gleich(v.plan, a.plan)) liste.push({ a, art: 'verschoben', t: 'Zeitraum geändert' });
        if (v.verantwortlich_id !== a.verantwortlich_id) liste.push({ a, art: 'person', t: 'verantwortlich ' + name(v.verantwortlich_id) + ' → ' + name(a.verantwortlich_id) });
        for (const w of Object.keys(a.ampel)) if (v.ampel[w] !== a.ampel[w]) liste.push({ a, art: 'ampel', t: T.kwText(w) + ': ' + AMPEL[a.ampel[w]] });
      }
      return liste;
    }

    // --- Verantwortlich-Menue am Kuerzel ---
    function menueZu() { if (S.menue) { S.menue.remove(); S.menue = null; } }
    function menueAuf(a) {
      menueZu();
      const knopf = ort.querySelector('tr[data-a="' + a.id + '"] .vchip');
      if (!knopf || a.verworfen) return;
      const aktive = S.sheet.mitglieder.filter(m => m.aktiv);
      const menue = el('div', { class: 'r-menue', role: 'menu' },
        el('div', { class: 'etikett', text: 'Verantwortlich · genau einer' }),
        braucht(a) ? el('div', { class: 'pflicht-t', text: 'Pflicht, weil die Aufgabe geplant ist' }) : null,
        aktive.length ? aktive.map(m => el('button', { type: 'button', role: 'menuitem', class: a.verantwortlich_id === m.id ? 'an' : '',
          onclick: () => verantwortlichSetzen(a, m.id) }, el('span', { class: 'vchip', text: m.kuerzel }), m.vorname + ' ' + m.nachname))
          : el('div', { class: 'leise', text: 'Noch keine Teammitglieder eingetragen.' }));
      const r = knopf.getBoundingClientRect();
      menue.style.left = Math.max(8, r.left + window.scrollX) + 'px';
      menue.style.top = (r.bottom + window.scrollY + 4) + 'px';
      document.body.appendChild(menue);
      S.menue = menue;
      S.menueSeit = Date.now();
    }

    // --- Maus, Finger, Tastatur ---
    function ereignisse(tab) {
      tab.addEventListener('pointerdown', ev => {
        const td = ev.target.closest('td[data-k]'), tr = td && td.closest('tr[data-a]');
        if (!tr || offenerDialog()) return;
        if (nurLesen()) { auswaehlen(Number(tr.dataset.a), Number(td.dataset.k)); return; }
        if (ev.target.hasPointerCapture && ev.target.hasPointerCapture(ev.pointerId)) ev.target.releasePointerCapture(ev.pointerId);
        ev.preventDefault();
        const aid = Number(tr.dataset.a), k = Number(td.dataset.k);
        S.zieh = { aid, von: k, bis: k };
        menueZu();
        auswaehlen(aid, k);
      });
      tab.addEventListener('pointerover', ev => {
        if (!S.zieh) return;
        const td = ev.target.closest('td[data-k]'), tr = td && td.closest('tr[data-a]');
        if (!tr || Number(tr.dataset.a) !== S.zieh.aid) return;
        S.zieh.bis = Number(td.dataset.k);
        const l = Math.min(S.zieh.von, S.zieh.bis), h = Math.max(S.zieh.von, S.zieh.bis);
        tr.querySelectorAll('td[data-k]').forEach(z => { const k = Number(z.dataset.k); z.classList.toggle('vor', k >= l && k <= h); });
      });
      tab.addEventListener('click', ev => {
        const v = ev.target.closest('[data-v]');
        if (v) { const a = aufgabe(Number(v.dataset.v)); S.gew = a.id; zeichnen(); if (!nurLesen()) menueAuf(a); return; }
        const n = ev.target.closest('td.name'), tr = n && n.closest('tr[data-a]');
        if (tr) { S.gew = Number(tr.dataset.a); S.sel = null; zeichnen(); return; }
        const ms = ev.target.closest('td[data-mk]');
        if (ms && !nurLesen()) {
          const w = wochen()[Number(ms.dataset.mk)];
          const hier = S.sheet.meilensteine.filter(m => !m.verworfen && m.woche === w);
          meilensteinDialog(hier[0], w);
        }
      });
    }

    function auswaehlen(aid, k) {
      S.sel = { a: aid, k };
      const neu = S.gew !== aid;
      S.gew = aid;
      if (neu) { zeichnen(); return; }
      ort.querySelectorAll('td.sel').forEach(z => z.classList.remove('sel'));
      const td = ort.querySelector('tr[data-a="' + aid + '"] td[data-k="' + k + '"]');
      if (td) td.classList.add('sel');
    }

    document.addEventListener('pointerup', async () => {
      if (!S.zieh) return;
      const z = S.zieh; S.zieh = null;
      ort.querySelectorAll('td.vor').forEach(t => t.classList.remove('vor'));
      if (z.von === z.bis) return;
      const a = aufgabe(z.aid);
      if (!a || a.verworfen) return;
      const l = Math.min(z.von, z.bis), h = Math.max(z.von, z.bis);
      const W = wochen().slice(l, h + 1);
      let ok = await senden('plan', { aufgabe_id: a.id, wochen: W, wert: true });
      if (ok && !aufgabe(a.id).ende) ok = await senden('ende', { aufgabe_id: a.id, woche: W[W.length - 1] });
      S.sel = { a: a.id, k: h };
      zeichnen();
      if (ok) nachAenderung(a.id);
    });

    document.addEventListener('click', ev => {
      if (S.menue && Date.now() - S.menueSeit > 300 && !S.menue.contains(ev.target) && !ev.target.closest('[data-v]')) menueZu();
    });

    document.addEventListener('keydown', ev => {
      if (ansicht !== 'raster' || !S.sel || offenerDialog() || ev.ctrlKey || ev.metaKey || ev.altKey) return;
      if (ev.target.closest && ev.target.closest('input, textarea, select, [contenteditable="true"]')) return;
      if (!ort.isConnected) return;
      const liste = alleAufgaben(), i = liste.findIndex(a => a.id === S.sel.a);
      const pfeil = { ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0] }[ev.key];
      if (pfeil) {
        ev.preventDefault();
        const ni = Math.min(Math.max(i + pfeil[0], 0), liste.length - 1), nk = Math.min(Math.max(S.sel.k + pfeil[1], 0), wochen().length - 1);
        auswaehlen(liste[ni].id, nk);
        return;
      }
      if (ev.key === 'Escape') { menueZu(); return; }
      if (nurLesen()) return;
      const taste = (ev.key === 'Backspace' || ev.key === 'Delete') ? 'Delete' : ev.key.toLowerCase();
      if (!['b', 'e', 'g', 'y', 'r', 'Delete'].includes(taste)) return;
      ev.preventDefault();
      tasteAnZelle(taste);
    });

    // --- Diese Woche (Handy) ---
    function dieseWoche() {
      const w = S.sheet.jetzt;
      if (!S.sheet.wochen.includes(w)) return el('div', { class: 'leer', text: 'Diese Woche liegt außerhalb des Projektzeitraums.' });
      const laufend = alleAufgaben().filter(a => !a.verworfen && (a.plan.includes(w) || a.ende === w || a.ampel[w]));
      const offen = laufend.filter(a => !a.ampel[w] && !a.erledigt).length;
      return el('div', { class: 'stapel' },
        el('div', { class: 'banner' }, T.kwText(w) + ': ' + (laufend.length ? (offen ? offen + ' von ' + laufend.length + ' Aufgaben brauchen noch eine Ampel.' : 'Alle Ampeln gesetzt.') : 'Für diese Woche ist nichts geplant.')),
        laufend.length ? el('div', { class: 'hz' }, laufend.map(a => el('div', { class: 'hz-z' + (a.ampel[w] || a.erledigt ? '' : ' offen') },
          el('div', {}, el('b', { text: (a.erledigt ? '✓ ' : '') + a.titel }), el('span', { class: 'leise', text:
            (a.verantwortlich_id ? kuerzel(a.verantwortlich_id) : 'ohne Verantwortlichen') + (a.ende ? ' · Ende ' + T.kwText(a.ende) : '') +
            (a.erledigt ? ' · erledigt' : a.ampel[w] ? '' : ' · noch keine Ampel') })),
          el('div', { class: 'hz-amp' }, ['g', 'y', 'r'].map(f => el('button', {
            type: 'button', class: f + (a.ampel[w] === f ? ' an' : ''), 'aria-label': AMPEL[f], 'aria-pressed': String(a.ampel[w] === f), disabled: nurLesen(),
            onclick: () => f === 'g' ? ampelSetzen(a, w, 'g') : problemDialog(a, w, f) }, f)),
          el('button', { type: 'button', class: 'erl' + (a.erledigt ? ' an' : ''), 'aria-label': 'erledigt', title: a.erledigt ? 'doch nicht erledigt' : 'erledigt',
            'aria-pressed': String(!!a.erledigt), disabled: nurLesen(), onclick: () => senden('erledigt', { aufgabe_id: a.id, erledigt: !a.erledigt }) }, '✓'))))) : null,
        el('p', { class: 'leise', text: 'Planen und Aufgaben anlegen geht im Reiter „Tracking-Sheet“, am besten am PC oder Tablet.' }));
    }

    // --- Nachladen, damit mehrere Geraete denselben Stand sehen ---
    const timer = setInterval(() => {
      if (!ort.isConnected) { clearInterval(timer); return; }
      if (document.visibilityState === 'visible' && !S.zieh && !offenerDialog() && !(document.activeElement && document.activeElement.matches('input, textarea'))) laden(true);
    }, 20000);

    return {
      laden,
      ansicht(neu) { ansicht = neu; menueZu(); zeichnen(); },
    };
  }

  return { erzeugen };
})();
