// Besprechungstafel: interaktiv fuer das Smartboard (/tafel?projekt=<id>, Lehrkraft) und eingefroren zum Ansehen im
// Protokoll (Team und Lehrkraft). Die Tafel ist 1600 x 900 Einheiten gross und wird auf den Bildschirm skaliert.
// Zonen: Seit letztem Mal | Skizzen & Ideen | Ergebnis (Absprachen, Auftraege, Meilensteine). Ein Post-it, das in eine
// Ergebnis-Zone gezogen wird, wird sofort zu diesem Ergebnis (Auftrag: Frist waehlen). Stift, Finger und Maus gleich.
'use strict';

const Tafel = (() => {
  const el = T.el;
  const B = 1600, H = 900, GI = 450, GE = 1060;
  const ART = { auftrag: 'Auftrag', problem: 'Problem', frage: 'Frage', thema: 'Thema', idee: 'Idee', aenderung: 'Änderung im Raster',
    absprache: 'Absprache', meilenstein: 'Meilenstein' };
  const FARBEN = ['#1d2433', '#00639C', '#D4005E', '#3d8b00', '#e07b00'];
  const MARKER_FARBEN = ['#f5c400', '#7fd13b', '#ff6fb0', '#4fb3ff'];
  const STICKER = [['idee', 'Idee', '#c98a1e'], ['problem', 'Problem', '#c98a1e'], ['frage', 'Frage', '#6f62d6'], ['ok', 'erledigt', '#4f8a1a'],
    ['nein', 'verworfen', '#c43b3b'], ['stern', 'wichtig', '#c98a1e'], ['ziel', 'Ziel', '#2f7fc0'], ['uhr', 'Zeit', '#2f7fc0'],
    ['flagge', 'Meilenstein', '#2f7fc0'], ['gut', 'gut', '#4f8a1a'], ['schlecht', 'schlecht', '#c43b3b'], ['team', 'Team', '#5d6779'],
    ['fertigung', 'Fertigung', '#5d6779'], ['elektrik', 'Elektrik', '#5d6779'], ['mechanik', 'Mechanik', '#5d6779'],
    ['programm', 'Programm', '#5d6779'], ['material', 'Material', '#5d6779'], ['mass', 'Maß', '#5d6779']];
  const STICKER_INFO = Object.fromEntries(STICKER.map(([k, name, farbe]) => [k, { name, farbe }]));
  const SG = 46;   // Groesse eines freien Stickers (Tafel-Einheiten)
  const ERGEBNIS = ['absprachen', 'auftraege', 'meilensteine'];
  const PB = 205, PH = 86;   // Post-it-Groesse

  const zoneBei = (x, y) => x < GI ? 'seit' : x < GE ? 'ideen' : y < H / 3 ? 'absprachen' : y < 2 * H / 3 ? 'auftraege' : 'meilensteine';
  const breite = z => ERGEBNIS.includes(z.zone) ? 245 : PB;
  const passt = (z, pos) => {   // liegt die gespeicherte Position in einer erlaubten Zone?
    const zb = zoneBei(pos[0] + breite(z) / 2, pos[1] + PH / 2);
    return ERGEBNIS.includes(z.zone) ? zb === z.zone : !ERGEBNIS.includes(zb);
  };

  // Positionen: gespeicherte (oder schon einmal vergebene), sonst der erste freie Platz der Zone. Post-its in einem
  // Rahmen (imRahmen) behalten ihren Platz in jeder Zone, sie gehen mit dem Rahmen.
  function anordnen(postits, positionen, imRahmen) {
    const plaetze = {
      seit: i => [12 + (i % 2) * (PB + 8), 56 + Math.floor(i / 2) * (PH + 10)],
      ideen: i => [GI + 12 + (i % 2) * (PB + 8), 56 + Math.floor(i / 2) * (PH + 10)],
      absprachen: i => [GE + 12 + (i % 2) * 257, 40 + Math.floor(i / 2) * (PH + 8)],
      auftraege: i => [GE + 12 + (i % 2) * 257, H / 3 + 40 + Math.floor(i / 2) * (PH + 8)],
      meilensteine: i => [GE + 12 + (i % 2) * 257, 2 * H / 3 + 40 + Math.floor(i / 2) * (PH + 8)],
    };
    const pos = {}, belegt = [];
    const frei = (x, y, b) => !belegt.some(r => x < r[0] + r[2] && r[0] < x + b && y < r[1] + PH && r[1] < y + PH);
    const offen = [];
    for (const z of postits) {
      const p = positionen[z.key];
      if (p && (passt(z, p) || (imRahmen && imRahmen.has(z.key)))) { pos[z.key] = p; belegt.push([p[0], p[1], breite(z)]); } else offen.push(z);
    }
    for (const z of offen) {
      let x, y;
      for (let i = 0; i < 60; i++) {
        [x, y] = plaetze[z.zone](i);
        x = Math.min(x, B - breite(z)); y = Math.min(y, H - PH);
        if (frei(x, y, breite(z))) break;
      }
      pos[z.key] = [x, y];
      belegt.push([x, y, breite(z)]);
    }
    return pos;
  }

  function untertext(z) {
    if (z.art === 'auftrag') return z.erledigt ? '✓ abgehakt ' + T.zeitText(z.erledigt) : (z.ueberfaellig ? '✕ fällig ' : 'bis ') +
      (z.frist ? z.frist.slice(8, 10) + '.' + z.frist.slice(5, 7) + '.' : '') + (z.verantwortlich ? ' · ' + z.verantwortlich : '');
    if (z.art === 'problem') return (z.ampel === 'r' ? 'R' : 'Y') + ' seit ' + T.kwText(z.seit) + ' · ' + z.aufgabe + (z.massnahme ? ' → ' + z.massnahme : '');
    if (z.art === 'meilenstein') return z.frist ? T.kwText(z.frist) : '';
    if (z.erledigt) return '✓ geklärt';
    if (z.wer_art === 'team') return 'Team · ' + T.zeitText(z.erstellt).split(' ').pop();
    return '';
  }

  function zettelElement(z, pos, bildBasis) {
    return el('div', { class: 'pi ' + z.art + (z.ampel ? ' amp-' + z.ampel : '') + (z.erledigt ? ' erl' : '') + (z.ueberfaellig ? ' ueber' : ''),
      'data-key': z.key, style: 'left:' + pos[0] + 'px;top:' + pos[1] + 'px;width:' + breite(z) + 'px' },
      el('div', { class: 'pi-art', text: ART[z.art] || z.art }),
      z.bild ? el('img', { class: 'pi-bild', src: bildBasis + '/bild/' + z.bild, alt: z.text, draggable: 'false' }) : null,
      el('div', { class: 'pi-text', text: z.text }),
      el('div', { class: 'pi-unter', text: untertext(z) }));
  }

  function zonen() {
    const kopf = (text, x, y, b) => el('div', { class: 'tz-kopf', style: 'left:' + x + 'px;top:' + y + 'px;width:' + b + 'px', text });
    return [
      el('div', { class: 'tz seit', style: 'left:0;top:0;width:' + GI + 'px;height:' + H + 'px' }),
      el('div', { class: 'tz ideen', style: 'left:' + GI + 'px;top:0;width:' + (GE - GI) + 'px;height:' + H + 'px' }),
      ['absprachen', 'auftraege', 'meilensteine'].map((z, i) => el('div', { class: 'tz ergebnis ' + z,
        style: 'left:' + GE + 'px;top:' + (i * H / 3) + 'px;width:' + (B - GE) + 'px;height:' + (H / 3) + 'px' })),
      kopf('Seit letztem Mal', 12, 10, GI - 24), kopf('Skizzen & Ideen', GI + 12, 10, GE - GI - 24),
      kopf('Absprachen', GE + 12, 6, 300), kopf('Aufträge', GE + 12, H / 3 + 6, 300), kopf('Meilensteine', GE + 12, 2 * H / 3 + 6, 300)];
  }

  // Alles, was auf die Zeichenflaeche gehoert: Striche (Textmarker halbdurchsichtig), Pfeile, ein Pfeil im Entstehen
  function zeichneStriche(ctx, striche, pfeile, ende, neu) {
    ctx.clearRect(0, 0, B, H);
    for (const s of striche) zeichneStrich(ctx, s);
    for (const p of (pfeile || []).concat(neu ? [neu] : [])) zeichnePfeil(ctx, p, ende || (e => [e.x, e.y]));
  }

  function zeichnePfeil(ctx, p, ende) {
    const a = ende(p.a), b = ende(p.b);
    if (!a || !b) return;
    const w = Math.atan2(b[1] - a[1], b[0] - a[0]), l = 22;
    ctx.save();
    ctx.globalAlpha = 1;
    ctx.strokeStyle = p.farbe; ctx.lineWidth = 4; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]);
    ctx.moveTo(b[0] - l * Math.cos(w - .45), b[1] - l * Math.sin(w - .45)); ctx.lineTo(b[0], b[1]);
    ctx.lineTo(b[0] - l * Math.cos(w + .45), b[1] - l * Math.sin(w + .45));
    ctx.stroke();
    ctx.restore();
  }

  // Ende eines Pfeils in Tafel-Koordinaten: haftet es an einem Post-it, zaehlt dessen aktuelle Lage auf der Tafel
  function pfeilEnde(zettelOrt) {
    return e => {
      if (e.key) {
        const pi = zettelOrt.querySelector('.pi[data-key="' + CSS.escape(e.key) + '"]');
        if (!pi) return null;
        return [pi.offsetLeft + e.rx * pi.offsetWidth, pi.offsetTop + e.ry * pi.offsetHeight];
      }
      if (e.rahmen) {
        const r = zettelOrt.querySelector('.t-rahmen[data-id="' + e.rahmen + '"]');
        if (!r) return null;
        return [r.offsetLeft + e.rx * r.offsetWidth, r.offsetTop + e.ry * r.offsetHeight];
      }
      return [e.x, e.y];
    };
  }

  // Rahmen um eine Skizze: Titel oben links, Marke rechts, sobald er ein Ergebnis ist, Griff unten rechts zum Vergroessern
  const ERG_TEXT = { absprache: 'Absprache', auftrag: 'Auftrag', meilenstein: 'Meilenstein' };
  function rahmenElement(r, aktiv) {
    const e = r.ergebnis;
    return el('div', { class: 't-rahmen' + (e ? ' ergebnis' : ''), 'data-id': String(r.id),
      style: 'left:' + r.x + 'px;top:' + r.y + 'px;width:' + r.w + 'px;height:' + r.h + 'px' },
      el('span', { class: 'r-titel', text: r.titel }),
      e ? el('span', { class: 'r-marke', text: ERG_TEXT[e.art] + (e.frist ? ' · bis ' + e.frist.slice(8, 10) + '.' + e.frist.slice(5, 7) + '.' : '') }) : null,
      aktiv ? el('span', { class: 'r-griff', title: 'Größe ändern' }) : null);
  }

  // Die Tafel (oder ein Ausschnitt, z. B. ein Rahmen) als Bild malen: fuer "Als Bild" und fuer das PDF
  const PI_FARBE = { auftrag: '#fff3b0', problem: '#ffe0ec', frage: '#dbeefa', thema: '#e6e9fb', idee: '#e7f4c8', aenderung: '#eef0f3',
    absprache: '#d6f0cf', meilenstein: '#ffffff' };
  function zeilen(ctx, text, breite, max) {
    const woerter = String(text || '').split(/\s+/), aus = [];
    let z = '';
    for (const w of woerter) {
      const probe = z ? z + ' ' + w : w;
      if (ctx.measureText(probe).width > breite && z) { aus.push(z); z = w; } else z = probe;
      if (aus.length === max) break;
    }
    if (aus.length < max && z) aus.push(z);
    return aus;
  }
  function tafelMalen(ctx, d, pos, groesse, opt = {}) {
    const o = d.objekte || {}, rahmen = o.rahmen || [];
    ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, B, H);
    if (opt.zonen) {
      ctx.fillStyle = '#f6f8fb'; ctx.fillRect(0, 0, GI, H);
      ctx.fillStyle = '#f3f9ef'; ctx.fillRect(GE, 0, B - GE, H);
      ctx.strokeStyle = '#c9d2dc'; ctx.lineWidth = 2; ctx.setLineDash([8, 6]);
      ctx.beginPath(); ctx.moveTo(GI, 0); ctx.lineTo(GI, H); ctx.moveTo(GE, 0); ctx.lineTo(GE, H);
      ctx.moveTo(GE, H / 3); ctx.lineTo(B, H / 3); ctx.moveTo(GE, 2 * H / 3); ctx.lineTo(B, 2 * H / 3); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#6b7686'; ctx.font = '700 15px Barlow, "Segoe UI", sans-serif';
      [['SEIT LETZTEM MAL', 12, 28], ['SKIZZEN & IDEEN', GI + 12, 28], ['ABSPRACHEN', GE + 12, 24], ['AUFTRÄGE', GE + 12, H / 3 + 24],
        ['MEILENSTEINE', GE + 12, 2 * H / 3 + 24]].forEach(([t, x, y]) => ctx.fillText(t, x, y));
    }
    for (const r of rahmen) {
      ctx.fillStyle = 'rgba(232,242,249,.45)'; ctx.fillRect(r.x, r.y, r.w, r.h);
      ctx.strokeStyle = r.ergebnis ? '#00639C' : '#7fb1cf'; ctx.lineWidth = 2; ctx.strokeRect(r.x, r.y, r.w, r.h);
      ctx.font = '700 14px Barlow, "Segoe UI", sans-serif';
      const tb = ctx.measureText(r.titel).width + 14;
      ctx.fillStyle = '#ffffff'; ctx.fillRect(r.x + 8, r.y - 10, tb, 20);
      ctx.fillStyle = '#00639C'; ctx.fillText(r.titel, r.x + 15, r.y + 5);
    }
    for (const z of d.postits) {
      const p = pos[z.key];
      if (!p) continue;
      const [w, h] = groesse(z);
      ctx.save();
      ctx.shadowColor = 'rgba(16,24,40,.18)'; ctx.shadowBlur = 6; ctx.shadowOffsetY = 2;
      ctx.fillStyle = PI_FARBE[z.art] || '#fff7c2'; ctx.fillRect(p[0], p[1], w, h);
      ctx.restore();
      if (z.art === 'meilenstein') { ctx.strokeStyle = '#00639C'; ctx.lineWidth = 2; ctx.strokeRect(p[0] + 1, p[1] + 1, w - 2, h - 2); }
      ctx.fillStyle = 'rgba(29,36,51,.6)'; ctx.font = '700 11px Barlow, "Segoe UI", sans-serif';
      ctx.fillText((ART[z.art] || z.art).toUpperCase(), p[0] + 9, p[1] + 17);
      ctx.fillStyle = '#1d2433'; ctx.font = '600 15px Barlow, "Segoe UI", sans-serif';
      zeilen(ctx, z.text, w - 18, 3).forEach((zeile, i) => ctx.fillText(zeile, p[0] + 9, p[1] + 36 + i * 18));
      if (z.erledigt) { ctx.strokeStyle = 'rgba(29,36,51,.5)'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(p[0] + 9, p[1] + 31); ctx.lineTo(p[0] + w - 9, p[1] + 31); ctx.stroke(); }
    }
    for (const s of d.striche) zeichneStrich(ctx, s);
    const ende = e => {
      if (e.key) { const z = d.postits.find(x => x.key === e.key), p = pos[e.key]; if (!z || !p) return null; const [w, h] = groesse(z); return [p[0] + e.rx * w, p[1] + e.ry * h]; }
      if (e.rahmen) { const r = rahmen.find(x => x.id === e.rahmen); return r ? [r.x + e.rx * r.w, r.y + e.ry * r.h] : null; }
      return [e.x, e.y];
    };
    for (const p of o.pfeile || []) zeichnePfeil(ctx, p, ende);
    for (const s of o.sticker || []) {
      let x, y, g;
      if (s.key) { const p = pos[s.key]; if (!p) continue; x = p[0] - 14; y = p[1] - 16; g = 38; } else { x = s.x; y = s.y; g = SG; }
      ctx.fillStyle = '#ffffff'; ctx.beginPath(); ctx.arc(x + g / 2, y + g / 2, g / 2, 0, 7); ctx.fill();
      ctx.save(); ctx.translate(x + g * .16, y + g * .16); ctx.scale(g * .68 / 24, g * .68 / 24);
      ctx.strokeStyle = (STICKER_INFO[s.art] || STICKER_INFO.idee).farbe; ctx.lineWidth = 2; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      ctx.stroke(new Path2D(T.SYMBOLE['st_' + s.art] || T.SYMBOLE.st_idee)); ctx.restore();
    }
  }

  // Bild (PNG/JPEG als data:-URL) der ganzen Tafel oder eines Ausschnitts [x, y, w, h]
  function bildErzeugen(d, pos, groesse, { ausschnitt, faktor = 2, typ = 'image/png', zonen = true } = {}) {
    const [ax, ay, aw, ah] = ausschnitt || [0, 0, B, H];
    const c = document.createElement('canvas');
    c.width = Math.round(aw * faktor); c.height = Math.round(ah * faktor);
    const ctx = c.getContext('2d');
    ctx.scale(faktor, faktor); ctx.translate(-ax, -ay);
    tafelMalen(ctx, d, pos, groesse, { zonen });
    return c.toDataURL(typ, .9);
  }

  function herunterladen(dataUrl, name) {
    const a = el('a', { href: dataUrl, download: name });
    document.body.appendChild(a); a.click(); a.remove();
  }

  function stickerElement(s) {
    const info = STICKER_INFO[s.art] || STICKER_INFO.idee;
    const e = el('div', { class: 'st' + (s.key ? ' haftet' : ''), 'data-sid': String(s.id), title: info.name, style: 'color:' + info.farbe +
      (s.key ? '' : ';left:' + s.x + 'px;top:' + s.y + 'px') }, T.symbol('st_' + s.art));
    return e;
  }

  // Sticker setzen: auf einem Post-it an dessen Ecke, sonst frei auf der Tafel
  function stickerSetzen(zettelOrt, sticker) {
    zettelOrt.querySelectorAll('.st').forEach(x => x.remove());
    for (const s of sticker || []) {
      const ziel = s.key ? zettelOrt.querySelector('.pi[data-key="' + CSS.escape(s.key) + '"]') : zettelOrt;
      if (ziel) ziel.appendChild(stickerElement(s));
    }
  }

  function zeichneStrich(ctx, s) {
    ctx.strokeStyle = s.farbe;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    const p = s.punkte;
    if (s.marker) {   // Textmarker: gleichmaessig breit, halbdurchsichtig
      ctx.save();
      ctx.globalAlpha = .38; ctx.lineWidth = s.breite;
      ctx.beginPath(); p.forEach((q, i) => i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1]));
      if (p.length === 1) ctx.lineTo(p[0][0] + .1, p[0][1]);
      ctx.stroke(); ctx.restore();
      return;
    }
    if (p.length === 1) { ctx.fillStyle = s.farbe; ctx.beginPath(); ctx.arc(p[0][0], p[0][1], s.breite / 2, 0, 7); ctx.fill(); return; }
    for (let i = 1; i < p.length; i++) {
      ctx.lineWidth = s.breite * (0.5 + (p[i][2] === undefined ? .5 : p[i][2]));
      ctx.beginPath(); ctx.moveTo(p[i - 1][0], p[i - 1][1]); ctx.lineTo(p[i][0], p[i][1]); ctx.stroke();
    }
  }

  // Tafel in einen Rahmen setzen und auf dessen Groesse skalieren
  function aufbauen(rahmen) {
    const flaeche = el('div', { class: 'tafel' });
    const canvas = el('canvas', { class: 'tafel-canvas', width: String(B), height: String(H) });
    const zettel = el('div', { class: 'tafel-zettel' });
    T.setzen(flaeche, zonen(), canvas, zettel);
    T.setzen(rahmen, flaeche);
    const t = { flaeche, canvas, zettel, ctx: canvas.getContext('2d'), skala: 1 };
    t.anpassen = () => {
      const r = rahmen.getBoundingClientRect();
      t.skala = Math.max(0.1, Math.min(r.width / B, r.height / H));
      flaeche.style.transform = 'scale(' + t.skala + ')';
      flaeche.style.left = Math.max(0, (r.width - B * t.skala) / 2) + 'px';
      flaeche.style.top = Math.max(0, (r.height - H * t.skala) / 2) + 'px';
    };
    t.punkt = ev => {
      const r = flaeche.getBoundingClientRect();
      return [Math.round((ev.clientX - r.left) / t.skala), Math.round((ev.clientY - r.top) / t.skala)];
    };
    window.addEventListener('resize', t.anpassen);
    t.anpassen();
    return t;
  }

  // --- Eingefroren ansehen (Protokoll) ---

  async function ansehen(url, bildBasis) {
    let d;
    try { d = (await T.api('GET', url)).tafel; } catch (e) { T.meldung(e.message, true); return; }
    const rahmen = el('div', { class: 'tafel-rahmen' });
    const schliessen = () => { huelle.remove(); window.removeEventListener('keydown', taste); };
    const taste = ev => { if (ev.key === 'Escape') schliessen(); };
    const huelle = el('div', { class: 'tafel-ansicht', role: 'dialog', 'aria-label': 'Tafel' },
      el('div', { class: 'tafel-leiste' }, el('b', { text: 'Tafel ' + T.kwText(d.woche) }),
        el('span', { class: 'leise', text: (d.termin ? T.kurzTag(d.termin.datum) + ', ' + d.termin.uhrzeit + ' · ' : '') +
          'eingefroren ' + T.zeitText(d.abgeschlossen) }),
        el('button', { type: 'button', class: 'rechts-btn', onclick: schliessen }, 'Schließen')), rahmen);
    document.body.appendChild(huelle);
    window.addEventListener('keydown', taste);
    const t = aufbauen(rahmen);
    eingefrorenZeichnen(t, d, bildBasis);
  }

  const rahmenKeys = o => new Set((o && o.rahmen || []).flatMap(r => r.postits || []));

  function eingefrorenZeichnen(t, d, bildBasis) {
    const o = d.objekte || {};
    const pos = anordnen(d.postits, d.positionen || {}, rahmenKeys(o));
    T.setzen(t.zettel, (o.rahmen || []).map(r => rahmenElement(r, false)), d.postits.map(z => zettelElement(z, pos[z.key], bildBasis)));
    stickerSetzen(t.zettel, o.sticker);
    zeichneStriche(t.ctx, d.striche, o.pfeile, pfeilEnde(t.zettel));
  }

  // --- Interaktiv am Board ---

  async function starten(ort) {
    const pid = Number(new URLSearchParams(location.search).get('projekt'));
    const basis = '/api/projekte/' + pid;
    let D;
    try { D = (await T.api('GET', basis + '/tafel')).tafel; }
    catch (e) {
      if (e.status === 401) { location.replace('/anmelden'); return; }
      T.setzen(ort, el('div', { class: 'leer', text: e.message }));
      return;
    }
    document.title = 'Tafel · ' + D.projekt.titel + ' · ' + T.NAME;
    const S = { werkzeug: 'zeiger', farbe: FARBEN[0], dicke: 4, markerFarbe: MARKER_FARBEN[0], sticker: 'idee', strich: null, pfeil: null,
      radiert: new Set(), radiertP: new Set(), radiertS: new Set(), zug: null, gewaehlt: null, rueck: [], vor: [],
      fest: {} };   // fest: einmal vergebene Plaetze, damit nichts nachrutscht
    const anwesendText = el('span', { class: 'leise' });
    const rahmen = el('div', { class: 'tafel-rahmen' });
    const auswahl = el('div', { class: 'pi-menue', hidden: true });

    // Werkzeugleiste unten: nur Symbole, das aktive blau gefuellt. Stift, Textmarker und Sticker klappen beim Waehlen
    // ihre Auswahl auf (ein zweiter Tipp schliesst sie), beim Zeichnen geht sie zu. Tastenkuerzel im Hinweis.
    const ZEICHNEN = ['stift', 'marker', 'pfeil', 'radierer', 'rahmen'];
    const knopf = (w, titel, taste) => el('button', { type: 'button', class: 'wz', 'data-w': w, title: titel + ' · ' + taste, 'aria-label': titel,
      onclick: () => werkzeugWaehlen(w, true) }, T.symbol(w));
    const auf = {
      stift: el('div', { class: 'wz-auf', hidden: true },
        el('div', { class: 'reihe' }, FARBEN.map(f => el('button', { type: 'button', class: 'farbe', style: 'background:' + f, 'data-f': f,
          'aria-label': 'Stiftfarbe', onclick: () => { S.farbe = f; leisteZeigen(); } }))),
        el('div', { class: 'reihe' }, [3, 6, 12].map(n => el('button', { type: 'button', class: 'dicke', 'data-d': String(n),
          'aria-label': 'Strichstärke ' + n, onclick: () => { S.dicke = n; leisteZeigen(); } }, el('span', { style: 'width:' + (n + 3) + 'px;height:' + (n + 3) + 'px' }))))),
      marker: el('div', { class: 'wz-auf', hidden: true },
        el('div', { class: 'reihe' }, MARKER_FARBEN.map(f => el('button', { type: 'button', class: 'farbe', style: 'background:' + f, 'data-m': f,
          'aria-label': 'Textmarkerfarbe', onclick: () => { S.markerFarbe = f; leisteZeigen(); } })))),
      sticker: el('div', { class: 'wz-auf', hidden: true },
        el('div', { class: 'etikett', text: 'Sticker wählen, dann auf die Tafel oder ein Post-it tippen' }),
        el('div', { class: 'st-raster' }, STICKER.map(([k, name, farbe]) => el('button', { type: 'button', 'data-s': k, title: name, 'aria-label': name,
          style: 'color:' + farbe, onclick: () => { S.sticker = k; aufZu(); leisteZeigen(); } }, T.symbol('st_' + k))))),
    };
    const gruppe = (w, titel, taste) => el('span', { class: 'wz-gruppe' }, knopf(w, titel, taste), auf[w]);
    const leiste = el('div', { class: 'tafel-werkzeuge' },
      knopf('zeiger', 'Auswählen und verschieben', 'V'), gruppe('stift', 'Stift', 'P'), gruppe('marker', 'Textmarker', 'M'),
      knopf('pfeil', 'Pfeil: von Post-it zu Post-it ziehen, er haftet an beiden', 'A'), knopf('radierer', 'Radierer', 'E'),
      el('span', { class: 'trenner' }),
      knopf('postit', 'Post-it: auf die Tafel tippen', 'N'), knopf('rahmen', 'Rahmen: Rechteck um eine Skizze ziehen', 'F'),
      gruppe('sticker', 'Sticker', 'S'),
      el('span', { class: 'trenner' }),
      el('button', { type: 'button', class: 'wz', title: 'Rückgängig · Strg+Z', 'aria-label': 'Rückgängig', onclick: rueckgaengig }, T.symbol('zurueck')),
      el('button', { type: 'button', class: 'wz', title: 'Wiederholen · Strg+Y', 'aria-label': 'Wiederholen', onclick: wiederholen }, T.symbol('vor')));
    function aufZu() { Object.values(auf).forEach(a => { a.hidden = true; }); }
    function werkzeugWaehlen(w, klick) {
      const vorher = S.werkzeug;
      S.werkzeug = w;
      const a = auf[w];
      const offen = a && !a.hidden;
      aufZu();
      if (a && klick) a.hidden = vorher === w && offen;
      leisteZeigen();
    }
    function leisteZeigen() {
      leiste.querySelectorAll('.wz[data-w]').forEach(b => b.classList.toggle('an', b.dataset.w === S.werkzeug));
      leiste.querySelectorAll('[data-f]').forEach(b => b.classList.toggle('an', b.dataset.f === S.farbe));
      leiste.querySelectorAll('[data-m]').forEach(b => b.classList.toggle('an', b.dataset.m === S.markerFarbe));
      leiste.querySelectorAll('.dicke').forEach(b => b.classList.toggle('an', Number(b.dataset.d) === S.dicke));
      leiste.querySelectorAll('[data-s]').forEach(b => b.classList.toggle('an', b.dataset.s === S.sticker));
      t.canvas.style.pointerEvents = ZEICHNEN.includes(S.werkzeug) ? 'auto' : 'none';
      t.flaeche.dataset.werkzeug = S.werkzeug;
      menueZu();
    }

    T.setzen(ort,
      el('div', { class: 'tafel-leiste' },
        el('b', { text: D.projekt.titel }),
        el('span', { class: 'leise', text: D.termin ? T.kurzTag(D.termin.datum) + ' · ' + D.termin.uhrzeit : T.kwText(D.woche) }),
        anwesendText,
        el('span', { class: 'rechts' },
          el('button', { type: 'button', onclick: rasterZeigen }, 'Raster'),
          el('button', { type: 'button', onclick: () => document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen().catch(() => {}) }, 'Vollbild'),
          el('button', { type: 'button', class: 'haupt', onclick: abschliessen }, 'Abschließen'))),
      rahmen, leiste);
    const t = aufbauen(rahmen);
    t.flaeche.appendChild(auswahl);

    async function senden(daten) {
      try {
        const r = await T.api('POST', basis + '/tafel', Object.assign({ woche: D.woche }, daten));
        D = r.tafel;
        zeichnen();
        return r.ergebnis || {};
      } catch (e) { T.meldung(e.message, true); laden(); return null; }
    }

    async function laden() {
      if (S.zug || S.strich || S.rZug || S.stZug || S.kasten || S.pfeil) return;
      try {
        const r = await T.api('GET', basis + '/tafel?stand=' + encodeURIComponent(D.stand));
        if (r.unveraendert) { anwesendZeigen(r.anwesend); return; }
        D = r.tafel;
        zeichnen();
      } catch (e) { /* naechster Versuch */ }
    }

    function anwesendZeigen(a) {
      anwesendText.textContent = a.geraete ? (a.geraete === 1 ? '1 Gerät des Teams verbunden' : a.geraete + ' Geräte des Teams verbunden') : 'kein Gerät des Teams verbunden';
    }

    const ende = pfeilEnde(t.zettel);
    const malen = () => zeichneStriche(t.ctx, D.striche, D.objekte.pfeile, ende, S.pfeil);

    function zeichnen() {
      if (D.abgeschlossen) return;
      const pos = anordnen(D.postits, Object.assign({}, S.fest, D.positionen), rahmenKeys(D.objekte));
      S.fest = pos;
      S.pos = pos;
      T.setzen(t.zettel, D.objekte.rahmen.map(r => rahmenElement(r, true)), D.postits.map(z => zettelElement(z, pos[z.key], basis)));
      stickerSetzen(t.zettel, D.objekte.sticker);
      malen();
      anwesendZeigen(D.anwesend);
    }

    // --- Rahmen ---
    const drinIn = (r, x, y) => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h;
    const rahmenBei = (x, y) => D.objekte.rahmen.filter(r => drinIn(r, x, y)).sort((a, b) => a.w * a.h - b.w * b.h)[0];
    const piMitte = pi => [pi.offsetLeft + pi.offsetWidth / 2, pi.offsetTop + pi.offsetHeight / 2];
    const groesse = z => { const pi = t.zettel.querySelector('.pi[data-key="' + CSS.escape(z.key) + '"]');
      return pi ? [pi.offsetWidth, pi.offsetHeight] : [breite(z), PH]; };

    // Was ganz in einem Rechteck liegt: Striche, freie Sticker und Post-its (mit ihrer Mitte)
    function inhaltVon(r) {
      return {
        striche: D.striche.filter(s => s.id > 0 && s.punkte.every(p => drinIn(r, p[0], p[1]))).map(s => s.id),
        sticker: D.objekte.sticker.filter(s => !s.key && drinIn(r, s.x + SG / 2, s.y + SG / 2)).map(s => s.id),
        postits: [...t.zettel.querySelectorAll('.pi')].filter(pi => drinIn(r, ...piMitte(pi))).map(pi => pi.dataset.key),
      };
    }

    async function titelFragen(alt) {
      const f = el('input', { required: true, maxlength: '80', value: alt || '', placeholder: 'z. B. Gehäuse Variante B' });
      return T.dialog({ titel: alt ? 'Titel des Rahmens' : 'Neuer Rahmen', knopf: 'Übernehmen',
        inhalt: el('div', { class: 'felder' }, T.feld('Titel', f)), speichern: () => f.value });
    }

    async function rahmenNeu(x, y, w, h) {
      const titel = await titelFragen('');
      if (titel === null) { malen(); return; }
      const r = { x, y, w, h };
      const r2 = await senden(Object.assign({ aktion: 'rahmen', titel }, r, inhaltVon(r)));
      if (r2 && r2.rahmen_id) merken({ typ: 'rahmen', id: r2.rahmen_id });
      werkzeugWaehlen('zeiger');
    }

    // Rahmen als Bild (fuer den Eintrag oder zum Herunterladen): nur dieser Ausschnitt, ohne Zonen
    const rahmenBild = (r, typ) => bildErzeugen(D, S.pos, groesse, { ausschnitt: [r.x - 12, r.y - 14, r.w + 24, r.h + 26], faktor: 2, zonen: false, typ });

    async function alsErgebnis(r, zone) {
      if (!zone) {
        const wahl = el('select', {}, [['absprachen', 'Absprache'], ['auftraege', 'Auftrag'], ['meilensteine', 'Meilenstein']]
          .map(([k, t2]) => el('option', { value: k, text: t2 })));
        zone = await T.dialog({ titel: r.titel + ' · als Ergebnis', knopf: 'Weiter', inhalt: el('div', { class: 'felder' }, T.feld('Wird zu', wahl)),
          speichern: () => wahl.value });
        if (!zone) return;
      }
      const mehr = await ergebnisAngaben(zone, { text: r.titel });
      if (mehr === null) { zeichnen(); return; }
      const bild = rahmenBild(r, 'image/jpeg').split(',')[1];   // JPEG: kommt so auch ins PDF
      const e = await senden(Object.assign({ aktion: 'rahmen_ergebnis', id: r.id, zone, bild }, mehr));
      if (e && e.key) T.meldung('„' + r.titel + '“ ist jetzt ' + { absprachen: 'eine Absprache', auftraege: 'ein Auftrag', meilensteine: 'ein Meilenstein' }[zone] + ', die Skizze hängt als Bild daran.');
    }

    function rahmenMenue(r, re) {
      T.setzen(auswahl,
        el('button', { type: 'button', onclick: async () => { menueZu(); const t2 = await titelFragen(r.titel); if (t2 !== null) senden({ aktion: 'rahmen_aendern', id: r.id, titel: t2 }); } }, 'Titel ändern'),
        r.ergebnis ? null : el('button', { type: 'button', onclick: () => { menueZu(); alsErgebnis(r); } }, 'Als Auftrag …'),
        el('button', { type: 'button', onclick: () => { menueZu(); herunterladen(rahmenBild(r, 'image/png'), 'Rahmen – ' + r.titel.replace(/[\\/:*?"<>|]/g, '') + '.png'); } }, 'Als Bild'),
        el('button', { type: 'button', class: 'warnen', onclick: () => { menueZu(); senden({ aktion: 'rahmen_weg', id: r.id }); } }, 'Rahmen lösen'));
      auswahl.style.left = Math.min(re.offsetLeft, B - 420) + 'px';
      auswahl.style.top = Math.min(re.offsetTop + re.offsetHeight + 6, H - 50) + 'px';
      auswahl.hidden = false;
    }

    // Wo ein Pfeil anfaengt oder endet: auf einem Post-it haftet er (Lage relativ zum Post-it), sonst frei
    function anker(ev, x, y) {
      const unter = document.elementsFromPoint(ev.clientX, ev.clientY);
      const pi = unter.map(n => n.closest && n.closest('.pi')).find(Boolean);
      const rel = e => ({ rx: Math.round((x - e.offsetLeft) / e.offsetWidth * 1000) / 1000, ry: Math.round((y - e.offsetTop) / e.offsetHeight * 1000) / 1000 });
      if (pi && t.zettel.contains(pi)) return Object.assign({ key: pi.dataset.key }, rel(pi));
      const re = unter.map(n => n.closest && n.closest('.t-rahmen')).find(Boolean);
      if (re && t.zettel.contains(re)) return Object.assign({ rahmen: Number(re.dataset.id) }, rel(re));
      return { x, y };
    }

    // Rueckgaengig/Wiederholen: rueck haelt, wie man etwas zuruecknimmt, vor, wie man es wieder herstellt
    function merken(eintrag) { S.rueck.push(eintrag); S.vor = []; }

    // --- Stift, Textmarker, Pfeil, Radierer (auf der Zeichenflaeche) ---
    t.canvas.addEventListener('pointerdown', ev => {
      ev.preventDefault();
      t.canvas.setPointerCapture(ev.pointerId);
      aufZu();
      const [x, y] = t.punkt(ev);
      if (S.werkzeug === 'stift') {
        S.strich = { farbe: S.farbe, breite: S.dicke, punkte: [[x, y, ev.pointerType === 'pen' ? ev.pressure : .5]] };
      } else if (S.werkzeug === 'marker') {
        S.strich = { farbe: S.markerFarbe, breite: 22, marker: true, punkte: [[x, y, .5]] };
      } else if (S.werkzeug === 'rahmen') {
        const kasten = el('div', { class: 'auswahl-kasten', style: 'left:' + x + 'px;top:' + y + 'px;width:0;height:0' });
        t.zettel.appendChild(kasten);
        S.kasten = { x0: x, y0: y, x, y, kasten };
      } else if (S.werkzeug === 'pfeil') {
        S.pfeil = { farbe: FARBEN[1], a: anker(ev, x, y), b: { x, y } };
      } else if (S.werkzeug === 'radierer') {
        S.radierer = true;
        radieren(x, y);
      }
    });
    t.canvas.addEventListener('pointermove', ev => {
      const [x, y] = t.punkt(ev);
      if (S.strich) {
        const p = S.strich.punkte, letzter = p[p.length - 1];
        if (Math.abs(letzter[0] - x) + Math.abs(letzter[1] - y) < 2) return;
        p.push([x, y, ev.pointerType === 'pen' ? ev.pressure : .5]);
        if (S.strich.marker) { D.striche.push(S.strich); malen(); D.striche.pop(); }   // halbdurchsichtig: ganz neu zeichnen
        else zeichneStrich(t.ctx, { farbe: S.strich.farbe, breite: S.strich.breite, punkte: p.slice(-2) });
      } else if (S.pfeil) { S.pfeil.b = { x, y }; malen(); }
      else if (S.kasten) {
        const k = S.kasten;
        Object.assign(k, { x, y });
        Object.assign(k.kasten.style, { left: Math.min(x, k.x0) + 'px', top: Math.min(y, k.y0) + 'px',
          width: Math.abs(x - k.x0) + 'px', height: Math.abs(y - k.y0) + 'px' });
      } else if (S.radierer) radieren(x, y);
    });
    const strichEnde = async ev => {
      if (S.strich) {
        const strich = S.strich;
        S.strich = null;
        D.striche.push(Object.assign({ id: -1 }, strich));
        const imRahmen = rahmenBei(strich.punkte[0][0], strich.punkte[0][1]);   // im Rahmen begonnen: gehoert dazu
        const daten = { aktion: 'strich', farbe: strich.farbe, breite: strich.breite, marker: !!strich.marker, punkte: strich.punkte,
          rahmen: imRahmen ? imRahmen.id : null };
        const r = await senden(daten);
        if (r && r.strich_id) merken({ typ: 'strich', id: r.strich_id, daten });
      } else if (S.pfeil) {
        const p = S.pfeil;
        S.pfeil = null;
        const [x, y] = t.punkt(ev);
        p.b = anker(ev, x, y);
        const a = ende(p.a), b = ende(p.b);
        if (!a || !b || Math.hypot(a[0] - b[0], a[1] - b[1]) < 25 || (p.a.key && p.a.key === p.b.key)) { malen(); return; }
        const daten = { aktion: 'pfeil', farbe: p.farbe, a: p.a, b: p.b };
        D.objekte.pfeile.push(Object.assign({ id: -1 }, p));
        const r = await senden(daten);
        if (r && r.pfeil_id) merken({ typ: 'pfeil', id: r.pfeil_id, daten });
      } else if (S.kasten) {
        const k = S.kasten;
        S.kasten = null;
        k.kasten.remove();
        [k.x, k.y] = t.punkt(ev);
        const w = Math.abs(k.x - k.x0), h = Math.abs(k.y - k.y0);
        if (w < 60 || h < 60) { T.meldung('Für einen Rahmen ein größeres Rechteck ziehen.'); return; }
        rahmenNeu(Math.min(k.x, k.x0), Math.min(k.y, k.y0), w, h);
      } else if (S.radierer) {
        S.radierer = false;
        if (S.radiert.size) {
          const ids = [...S.radiert], weg = D._wegStriche || [];
          S.radiert.clear(); D._wegStriche = [];
          await senden({ aktion: 'strich_weg', ids });
          merken({ typ: 'radiert', striche: weg });
        }
        if (S.radiertP.size || S.radiertS.size) {
          const pf = [...S.radiertP], st = [...S.radiertS];
          S.radiertP.clear(); S.radiertS.clear();
          senden({ aktion: 'objekte_weg', pfeile: pf, sticker: st });
        }
      }
    };
    t.canvas.addEventListener('pointerup', strichEnde);
    t.canvas.addEventListener('pointercancel', strichEnde);

    // Radierer: Striche und Pfeile in der Naehe, dazu freie Sticker unter dem Finger
    function radieren(x, y) {
      let anders = false;
      D.striche = D.striche.filter(s => {
        const trifft = s.punkte.some(p => Math.abs(p[0] - x) < 14 + (s.marker ? s.breite / 2 : 0) && Math.abs(p[1] - y) < 14 + (s.marker ? s.breite / 2 : 0));
        if (trifft) { S.radiert.add(s.id); (D._wegStriche = D._wegStriche || []).push(s); anders = true; }
        return !trifft;
      });
      D.objekte.pfeile = D.objekte.pfeile.filter(p => {
        const a = ende(p.a), b = ende(p.b);
        if (!a || !b) return true;
        const trifft = [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1].some(k => Math.hypot(a[0] + (b[0] - a[0]) * k - x, a[1] + (b[1] - a[1]) * k - y) < 16);
        if (trifft) { S.radiertP.add(p.id); anders = true; }
        return !trifft;
      });
      D.objekte.sticker = D.objekte.sticker.filter(s => {
        const trifft = !s.key && x >= s.x - 6 && x <= s.x + SG + 6 && y >= s.y - 6 && y <= s.y + SG + 6;
        if (trifft) { S.radiertS.add(s.id); anders = true; }
        return !trifft;
      });
      if (anders) { stickerSetzen(t.zettel, D.objekte.sticker); malen(); }
    }

    // --- Post-its: ziehen, waehlen, neu ---
    t.zettel.addEventListener('pointerdown', ev => {
      if (S.werkzeug !== 'zeiger') return;
      const re = ev.target.closest('.t-rahmen');
      if (re && !ev.target.closest('.pi, .st')) {   // Rahmen ziehen (Inhalt geht mit) oder am Griff vergroessern
        ev.preventDefault();
        re.setPointerCapture(ev.pointerId);
        const r = D.objekte.rahmen.find(x => x.id === Number(re.dataset.id));
        if (!r) return;
        const [x, y] = t.punkt(ev);
        const pis = (r.postits || []).map(k => t.zettel.querySelector('.pi[data-key="' + CSS.escape(k) + '"]')).filter(Boolean)
          .map(pi => ({ pi, x: pi.offsetLeft, y: pi.offsetTop }));
        const sts = (r.sticker || []).map(id => t.zettel.querySelector('.st[data-sid="' + id + '"]')).filter(s => s && !s.classList.contains('haftet'))
          .map(st => ({ st, x: st.offsetLeft, y: st.offsetTop }));
        const striche = D.striche.filter(s => (r.striche || []).includes(s.id)).map(s => ({ s, punkte: s.punkte.map(p => p.slice()) }));
        S.rZug = { re, r, x0: x, y0: y, start: { x: r.x, y: r.y, w: r.w, h: r.h }, groesse: !!ev.target.closest('.r-griff'), pis, sts, striche, bewegt: false };
        return;
      }
      const st = ev.target.closest('.st');
      if (st && !st.classList.contains('haftet')) {   // freien Sticker ziehen (auf ein Post-it gezogen haftet er dort)
        ev.preventDefault();
        st.setPointerCapture(ev.pointerId);
        const [x, y] = t.punkt(ev);
        S.stZug = { st, id: Number(st.dataset.sid), dx: x - st.offsetLeft, dy: y - st.offsetTop, x0: x, y0: y, bewegt: false };
        return;
      }
      const pi = ev.target.closest('.pi');
      if (!pi) return;
      ev.preventDefault();
      pi.setPointerCapture(ev.pointerId);
      const [x, y] = t.punkt(ev);
      const pos = S.pos[pi.dataset.key];
      S.zug = { pi, key: pi.dataset.key, dx: x - pos[0], dy: y - pos[1], start: pos, bewegt: false, sticker: st };
      pi.classList.add('zieht');
    });
    t.zettel.addEventListener('pointermove', ev => {
      if (S.rZug) {
        const z = S.rZug, [x, y] = t.punkt(ev), a = z.start;
        if (Math.abs(x - z.x0) + Math.abs(y - z.y0) > 4) z.bewegt = true;
        if (!z.bewegt) return;
        if (z.groesse) {
          z.r.w = Math.max(60, Math.min(B - a.x, a.w + x - z.x0));
          z.r.h = Math.max(60, Math.min(H - a.y, a.h + y - z.y0));
        } else {
          const dx = Math.max(-a.x, Math.min(B - a.w - a.x, x - z.x0)), dy = Math.max(-a.y, Math.min(H - a.h - a.y, y - z.y0));
          z.r.x = a.x + dx; z.r.y = a.y + dy; z.dx = dx; z.dy = dy;
          z.pis.forEach(p => { p.pi.style.left = (p.x + dx) + 'px'; p.pi.style.top = (p.y + dy) + 'px'; });
          z.sts.forEach(p => { p.st.style.left = (p.x + dx) + 'px'; p.st.style.top = (p.y + dy) + 'px'; });
          z.striche.forEach(({ s, punkte }) => { s.punkte = punkte.map(p => [p[0] + dx, p[1] + dy].concat(p.slice(2))); });
        }
        Object.assign(z.re.style, { left: z.r.x + 'px', top: z.r.y + 'px', width: z.r.w + 'px', height: z.r.h + 'px' });
        malen();
        return;
      }
      if (S.stZug) {
        const [x, y] = t.punkt(ev), z = S.stZug;
        if (Math.abs(x - z.x0) + Math.abs(y - z.y0) > 4) z.bewegt = true;
        z.st.style.left = Math.max(0, Math.min(B - SG, x - z.dx)) + 'px';
        z.st.style.top = Math.max(0, Math.min(H - SG, y - z.dy)) + 'px';
        return;
      }
      if (!S.zug) return;
      const [x, y] = t.punkt(ev);
      const nx = Math.max(0, Math.min(B - S.zug.pi.offsetWidth, x - S.zug.dx)), ny = Math.max(0, Math.min(H - PH, y - S.zug.dy));
      if (Math.abs(nx - S.zug.start[0]) + Math.abs(ny - S.zug.start[1]) > 4) S.zug.bewegt = true;
      S.zug.pi.style.left = nx + 'px';
      S.zug.pi.style.top = ny + 'px';
      S.zug.ziel = [Math.round(nx), Math.round(ny)];
      malen();   // haftende Pfeile gehen mit
    });
    t.zettel.addEventListener('pointerup', async ev => {
      if (S.rZug) {
        const z = S.rZug;
        S.rZug = null;
        if (!z.bewegt) { rahmenMenue(z.r, z.re); return; }
        if (z.groesse) {   // neue Groesse: Inhalt neu bestimmen
          await senden(Object.assign({ aktion: 'rahmen_aendern', id: z.r.id, w: Math.round(z.r.w), h: Math.round(z.r.h) }, inhaltVon(z.r)));
          return;
        }
        const postits = {};
        z.pis.forEach(p => { postits[p.pi.dataset.key] = [Math.round(p.x + z.dx), Math.round(p.y + z.dy)]; });
        await senden({ aktion: 'rahmen_bewegen', id: z.r.id, dx: Math.round(z.dx || 0), dy: Math.round(z.dy || 0), postits });
        merken({ typ: 'rahmen_bewegen', id: z.r.id, dx: Math.round(z.dx || 0), dy: Math.round(z.dy || 0), postits: Object.fromEntries(
          z.pis.map(p => [p.pi.dataset.key, [p.x, p.y]])), neu: postits });
        const cx = z.r.x + z.r.w / 2, cy = z.r.y + z.r.h / 2;   // in "Ergebnis" gezogen: wird Absprache, Auftrag oder Meilenstein
        if (cx >= GE && !z.r.ergebnis) {
          const r = D.objekte.rahmen.find(x => x.id === z.r.id);
          if (r) alsErgebnis(r, zoneBei(cx, cy));
        }
        return;
      }
      if (S.stZug) {
        const z = S.stZug;
        S.stZug = null;
        if (!z.bewegt) { stickerMenue(z.id, z.st); return; }
        const pi = document.elementsFromPoint(ev.clientX, ev.clientY).map(n => n.closest && n.closest('.pi')).find(Boolean);
        const s = D.objekte.sticker.find(x => x.id === z.id);
        const daten = pi && !D.objekte.sticker.some(x => x.key === pi.dataset.key) ? { key: pi.dataset.key }
          : { x: Math.round(z.st.offsetLeft), y: Math.round(z.st.offsetTop) };
        if (s) { delete s.key; delete s.x; delete s.y; Object.assign(s, daten); }
        senden(Object.assign({ aktion: 'sticker_bewegen', id: z.id }, daten));
        return;
      }
      if (!S.zug) return;
      const z = S.zug;
      S.zug = null;
      z.pi.classList.remove('zieht');
      if (!z.bewegt && z.sticker) { stickerMenue(Number(z.sticker.dataset.sid), z.sticker); return; }
      const zettel = D.postits.find(p => p.key === z.key);
      if (!z.bewegt || !z.ziel) { menueAuf(zettel, z.pi); return; }
      const ziel = zoneBei(z.ziel[0] + z.pi.offsetWidth / 2, z.ziel[1] + PH / 2);
      const vorher = ERGEBNIS.includes(zettel.zone) ? zettel.zone : 'frei';
      const nachher = ERGEBNIS.includes(ziel) ? ziel : 'frei';
      if (vorher === nachher) {
        S.pos[z.key] = z.ziel;
        D.positionen[z.key] = z.ziel;
        merken({ typ: 'position', key: z.key, pos: z.start, neu: z.ziel });
        await senden({ aktion: 'position', key: z.key, x: z.ziel[0], y: z.ziel[1] });
        zuRahmen(z.key, z.ziel[0] + z.pi.offsetWidth / 2, z.ziel[1] + z.pi.offsetHeight / 2);
        return;
      }
      const mehr = await ergebnisAngaben(ziel, zettel);
      if (mehr === null) { zeichnen(); return; }
      senden(Object.assign({ aktion: 'ablegen', key: z.key, zone: ziel, x: z.ziel[0], y: z.ziel[1], text: zettel.text }, mehr));
    });

    t.flaeche.addEventListener('click', async ev => {
      if (S.werkzeug === 'sticker' && !ev.target.closest('.pi-menue, .st')) {   // Sticker setzen
        aufZu();
        const [x, y] = t.punkt(ev);
        const pi = ev.target.closest('.pi');
        const daten = Object.assign({ aktion: 'sticker', art: S.sticker }, pi && !D.objekte.sticker.some(s => s.key === pi.dataset.key)
          ? { key: pi.dataset.key } : { x: Math.max(0, Math.min(B - SG, x - SG / 2)), y: Math.max(0, Math.min(H - SG, y - SG / 2)) });
        const r = await senden(daten);
        if (r && r.sticker_id) merken({ typ: 'sticker', id: r.sticker_id, daten });
        return;
      }
      if (S.werkzeug !== 'postit' || ev.target.closest('.pi, .pi-menue')) return;
      const [x, y] = t.punkt(ev);
      const zone = zoneBei(x, y);
      const text = el('input', { required: true, maxlength: '500', placeholder: zone === 'auftraege' ? 'Was ist zu tun?' : 'Text' });
      let mehr = {};
      const ok = await T.dialog({ titel: 'Neues Post-it · ' + ({ seit: 'Seit letztem Mal', ideen: 'Ideen', absprachen: 'Absprache',
        auftraege: 'Auftrag', meilensteine: 'Meilenstein' })[zone], knopf: 'Aufkleben',
        inhalt: el('div', { class: 'felder' }, T.feld('Text', text)),
        speichern: async () => { mehr = await ergebnisAngaben(zone, { text: text.value }); return mehr !== null; } });
      if (!ok) return;
      const daten = Object.assign({ aktion: 'postit', zone, text: text.value, x: Math.min(x, B - PB), y: Math.min(y, H - PH) }, mehr);
      const r = await senden(daten);
      if (r && r.key) merken({ typ: 'postit', key: r.key, daten });
    });

    // Post-it in einen Rahmen gezogen (oder heraus): Mitgliedschaft nachziehen
    function zuRahmen(key, cx, cy) {
      const neu = rahmenBei(cx, cy), alt = D.objekte.rahmen.find(r => (r.postits || []).includes(key));
      if (neu === alt) return;
      if (neu) senden({ aktion: 'rahmen_aendern', id: neu.id, postits: (neu.postits || []).concat(key) });
      else if (alt) senden({ aktion: 'rahmen_aendern', id: alt.id, postits: alt.postits.filter(k => k !== key) });
    }

    function stickerMenue(id, st) {
      const s = D.objekte.sticker.find(x => x.id === id);
      if (!s) return;
      T.setzen(auswahl, el('span', { class: 'leise', text: (STICKER_INFO[s.art] || {}).name || 'Sticker' }),
        s.key ? el('button', { type: 'button', onclick: () => { menueZu(); senden({ aktion: 'sticker_bewegen', id, x: Math.min(B - SG, (S.pos[s.key] || [0])[0] + 20), y: Math.max(0, (S.pos[s.key] || [0, 60])[1] - 50) }); } }, 'vom Post-it lösen') : null,
        el('button', { type: 'button', class: 'warnen', onclick: () => { menueZu(); senden({ aktion: 'objekte_weg', sticker: [id] }); merken({ typ: 'sticker_weg', s }); } }, 'Entfernen'));
      const ziel = st.closest('.pi') || st;
      auswahl.style.left = Math.min(ziel.offsetLeft, B - 260) + 'px';
      auswahl.style.top = Math.min(ziel.offsetTop + ziel.offsetHeight + 6, H - 50) + 'px';
      auswahl.hidden = false;
    }

    // Angaben, die ein Ergebnis braucht: Auftrag -> Frist (+ wer), Meilenstein -> Woche. null = abgebrochen
    async function ergebnisAngaben(zone, zettel) {
      if (zone !== 'auftraege' && zone !== 'meilensteine') return {};
      const naechste = new Date(); naechste.setDate(naechste.getDate() + 7);
      const f = {
        frist: el('input', { type: 'date', required: true, value: T.isoDatum(naechste) }),
        wer: el('select', {}, el('option', { value: '', text: 'ganzes Team' }), D.mitglieder.map(m => el('option', { value: String(m.id), text: m.name }))),
        woche: el('input', { type: 'date', required: true, value: T.isoDatum(naechste) }),
      };
      return T.dialog({
        titel: (zone === 'auftraege' ? 'Auftrag: ' : 'Meilenstein: ') + zettel.text, knopf: 'Übernehmen',
        inhalt: zone === 'auftraege' ? el('div', { class: 'felder zwei' }, T.feld('Frist', f.frist), T.feld('Verantwortlich', f.wer))
          : el('div', { class: 'felder' }, T.feld('In der Woche vom', f.woche, 'erscheint sofort im Tracking-Sheet')),
        speichern: () => zone === 'auftraege' ? { frist: f.frist.value, verantwortlich_id: f.wer.value ? Number(f.wer.value) : null }
          : { meilenstein_woche: f.woche.value },
      });
    }

    function menueZu() { auswahl.hidden = true; S.gewaehlt = null; }
    function menueAuf(z, pi) {
      if (!z) return;
      const echt = z.key.startsWith('e');
      const knoepfe = [];
      if (z.bild) knoepfe.push(el('button', { type: 'button', onclick: () => bildZeigen(z) }, 'Foto groß'));
      if (echt && ['frage', 'thema', 'auftrag'].includes(z.art)) {
        knoepfe.push(el('button', { type: 'button', onclick: () => { menueZu(); senden({ aktion: 'erledigt', key: z.key, erledigt: !z.erledigt }); } },
          z.erledigt ? 'wieder offen' : z.art === 'auftrag' ? '✓ erledigt' : '✓ geklärt'));
      }
      if (echt && z.art !== 'meilenstein') knoepfe.push(el('button', { type: 'button', class: 'warnen', onclick: () => { menueZu(); senden({ aktion: 'verwerfen', key: z.key }); } }, 'Verwerfen'));
      if (!knoepfe.length) { menueZu(); return; }
      T.setzen(auswahl, knoepfe);
      auswahl.style.left = Math.min(pi.offsetLeft, B - 260) + 'px';
      auswahl.style.top = Math.min(pi.offsetTop + pi.offsetHeight + 6, H - 50) + 'px';
      auswahl.hidden = false;
      S.gewaehlt = z.key;
    }
    document.addEventListener('pointerdown', ev => { if (!auswahl.hidden && !ev.target.closest('.pi-menue, .pi')) menueZu(); });

    function bildZeigen(z) {
      menueZu();
      const huelle = el('div', { class: 'tafel-ansicht bild', onclick: () => huelle.remove() },
        el('img', { src: basis + '/bild/' + z.bild, alt: z.text }), el('div', { class: 'tafel-leiste', text: z.text + ' · antippen zum Schließen' }));
      document.body.appendChild(huelle);
    }

    async function rueckgaengig() {
      const r = S.rueck.pop();
      if (!r) { T.meldung('Nichts mehr rückgängig zu machen.'); return; }
      if (r.typ === 'rahmen') { await senden({ aktion: 'rahmen_weg', id: r.id }); }
      else if (r.typ === 'rahmen_bewegen') {   // zurueck an den alten Platz
        await senden({ aktion: 'rahmen_bewegen', id: r.id, dx: -r.dx, dy: -r.dy, postits: r.postits });
        S.vor.push({ typ: 'rahmen_bewegen', id: r.id, dx: -r.dx, dy: -r.dy, postits: r.neu, neu: r.postits });
      } else if (r.typ === 'sticker_weg') {   // entfernten Sticker wieder aufkleben
        const s = r.s;
        await senden(Object.assign({ aktion: 'sticker', art: s.art }, s.key ? { key: s.key } : { x: s.x, y: s.y }));
      } else if (r.typ === 'strich') { await senden({ aktion: 'strich_weg', ids: [r.id] }); S.vor.push(r); }
      else if (r.typ === 'pfeil') { await senden({ aktion: 'objekte_weg', pfeile: [r.id] }); S.vor.push(r); }
      else if (r.typ === 'sticker') { await senden({ aktion: 'objekte_weg', sticker: [r.id] }); S.vor.push(r); }
      else if (r.typ === 'postit') { await senden({ aktion: 'verwerfen', key: r.key }); S.vor.push(r); }
      else if (r.typ === 'position') {
        await senden({ aktion: 'position', key: r.key, x: r.pos[0], y: r.pos[1] });
        S.vor.push({ typ: 'position', key: r.key, pos: r.neu, neu: r.pos });
      } else if (r.typ === 'radiert') {   // weggeradierte Striche kommen wieder
        const ids = [];
        for (const s of r.striche) {
          const e = await senden({ aktion: 'strich', farbe: s.farbe, breite: s.breite, marker: !!s.marker, punkte: s.punkte });
          if (e && e.strich_id) ids.push(e.strich_id);
        }
        S.vor.push({ typ: 'radiert_wieder', ids, striche: r.striche });
      }
    }

    async function wiederholen() {
      const v = S.vor.pop();
      if (!v) { T.meldung('Nichts zu wiederholen.'); return; }
      const nochmal = async (feld, typ) => { const e = await senden(v.daten); if (e && e[feld]) S.rueck.push({ typ, id: e[feld], daten: v.daten }); };
      if (v.typ === 'strich') await nochmal('strich_id', 'strich');
      else if (v.typ === 'pfeil') await nochmal('pfeil_id', 'pfeil');
      else if (v.typ === 'sticker') await nochmal('sticker_id', 'sticker');
      else if (v.typ === 'rahmen_bewegen') {
        await senden({ aktion: 'rahmen_bewegen', id: v.id, dx: -v.dx, dy: -v.dy, postits: v.postits });
        S.rueck.push({ typ: 'rahmen_bewegen', id: v.id, dx: -v.dx, dy: -v.dy, postits: v.neu, neu: v.postits });
      } else if (v.typ === 'postit') { const e = await senden(v.daten); if (e && e.key) S.rueck.push({ typ: 'postit', key: e.key, daten: v.daten }); }
      else if (v.typ === 'position') {
        await senden({ aktion: 'position', key: v.key, x: v.pos[0], y: v.pos[1] });
        S.rueck.push({ typ: 'position', key: v.key, pos: v.neu, neu: v.pos });
      } else if (v.typ === 'radiert_wieder') {
        await senden({ aktion: 'strich_weg', ids: v.ids });
        S.rueck.push({ typ: 'radiert', striche: v.striche });
      }
    }

    // Tastenkuerzel (nicht beim Schreiben in Feldern)
    document.addEventListener('keydown', ev => {
      if (ev.target.closest && ev.target.closest('input, textarea, select, [contenteditable="true"], dialog')) return;
      const k = ev.key.toLowerCase();
      if ((ev.ctrlKey || ev.metaKey) && k === 'z') { ev.preventDefault(); if (ev.shiftKey) wiederholen(); else rueckgaengig(); return; }
      if ((ev.ctrlKey || ev.metaKey) && k === 'y') { ev.preventDefault(); wiederholen(); return; }
      if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
      const w = { v: 'zeiger', p: 'stift', m: 'marker', a: 'pfeil', e: 'radierer', n: 'postit', f: 'rahmen', s: 'sticker' }[k];
      if (w) { ev.preventDefault(); werkzeugWaehlen(w); }
      if (k === 'escape') { aufZu(); menueZu(); }
    });

    async function rasterZeigen() {
      const ort2 = el('div', { class: 'tafel-raster' });
      const huelle = el('div', { class: 'tafel-ansicht' },
        el('div', { class: 'tafel-leiste' }, el('b', { text: 'Tracking-Sheet · ' + D.projekt.titel }),
          el('button', { type: 'button', class: 'rechts-btn', onclick: () => huelle.remove() }, 'Schließen')), ort2);
      document.body.appendChild(huelle);
      Raster.erzeugen({ ort: ort2, basis, rolle: 'lehrkraft' }).laden();
    }

    async function abschliessen() {
      const n = D.postits.filter(z => ERGEBNIS.includes(z.zone)).length;
      const ok = await T.dialog({ titel: 'Besprechung abschließen?', knopf: 'Abschließen',
        inhalt: el('p', { text: 'Die Tafel wird mit ' + n + (n === 1 ? ' Ergebnis' : ' Ergebnissen') + ' eingefroren und steht im Protokoll. Offene Aufträge, Fragen, Ideen und Rahmen wandern zur nächsten Tafel. Danach gibt es sie als PDF und als Bild.' }),
        speichern: () => {
          let bild = null;   // Bild der Tafel fuer das PDF (JPEG, 3200 x 1800)
          try { bild = bildErzeugen(D, S.pos, groesse, { typ: 'image/jpeg', zonen: true, faktor: 2 }).split(',')[1]; } catch (e) { bild = null; }
          return T.api('POST', basis + '/besprechung', { aktion: 'abschliessen', woche: D.woche, bild });
        } });
      if (!ok) return;
      D.abgeschlossen = true;
      T.setzen(ort, el('div', { class: 'tafel-fertig' }, el('h1', { class: 'dreieck', text: 'Besprechung abgeschlossen' }),
        el('p', { text: 'Die Tafel steht im Protokoll. Dieses Fenster kann geschlossen werden.' }),
        el('button', { type: 'button', onclick: () => window.close() }, 'Fenster schließen')));
    }

    leisteZeigen();
    zeichnen();
    const timer = setInterval(() => {
      if (D.abgeschlossen) { clearInterval(timer); return; }
      if (!document.querySelector('dialog[open]')) laden();
    }, 1500);
  }

  // Auf der Lehrer-Seite: Tafel in einem eigenen Fenster auf dem zweiten Bildschirm (Board) oeffnen
  async function aufsBoard(pid) {
    const url = '/tafel?projekt=' + pid;
    let lage = 'popup,width=1280,height=720';
    try {
      if ('getScreenDetails' in window) {   // Chrome/Edge: fragt einmal nach der Erlaubnis "Fenster verwalten"
        const d = await window.getScreenDetails();
        const board = d.screens.find(s => s !== d.currentScreen);
        if (board) lage = 'popup,left=' + board.availLeft + ',top=' + board.availTop + ',width=' + board.availWidth + ',height=' + board.availHeight;
      }
    } catch (e) { /* ohne Erlaubnis: normales Fenster */ }
    const fenster = window.open(url, 'tafel-' + pid, lage);
    if (!fenster) T.meldung('Der Browser hat das Fenster blockiert. Bitte Pop-ups für diese Seite erlauben.', true);
    else T.meldung('Tafel geöffnet. Auf dem Board „Vollbild“ antippen.');
  }

  // Eingefrorene Tafel fest in eine Seite setzen (Projektbericht); der Rahmen braucht eine feste Groesse
  function einbetten(rahmen, d, bildBasis) {
    eingefrorenZeichnen(aufbauen(rahmen), d, bildBasis);
  }

  // --- Nach der Besprechung: Tafel als Bild (PNG, im Browser gemalt) und PDF (im Container gebaut) ---
  async function eingefrorenesBild(url, typ) {
    const d = (await T.api('GET', url)).tafel;
    const pos = anordnen(d.postits, d.positionen || {}, rahmenKeys(d.objekte));
    return bildErzeugen(d, pos, z => [breite(z), PH], { typ, zonen: true, faktor: 2 });
  }

  // p: Protokoll (id, woche, tafel_bild), basis: /api/projekte/<id> oder /api/t/<link>, titel: Projekt
  async function alsPng(basis, p, titel) {
    try { herunterladen(await eingefrorenesBild(basis + '/tafel/' + p.id, 'image/png'), 'Tafel ' + T.kwText(p.woche) + ' – ' + titel + '.png'); }
    catch (e) { T.meldung(e.message, true); }
  }

  async function alsPdf(basis, p) {
    try {
      if (!p.tafel_bild && p.tafel) {   // Besprechungen von vor 0.10.6: Bild der Tafel einmal nachtragen
        const bild = (await eingefrorenesBild(basis + '/tafel/' + p.id, 'image/jpeg')).split(',')[1];
        p.tafel_bild = (await T.api('POST', basis + '/besprechung/' + p.id + '/tafelbild', { bild })).tafel_bild;
      }
      location.href = basis + '/besprechung/' + p.id + '/pdf';
    } catch (e) { T.meldung(e.message, true); }
  }

  function downloadKnoepfe(basis, p, titel) {
    return el('div', { class: 'zeile download-knoepfe' },
      el('button', { type: 'button', class: 'haupt', onclick: () => alsPdf(basis, p) }, T.symbol('laden'), 'PDF herunterladen'),
      p.tafel ? el('button', { type: 'button', onclick: () => alsPng(basis, p, titel) }, T.symbol('bild'), 'Tafel als Bild (PNG)') : null);
  }

  return { starten, ansehen, aufsBoard, einbetten, alsPng, alsPdf, downloadKnoepfe };
})();
