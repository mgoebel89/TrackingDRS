// Anfragen und Bestelllisten. Team (Reiter "Anfragen"): Rueckfrage, Material ausleihen, Abnahme stellen und im
// Gespraechsverlauf verfolgen (vorgang.js); Bestellliste sammeln und im Einreichfenster einreichen. Lehrkraft: Eingang
// (#anfragen, vorgang.js), Einreichfenster (#anfragen/fenster), Listen je Position pruefen (#anfragen/liste/<id>),
// Sammelbestellung je Lieferant (#anfragen/sammel/<id>).
'use strict';

const Anfragen = (() => {
  const el = T.el;
  const ARTEN = { rueckfrage: 'Rückfrage', ausleihe: 'Ausleihe', abnahme: 'Abnahme' };
  const STATUS = { neu: 'neu', beantwortet: 'beantwortet', bereitgelegt: 'bereitgelegt', ausgegeben: 'ausgegeben', zurueck: 'zurück',
    abgelehnt: 'abgelehnt', freigegeben: 'freigegeben', nachbessern: 'nachbessern', zurueckgezogen: 'zurückgezogen' };
  const WEGE = [['bestellen', 'Bestellen'], ['lager', 'SchulLager'], ['firma', 'Firma'], ['ersetzen', 'Ersetzen'], ['ablehnen', 'Ablehnen']];

  const datum = text => text ? text.slice(8, 10) + '.' + text.slice(5, 7) + '.' : '';
  const stichtag = text => T.kurzTag(text) + ', ' + text.slice(11, 16);
  const statusChip = s => el('span', { class: 'chip st-' + s, text: STATUS[s] || s });

  function posStatus(p, eingereicht) {
    if (!eingereicht) return '';
    if (!p.entscheidung) return 'in Prüfung';
    const ersatz = p.entscheidung === 'ersetzen' && p.ersatz_artikel ? 'ersetzt durch ' + p.ersatz_artikel + ' · ' : '';
    if (p.weg === 'bestellen') return ersatz + (p.status || 'wird bestellt');
    if (p.weg === 'lager') return ersatz + (p.status === 'ausgegeben' ? 'ausgegeben' : 'liegt im Lager' + (p.kommentar && !ersatz ? ': ' + p.kommentar : ''));
    if (p.weg === 'firma') return 'über die Firma besorgen';
    if (p.weg === 'ersatz_gesucht') return 'Ersatz gesucht' + (p.kommentar ? ': ' + p.kommentar : '');
    return 'abgelehnt: ' + p.kommentar;
  }

  function lageText(lage) {
    if (lage.offen) return 'Einreichfenster offen bis ' + stichtag(lage.offen.bis) + '.';
    if (lage.naechstes) return 'Nächstes Einreichfenster: ' + T.kurzTag(lage.naechstes.von) + ' bis ' + stichtag(lage.naechstes.bis) +
      '. Bis dahin sammelt ihr hier, dann reicht ihr die Liste einmal ein.';
    return 'Noch kein Einreichfenster festgelegt. Ihr könnt trotzdem schon sammeln.';
  }

  function positionFelder(p, aufgaben) {
    const f = {
      artikel: el('input', { required: true, maxlength: '200', value: p ? p.artikel : '', placeholder: 'z. B. Axiallüfter 80×80 mm, 24 V' }),
      bestellnr: el('input', { maxlength: '80', value: p ? p.bestellnr : '' }),
      menge: el('input', { type: 'number', min: '1', max: '9999', required: true, value: String(p ? p.menge : 1) }),
      preis: el('input', { maxlength: '30', value: p ? p.preis : '', placeholder: 'z. B. 8,90 €' }),
      lieferant: el('input', { maxlength: '300', value: p ? p.lieferant : '', placeholder: 'Name oder Link' }),
      aufgabe: el('select', {}, el('option', { value: '', text: 'keine' }), aufgaben.map(a => el('option', { value: String(a.id), text: a.titel }))),
      begruendung: el('input', { maxlength: '500', value: p ? p.begruendung : '' }),
    };
    if (p && p.aufgabe_id) f.aufgabe.value = String(p.aufgabe_id);
    f.inhalt = el('div', { class: 'felder' }, T.feld('Artikel', f.artikel),
      el('div', { class: 'felder zwei' }, T.feld('Bestellnummer', f.bestellnr), T.feld('Menge', f.menge)),
      el('div', { class: 'felder zwei' }, T.feld('Preis', f.preis, 'nur zur Information'), T.feld('Lieferant oder Link', f.lieferant)),
      T.feld('Für die Tätigkeit', f.aufgabe), T.feld('Begründung', f.begruendung));
    f.werte = () => ({ artikel: f.artikel.value, bestellnr: f.bestellnr.value, menge: Number(f.menge.value), preis: f.preis.value,
      lieferant: f.lieferant.value, aufgabe_id: f.aufgabe.value ? Number(f.aufgabe.value) : null, begruendung: f.begruendung.value });
    return f;
  }

  function positionenTabelle(liste, eingereicht, aktionen) {
    if (!liste.length) return el('div', { class: 'leise klein-text', text: 'Noch keine Positionen.' });
    return el('div', { class: 'rollbar' }, el('table', { class: 'liste bestell' },
      el('thead', {}, el('tr', {}, ['Artikel', 'Bestellnr.', 'Menge', 'Preis', 'Lieferant', 'Tätigkeit', eingereicht ? 'Stand' : ''].map(t => el('th', { text: t })))),
      el('tbody', {}, liste.map(p => el('tr', { class: p.gestrichen ? 'gestrichen' : '' },
        el('td', {}, el('b', { text: p.artikel }), p.begruendung ? el('div', { class: 'leise klein-text', text: p.begruendung }) : null),
        el('td', { class: 'mono', text: p.bestellnr }),
        el('td', { text: p.menge_genehmigt && p.menge_genehmigt !== p.menge ? p.menge_genehmigt + ' (statt ' + p.menge + ')' : String(p.menge) }),
        el('td', { text: p.preis }),
        el('td', { class: 'lieferant', text: p.lieferant }),
        el('td', { text: p.aufgabe || '' }),
        el('td', {}, eingereicht ? el('span', { class: 'pos-stand w-' + (p.weg || 'offen'), text: posStatus(p, true) }) : null, aktionen ? aktionen(p) : null))))));
  }

  // --- Team ---

  function teamErzeugen({ ort, basis, beiAenderung }) {
    let D = null;
    let offen = null;   // geoeffneter Vorgang

    async function laden() {
      try { D = await T.api('GET', basis + '/anfragen'); zeichnen(); }
      catch (e) { T.setzen(ort, el('div', { class: 'leer', text: e.message })); }
    }

    async function senden(pfad, daten, meldung) {
      try {
        D = await T.api('POST', basis + pfad, daten);
        zeichnen();
        if (meldung) T.meldung(meldung);
        if (beiAenderung) beiAenderung();
        return true;
      } catch (e) { T.meldung(e.message, true); return false; }
    }

    async function positionDialog(p) {
      const f = positionFelder(p, D.bestellung.aufgaben);
      const ok = await T.dialog({ titel: p ? 'Position ändern' : 'Neue Position', knopf: p ? 'Speichern' : 'Hinzufügen', inhalt: f.inhalt,
        speichern: async () => { D = await T.api('POST', basis + '/bestellung', Object.assign({ aktion: p ? 'position_aendern' : 'position_neu',
          position_id: p ? p.id : undefined }, f.werte())); return true; } });
      if (ok) { zeichnen(); T.meldung('Gespeichert.'); }
    }

    async function anfrageDialog(art) {
      const heute = T.isoDatum(new Date());
      const f = {
        titel: el('input', { required: true, maxlength: '200', placeholder: { rueckfrage: 'z. B. Dürfen wir 24 V nehmen?',
          ausleihe: 'z. B. Anemometer und Labornetzgerät', abnahme: 'z. B. Netzteil-Verdrahtung prüfen' }[art] }),
        text: el('textarea', { rows: '3', maxlength: '2000' }),
        aufgabe: el('select', {}, el('option', { value: '', text: 'keine' }), D.bestellung.aufgaben.map(a => el('option', { value: String(a.id), text: a.titel }))),
        tafel: el('input', { type: 'checkbox' }),
        menge: el('input', { maxlength: '40', value: '1' }),
        von: el('input', { type: 'date', required: true, value: heute }),
        bis: el('input', { type: 'date', required: true, value: heute }),
        foto: el('input', { type: 'file', accept: 'image/*', capture: 'environment' }),
      };
      const ok = await T.dialog({
        titel: { rueckfrage: 'Rückfrage', ausleihe: 'Material ausleihen', abnahme: 'Abnahme / Freigabe' }[art], knopf: 'Absenden',
        inhalt: el('div', { class: 'felder' },
          T.feld({ rueckfrage: 'Frage', ausleihe: 'Was?', abnahme: 'Was soll geprüft werden?' }[art], f.titel),
          art === 'ausleihe' ? el('div', { class: 'felder drei' }, T.feld('Wie viele?', f.menge), T.feld('Ab', f.von), T.feld('Bis', f.bis)) : null,
          T.feld('Details', f.text), T.feld('Zur Tätigkeit', f.aufgabe),
          art === 'rueckfrage' ? el('label', { class: 'haken' }, f.tafel, 'in der Besprechung klären (kommt als Frage auf die Tafel)') : null,
          art === 'abnahme' ? T.feld('Foto (optional)', f.foto, 'Aufbau fotografieren, keine Personen') : null),
        speichern: async () => {
          let bild = null;
          if (art === 'abnahme' && f.foto.files.length) bild = await Besprechung.verkleinern(f.foto.files[0]);
          D = await T.api('POST', basis + '/anfragen', { aktion: 'neu', art, titel: f.titel.value, text: f.text.value,
            aufgabe_id: f.aufgabe.value ? Number(f.aufgabe.value) : null, in_besprechung: f.tafel.checked,
            menge: f.menge.value, von: f.von.value, bis: f.bis.value, bild });
          return true;
        },
      });
      if (ok) { zeichnen(); T.meldung('Anfrage gestellt. Antworten erscheinen im Verlauf der Anfrage.'); if (beiAenderung) beiAenderung(); }
    }

    function zeichnen() {
      if (offen) {
        Vorgang.teamDetail({ ort, basis, id: offen, beiAenderung, zurueck: () => { offen = null; laden(); } });
        return;
      }
      const b = D.bestellung;
      const sammel = b.sammel.positionen.filter(p => !p.gestrichen);
      T.setzen(ort, el('div', { class: 'stapel' },
        el('div', { class: 'zeile' }, el('span', { class: 'etikett', text: 'Neue Anfrage' }),
          el('button', { type: 'button', onclick: () => anfrageDialog('rueckfrage') }, '+ Rückfrage'),
          el('button', { type: 'button', onclick: () => anfrageDialog('ausleihe') }, '+ Material ausleihen'),
          el('button', { type: 'button', onclick: () => anfrageDialog('abnahme') }, '+ Abnahme')),
        el('section', { class: 'karte stapel-eng' },
          el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: 'Bestellliste' }), el('span', { class: 'chip', text: sammel.length === 1 ? '1 Position' : sammel.length + ' Positionen' })),
          el('div', { class: 'banner' + (b.lage.offen ? '' : ' leise') }, lageText(b.lage)),
          positionenTabelle(b.sammel.positionen, false, p => el('span', { class: 'zeile' },
            p.gestrichen ? el('button', { type: 'button', class: 'leicht', onclick: () => senden('/bestellung', { aktion: 'position_streichen', position_id: p.id, gestrichen: false }) }, '↺')
              : [el('button', { type: 'button', class: 'leicht', title: 'ändern', 'aria-label': 'ändern', onclick: () => positionDialog(p) }, '✎'),
                el('button', { type: 'button', class: 'leicht', title: 'streichen', 'aria-label': 'streichen', onclick: () => senden('/bestellung', { aktion: 'position_streichen', position_id: p.id }) }, '✕')])),
          el('div', { class: 'zeile' },
            el('button', { type: 'button', onclick: () => positionDialog() }, '+ Position'),
            el('button', { type: 'button', class: 'haupt', disabled: !b.lage.offen || !sammel.length,
              onclick: () => senden('/bestellung', { aktion: 'einreichen' }, 'Liste eingereicht.') },
              b.lage.offen ? 'Liste einreichen' : b.lage.naechstes ? 'Liste einreichen (ab ' + T.kurzTag(b.lage.naechstes.von) + ')' : 'Liste einreichen')),
          el('p', { class: 'leise klein-text', text: 'Der Preis ist nur zur Information und hat keinen Einfluss auf die Bestellung.' })),
        b.eingereicht.length ? el('section', { class: 'karte stapel-eng' },
          el('h2', { class: 'dreieck', text: 'Eingereichte Listen' }),
          b.eingereicht.map(l => el('details', { class: 'protokoll', open: l === b.eingereicht[0] ? true : null },
            el('summary', {}, el('b', { text: 'Liste vom ' + T.zeitText(l.eingereicht) }), ' · ' + (l.geprueft ? 'geprüft' : 'in Prüfung') +
              ' · ' + l.positionen.filter(p => !p.gestrichen).length + ' Positionen'),
            positionenTabelle(l.positionen.filter(p => !p.gestrichen), true, p => (p.entscheidung === 'ablehnen' || p.weg === 'ersatz_gesucht')
              ? el('button', { type: 'button', class: 'leicht', onclick: () => senden('/bestellung', { aktion: 'uebernehmen', position_id: p.id }, 'In die nächste Liste übernommen.') }, 'in nächste Liste')
              : null)))) : null,
        el('section', { class: 'karte stapel-eng' },
          el('h2', { class: 'dreieck', text: 'Anfragen' }),
          Vorgang.teamListe(D.anfragen, id => { offen = id; zeichnen(); }))));
    }

    return { laden };
  }

  // --- Lehrkraft ---

  // Kopf mit den beiden Reitern der Anfragen-Seite
  function kopf(aktiv) {
    return el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Anfragen' }),
      el('span', { class: 'umschalter' },
        el('a', { class: 'knopf' + (aktiv === 'eingang' ? ' an' : ''), href: '#anfragen' }, 'Eingang'),
        el('a', { class: 'knopf' + (aktiv === 'fenster' ? ' an' : ''), href: '#anfragen/fenster' }, 'Einreichfenster')),
      el('span', { class: 'rechts' }, Vorgang.glocke()));
  }

  async function lehrerZeigen(teil, id) {
    if (teil === 'liste') return listeZeigen(Number(id));
    if (teil === 'sammel') return sammelZeigen(Number(id));
    if (teil === 'fenster') return fensterZeigen();
    return Vorgang.eingang(teil === 'v' ? Number(id) : null);
  }

  async function fensterZeigen() {
    titelSetzen('Einreichfenster');
    const d = await T.api('GET', '/api/anfragen');
    const fensterKarte = el('section', { class: 'karte stapel-eng' },
      el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: 'Einreichfenster für Bestelllisten' }),
        el('span', { class: 'rechts' }, el('button', { type: 'button', onclick: async () => { if (await fensterDialog(d.bestellung)) zeigen(); } }, '+ Einreichfenster'))),
      d.bestellung.fenster.length ? d.bestellung.fenster.map(f => el('div', { class: 'fenster' + (f.laeuft ? ' laeuft' : '') },
        el('div', { class: 'zeile' },
          el('b', { text: T.kurzTag(f.von) + ' bis ' + stichtag(f.bis) }),
          el('span', { class: 'chip blau', text: f.projekt ? 'Sonderfenster ' + f.projekt : f.klasse || 'alle meine Projekte' }),
          el('span', { class: 'chip' + (f.laeuft ? ' blau' : ''), text: f.laeuft ? 'läuft' : f.vorbei ? 'vorbei' : 'kommt' }),
          el('span', { class: 'rechts' },
            el('a', { class: 'knopf klein', href: '#anfragen/sammel/' + f.id }, 'Sammelbestellung'),
            el('button', { type: 'button', class: 'leicht', onclick: () => stichtagDialog(f) }, 'Stichtag'),
            el('button', { type: 'button', class: 'leicht', onclick: () => fensterBeenden(f) }, 'Beenden'))),
        el('div', { class: 'rollbar' }, el('table', { class: 'liste' }, el('tbody', {}, f.teams.map(t => el('tr', {},
          el('td', {}, el('a', { href: '#projekt/' + t.projekt_id, text: t.titel })),
          el('td', {}, el('span', { class: 'chip' + (t.stand === 'eingereicht' ? ' blau' : ''), text: { eingereicht: 'eingereicht', geprueft: 'geprüft',
            sammelt: 'sammelt, noch nicht eingereicht', leer: 'nichts gesammelt' }[t.stand] })),
          el('td', { class: 'leise', text: (t.positionen === 1 ? '1 Position' : t.positionen + ' Positionen') + (t.offen ? ' · ' + t.offen + ' offen' : '') +
            (t.eingereicht ? ' · ' + T.zeitText(t.eingereicht) : '') }),
          el('td', {}, t.liste_id ? el('a', { class: 'knopf klein' + (t.stand === 'eingereicht' ? ' haupt' : ''), href: '#anfragen/liste/' + t.liste_id }, 'Prüfen') : null))))))))
        : el('div', { class: 'leise klein-text', text: 'Noch kein Einreichfenster. Teams sammeln trotzdem schon und reichen ein, sobald ein Fenster offen ist.' }));
    T.setzen(inhalt, kopf('fenster'), fensterKarte);
    Vorgang.zaehlerZeigen(d.zaehler);
  }

  // Einreichfenster festlegen; aus einer Rueckfrage (anfrageId) als Sonderfenster, das dann im Verlauf steht
  async function fensterDialog(b, sonderFuer, anfrageId) {
    const heute = T.isoDatum(new Date());
    const f = {
      von: el('input', { type: 'date', required: true, value: heute }),
      bisTag: el('input', { type: 'date', required: true, value: heute }),
      bisZeit: el('input', { type: 'time', required: true, value: '12:00' }),
      fuer: el('select', {}, el('option', { value: '', text: 'alle meine Projekte' }),
        b.klassen.map(k => el('option', { value: 'k:' + k, text: 'Klasse ' + k })),
        b.projekte.map(p => el('option', { value: 'p:' + p.id, text: 'Sonderfenster: ' + p.titel + ' (' + p.klasse + ')' }))),
    };
    if (sonderFuer) f.fuer.value = 'p:' + sonderFuer;
    const ok = await T.dialog({ titel: 'Einreichfenster', knopf: 'Festlegen',
      inhalt: el('div', { class: 'felder' }, T.feld('Für', f.fuer, 'Ein Sonderfenster steht im Verlauf des Projekts.'),
        el('div', { class: 'felder drei' }, T.feld('Von', f.von), T.feld('Stichtag', f.bisTag), T.feld('um', f.bisZeit))),
      speichern: () => {
        const w = f.fuer.value;
        return T.api('POST', '/api/bestellfenster', { von: f.von.value, bis: f.bisTag.value + 'T' + f.bisZeit.value,
          klasse: w.startsWith('k:') ? w.slice(2) : '', projekt_id: w.startsWith('p:') ? Number(w.slice(2)) : null,
          anfrage_id: anfrageId && w === 'p:' + sonderFuer ? anfrageId : null });
      } });
    if (ok) T.meldung('Einreichfenster festgelegt.');
    return !!ok;
  }

  async function stichtagDialog(f) {
    const tag = el('input', { type: 'date', required: true, value: f.bis.slice(0, 10) });
    const zeit = el('input', { type: 'time', required: true, value: f.bis.slice(11, 16) });
    const ok = await T.dialog({ titel: 'Stichtag ändern', inhalt: el('div', { class: 'felder zwei' }, T.feld('Stichtag', tag), T.feld('um', zeit)),
      speichern: () => T.api('POST', '/api/bestellfenster/' + f.id, { bis: tag.value + 'T' + zeit.value }) });
    if (ok) { T.meldung('Gespeichert.'); zeigen(); }
  }

  async function fensterBeenden(f) {
    const ok = await T.dialog({ titel: 'Einreichfenster beenden?', knopf: 'Beenden', gefaehrlich: true,
      inhalt: el('p', { text: 'Das Fenster verschwindet aus der Liste. Eingereichte Listen bleiben erhalten.' }),
      speichern: () => T.api('POST', '/api/bestellfenster/' + f.id, { aktiv: false }) });
    if (ok) zeigen();
  }

  // Pruefen einer Liste je Position
  async function listeZeigen(lid) {
    let L = (await T.api('GET', '/api/bestellliste/' + lid)).liste;
    titelSetzen('Bestellliste · ' + L.titel);
    const ort = el('div');

    async function entscheiden(p, e, menge) {
      const daten = { aktion: 'entscheiden', position_id: p.id, entscheidung: e, menge_genehmigt: menge !== p.menge ? menge : null, kommentar: '' };
      if (e === 'lager' || e === 'ablehnen' || e === 'ersetzen') {
        const f = {
          kommentar: el('input', { maxlength: '500', required: e === 'ablehnen', value: p.kommentar || '',
            placeholder: e === 'lager' ? 'z. B. Regal B3, 6 Stück' : e === 'ablehnen' ? 'Warum?' : 'Hinweis für das Team (wenn ihr keinen Ersatz eintragt)' }),
          artikel: el('input', { maxlength: '200', value: p.ersatz_artikel || '' }),
          nr: el('input', { maxlength: '80', value: p.ersatz_bestellnr || '' }),
          lieferant: el('input', { maxlength: '300', value: p.ersatz_lieferant || p.lieferant }),
          weg: el('select', {}, el('option', { value: 'bestellen', text: 'bestellen' }), el('option', { value: 'lager', text: 'aus dem SchulLager' })),
        };
        if (p.ersatz_weg) f.weg.value = p.ersatz_weg;
        const ok = await T.dialog({ titel: p.artikel + ' · ' + { lager: 'SchulLager', ablehnen: 'Ablehnen', ersetzen: 'Ersetzen' }[e], knopf: 'Übernehmen',
          inhalt: el('div', { class: 'felder' },
            e === 'ersetzen' ? [T.feld('Ersatzartikel', f.artikel, 'leer lassen: das Team sucht selbst einen Ersatz'),
              el('div', { class: 'felder zwei' }, T.feld('Bestellnummer', f.nr), T.feld('Lieferant', f.lieferant)), T.feld('Ersatz', f.weg)] : null,
            T.feld(e === 'lager' ? 'Lagerort' : e === 'ablehnen' ? 'Kommentar für das Team' : 'Hinweis', f.kommentar)),
          speichern: () => {
            Object.assign(daten, { kommentar: f.kommentar.value, ersatz_artikel: f.artikel.value, ersatz_bestellnr: f.nr.value,
              ersatz_lieferant: f.lieferant.value, ersatz_weg: f.weg.value });
            return true;
          } });
        if (!ok) return;
      }
      senden(daten);
    }

    async function senden(daten) {
      try { L = (await T.api('POST', '/api/projekte/' + L.projekt_id + '/bestellung', daten)).liste; zeichnen(); }
      catch (e) { T.meldung(e.message, true); }
    }

    function zeichnen() {
      const pos = L.positionen.filter(p => !p.gestrichen);
      T.setzen(ort, el('section', { class: 'karte stapel-eng' },
        el('div', { class: 'zeile' }, el('h2', { class: 'dreieck', text: L.titel }),
          el('span', { class: 'leise', text: 'eingereicht ' + T.zeitText(L.eingereicht) }),
          el('span', { class: 'chip' + (L.geprueft ? '' : ' blau'), text: L.geprueft ? 'geprüft' : 'in Prüfung' })),
        el('div', { class: 'rollbar' }, el('table', { class: 'liste pruefen' },
          el('thead', {}, el('tr', {}, ['Artikel', 'Menge', 'Woher?', 'Details'].map(t => el('th', { text: t })))),
          el('tbody', {}, pos.map(p => {
            const menge = el('input', { type: 'number', min: '1', max: '9999', class: 'menge', value: String(p.menge_genehmigt || p.menge), 'aria-label': 'Menge' });
            const stati = p.weg === 'bestellen' ? ['', 'bestellt', 'geliefert', 'ausgegeben'] : p.weg === 'lager' ? ['', 'ausgegeben'] : null;
            const statusWahl = stati ? el('select', { class: 'klein', 'aria-label': 'Status', onchange: ev => senden({ aktion: 'status', position_id: p.id, status: ev.target.value || null }) },
              stati.map(s => el('option', { value: s, text: s || 'noch offen' }))) : null;
            if (statusWahl) statusWahl.value = p.status || '';
            return el('tr', {},
              el('td', {}, el('b', { text: p.artikel }), el('div', { class: 'leise klein-text', text: [p.bestellnr, p.lieferant, p.preis].filter(Boolean).join(' · ') }),
                p.aufgabe ? el('div', { class: 'leise klein-text', text: 'Tätigkeit: ' + p.aufgabe }) : null,
                p.begruendung ? el('div', { class: 'klein-text', text: p.begruendung }) : null),
              el('td', {}, menge, p.menge_genehmigt && p.menge_genehmigt !== p.menge ? el('div', { class: 'leise klein-text', text: 'beantragt ' + p.menge }) : null),
              el('td', {}, el('div', { class: 'umschalter wege' }, WEGE.map(([w, t]) => el('button', { type: 'button', class: p.entscheidung === w ? 'an' : '',
                onclick: () => entscheiden(p, w, Number(menge.value)) }, t)))),
              el('td', {}, el('div', { class: 'pos-stand w-' + (p.weg || 'offen'), text: posStatus(p, true) }), statusWahl));
          }))))));
    }

    T.setzen(inhalt, el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Bestellliste prüfen' }),
      el('a', { class: 'knopf', href: '#anfragen/fenster' }, 'Zu den Einreichfenstern'), el('a', { class: 'knopf', href: '#projekt/' + L.projekt_id }, 'Zum Projekt')), ort);
    zeichnen();
  }

  async function sammelZeigen(fid) {
    const s = (await T.api('GET', '/api/bestellfenster/' + fid + '/sammelbestellung')).sammelbestellung;
    titelSetzen('Sammelbestellung');
    const f = s.fenster;
    T.setzen(inhalt,
      el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Sammelbestellung' }),
        el('a', { class: 'knopf', href: '/api/bestellfenster/' + fid + '/sammelbestellung.csv', download: '' }, 'Excel (CSV)'),
        el('button', { type: 'button', onclick: () => window.print() }, 'Drucken / PDF'),
        el('a', { class: 'knopf', href: '#anfragen/fenster' }, 'Zurück')),
      el('p', { class: 'leise', text: 'Einreichfenster ' + T.kurzTag(f.von) + ' bis ' + stichtag(f.bis) +
        '. Nur Positionen mit „Bestellen“ (auch Ersatzartikel), je Lieferant, gleiche Bestellnummern zusammengefasst. Preise nur zur Information.' }),
      s.lieferanten.length ? s.lieferanten.map(g => el('section', { class: 'karte stapel-eng sammel' },
        el('h2', { class: 'dreieck', text: (g.lieferant || 'ohne Lieferant, bitte zuordnen') }),
        el('div', { class: 'rollbar' }, el('table', { class: 'liste' },
          el('thead', {}, el('tr', {}, ['Artikel', 'Bestellnr.', 'Menge', 'Preis', 'Teams'].map(t => el('th', { text: t })))),
          el('tbody', {}, g.zeilen.map(z => el('tr', {}, el('td', { text: z.artikel }), el('td', { class: 'mono', text: z.bestellnr }),
            el('td', { text: String(z.menge) }), el('td', { text: z.preis }), el('td', { text: z.teams.join(', ') }))))))))
        : el('div', { class: 'leer', text: 'Noch keine Position zum Bestellen entschieden.' }));
  }

  return { teamErzeugen, lehrerZeigen, kopf, fensterDialog };
})();
