"""WireGuard (Stufe G): Angaben fuer "trackingdrs vpn einrichten" pruefen und den Sperrtest ausfuehren.

Aufruf aus deploy/vpn.sh (als root, im Repo-Ordner):
  python3 -m app.vpn pruefen <server:port> <schluessel> <adresse> "<netze>" [<server-ip>]
    Ausgabe: adresse|netze|server-ip (bereinigt), sonst eine Fehlermeldung und Exit 1.
  python3 -m app.vpn sperrtest [--leise]
    Versucht ueber das VPN den Server, das Heimnetz und andere Teilnehmer zu erreichen (Ping und einige TCP-Ports).
    Mit der Sperre auf dem Server (vps/sperre.sh) muss alles scheitern. Ergebnis nach <VPN_DIR>/sperrtest.json,
    das der Lehrerbereich anzeigt (rote Warnung, wenn etwas durchkommt). Exit 0 dicht/aus, 2 offen, 1 sonst.
  python3 -m app.vpn anfrage-lesen <datei>
    Auftrag aus dem Lehrerbereich lesen, loeschen, pruefen. Ausgabe: aktion|server|schluessel|adresse|netze|server-ip|
    server-if (bei sperrtest/aus nur die Aktion).
  python3 -m app.vpn conf-lesen <client-datei>
    Wie anfrage-lesen, aber aus einer WireGuard-Datei fuer den Container (trackingdrs vpn einrichten --conf). Legt den
    privaten Schluessel (und PresharedKey) aus der Datei nach /etc/wireguard. Ausgabe wie oben, dazu |psk|aus_datei.
  python3 -m app.vpn info-ablegen <oeffentlicher schluessel des containers> <aktiv 0|1> [<schnittstelle auf dem server>]
                                  [<aus datei 0|1>]
    Oeffentliche Angaben fuer den Lehrerbereich nach <VPN_DIR>/einrichtung.json.
"""
import base64
import concurrent.futures
import datetime
import ipaddress
import itertools
import json
import os
import re
import socket
import stat
import subprocess
import sys

from . import db

KONF = "/etc/wireguard/wg0.conf"
SCHLUESSEL = "/etc/wireguard/trackingdrs.key"   # privater Schluessel des Containers (nur root)
PSK = "/etc/wireguard/trackingdrs.psk"          # PresharedKey, nur wenn die Client-Datei einen hat
VPN_DIR = os.environ.get("TRACKINGDRS_VPN_DIR", "/var/lib/trackingdrs-vpn")
PORTS = (22, 53, 80, 443, 8080)
HANDSHAKE_MAX = 300   # Sekunden; mit Keepalive 25 erneuert WireGuard den Handshake alle 2 Minuten


class VpnFehler(Exception):
    pass


def eigene_netze():
    """Netze der anderen Schnittstellen (eth0 im Schulnetz): das VPN darf sie nicht ueberdecken."""
    aus = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"], capture_output=True, text=True).stdout
    netze = []
    for zeile in aus.splitlines():
        teile = zeile.split()
        if len(teile) >= 4 and teile[2] == "inet" and teile[1] != "wg0":
            netze.append((teile[1], ipaddress.ip_interface(teile[3]).network))
    return netze


def pruefen(server, schluessel, adresse, netze, server_ip="", lokal=()):
    """Gibt (adresse, [netze], server_ip) zurueck oder wirft VpnFehler mit einem Hinweis, wo die Angabe steht."""
    server = (server or "").strip()
    m = re.fullmatch(r"([A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\]):(\d{1,5})", server)
    if not m or not 0 < int(m.group(2)) < 65536:
        raise VpnFehler("Server bitte als Adresse:Port, z. B. vpn.example.de:51820 (Port = ListenPort der Server-Config).")
    try:
        roh = base64.b64decode((schluessel or "").strip(), validate=True)
    except ValueError:
        roh = b""
    if len(roh) != 32:
        raise VpnFehler("Der öffentliche Schlüssel des Servers hat 44 Zeichen und endet auf „=“. "
                        "Auf dem Server: wg show wg0 public-key (nicht den PrivateKey aus der Config nehmen).")
    try:
        a = ipaddress.IPv4Address((adresse or "").strip().split("/")[0])
    except ValueError:
        raise VpnFehler("Die VPN-Adresse des Containers bitte als IPv4-Adresse, z. B. 10.8.0.20.") from None
    liste = []
    for n in (netze or "").replace(",", " ").split():
        try:
            liste.append(ipaddress.IPv4Network(n, strict=False))
        except ValueError:
            raise VpnFehler("Netz ungültig: %s (z. B. 10.8.0.0/24)" % n) from None
    if not liste:
        liste = [ipaddress.IPv4Network("%s/24" % a, strict=False)]
    if any(n.prefixlen < 8 for n in liste):
        raise VpnFehler("Nur das VPN-Netz (und ggf. das Heimnetz) soll über den Tunnel laufen, nicht alles (0.0.0.0/0).")
    if not any(a in n for n in liste):
        raise VpnFehler("Die VPN-Adresse %s liegt in keinem der Netze %s." % (a, " ".join(map(str, liste))))
    for name, netz in lokal:
        for n in liste:
            if n.overlaps(netz):
                raise VpnFehler("%s überschneidet sich mit dem Netz von %s (%s): dann wäre der Container dort nicht mehr "
                                "erreichbar." % (n, name, netz))
    try:
        s = ipaddress.IPv4Address(server_ip.strip()) if server_ip and server_ip.strip() else next(liste[0].hosts())
    except ValueError:
        raise VpnFehler("Die VPN-Adresse des Servers bitte als IPv4-Adresse, z. B. 10.8.0.1.") from None
    if s == a:
        raise VpnFehler("Container und Server können nicht dieselbe VPN-Adresse haben.")
    return str(a), [str(n) for n in liste], str(s)


def konf_lesen(text):
    """Aus wg0.conf: eigene Adresse, Netze ueber den Tunnel (AllowedIPs) und die Server-IP (Kommentar von vpn.sh)."""
    werte = {}
    for zeile in text.splitlines():
        m = re.match(r"\s*(#\s*Server-IP|Address|AllowedIPs)\s*=\s*(.+?)\s*$", zeile)
        if m:
            werte.setdefault(m.group(1).lstrip("# ").strip(), m.group(2))
    adresse = ipaddress.IPv4Address(werte["Address"].split("/")[0])
    netze = [ipaddress.IPv4Network(n, strict=False) for n in werte.get("AllowedIPs", "").replace(",", " ").split()]
    server = werte.get("Server-IP")
    return adresse, netze, ipaddress.IPv4Address(server) if server else None


def sperrziele(adresse, netze, server_ip):
    """Server, dazu je Netz die ersten beiden Adressen (Fritzbox, Router, weitere Teilnehmer), ohne den Container."""
    ziele = [server_ip] if server_ip else []
    for n in netze:
        ziele.extend(itertools.islice(n.hosts(), 2))
    gesehen = set()
    return [str(z) for z in ziele if z != adresse and not (z in gesehen or gesehen.add(z))]


def _tcp(ziel, port):
    """Durchgekommen, wenn die Gegenseite antwortet, auch mit "Verbindung abgelehnt" (RST)."""
    try:
        socket.create_connection((ziel, port), timeout=1.5).close()
        return True
    except ConnectionRefusedError:
        return True
    except OSError:
        return False


def _ping(ziel):
    return subprocess.run(["ping", "-c", "1", "-W", "1", ziel], capture_output=True).returncode == 0


def proben(ziele, tcp=_tcp, ping=_ping):
    """[(ziel, "Ping" | "TCP <port>", durch)] in der Reihenfolge der Ziele, parallel ausgefuehrt."""
    auftraege = [(z, "Ping", lambda z=z: ping(z)) for z in ziele]
    auftraege += [(z, "TCP %d" % p, lambda z=z, p=p: tcp(z, p)) for z in ziele for p in PORTS]
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        ergebnisse = list(pool.map(lambda a: a[2](), auftraege))
    zeilen = [(z, art, durch) for (z, art, _), durch in zip(auftraege, ergebnisse)]
    return sorted(zeilen, key=lambda t: ziele.index(t[0]))


def _handshake_alter():
    r = subprocess.run(["wg", "show", "wg0", "latest-handshakes"], capture_output=True, text=True)
    if r.returncode != 0:
        return None, False
    zeiten = [int(t.split()[1]) for t in r.stdout.splitlines() if len(t.split()) == 2 and t.split()[1].isdigit()]
    letzte = max(zeiten, default=0)
    return (int(datetime.datetime.now().timestamp()) - letzte if letzte else None), True


def sperrtest(text, handshake=_handshake_alter, pruefe=proben):
    """Ergebnis: dicht (nichts erreicht) | offen (etwas erreicht) | keine_verbindung | aus (wg0 nicht aktiv)."""
    adresse, netze, server_ip = konf_lesen(text)
    ziele = sperrziele(adresse, netze, server_ip)
    erg = {"zeit": db.jetzt(), "adresse": str(adresse), "ziele": ziele, "proben": [], "durch": []}
    alter, aktiv = handshake()
    if not aktiv:
        return dict(erg, ergebnis="aus")
    if alter is None or alter > HANDSHAKE_MAX:
        return dict(erg, ergebnis="keine_verbindung")
    erg["proben"] = [{"ziel": z, "art": art, "durch": durch} for z, art, durch in pruefe(ziele)]
    erg["durch"] = ["%s %s" % (p["ziel"], p["art"]) for p in erg["proben"] if p["durch"]]
    return dict(erg, ergebnis="offen" if erg["durch"] else "dicht")


def _schreiben(name, daten, ordner=None):
    ordner = ordner or VPN_DIR
    os.makedirs(ordner, mode=0o755, exist_ok=True)
    pfad = os.path.join(ordner, name)
    with open(pfad + ".neu", "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=1)
    os.chmod(pfad + ".neu", 0o644)
    os.replace(pfad + ".neu", pfad)


def _lesen(name):
    try:
        with open(os.path.join(VPN_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def ablegen(erg, ordner=None):
    _schreiben("sperrtest.json", erg, ordner)


def stand():
    return _lesen("sperrtest.json")


def kurz():
    """Fuer /api/ich (Admins): letzter Sperrtest, None ohne VPN. alt = seit 3 Tagen kein Test mehr."""
    s = stand()
    if not s or not s.get("zeit"):
        return None
    try:
        alt = datetime.datetime.fromisoformat(db.jetzt()) - datetime.datetime.fromisoformat(s["zeit"]) > datetime.timedelta(days=3)
    except ValueError:
        alt = True
    return {"ergebnis": s.get("ergebnis"), "zeit": s["zeit"], "durch": s.get("durch") or [], "ziele": s.get("ziele") or [],
            "adresse": s.get("adresse"), "alt": alt}


# --- Einrichten aus dem Lehrerbereich ---
# Der Webdienst darf nichts einrichten (eigener Benutzer). Er prueft die Angaben und legt <daten>/vpn/anfrage.json ab;
# trackingdrs-vpn-anfrage.path startet daraufhin als root "trackingdrs-vpn anfrage". Das liest die Datei (ohne einem
# Symlink zu folgen), loescht sie, prueft die Angaben noch einmal und fuehrt den Auftrag aus. Ergebnisse in VPN_DIR:
# lauf.json, protokoll.txt und einrichtung.json (nur Oeffentliches: Adressen, oeffentliche Schluessel, wg0.conf ohne
# Schluessel). Den privaten Schluessel des Containers sieht die Seite nie, einen privaten Schluessel nimmt sie nie an.

EINHEIT = os.environ.get("TRACKINGDRS_VPN_EINHEIT", "/etc/systemd/system/trackingdrs-vpn-anfrage.path")
AKTIONEN = ("einrichten", "sperrtest", "aus")
SCHNITTSTELLE = re.compile(r"[A-Za-z0-9_.=-]{1,15}")
LAUF_MAX = datetime.timedelta(minutes=10)   # haengt ein Auftrag laenger, darf ein neuer kommen


def _anfrage_pfad(daten_dir):
    return os.path.join(daten_dir, "vpn", "anfrage.json")


def server_text(host, port):
    """Adresse und Port aus dem Formular -> host:port ([v6]:port)."""
    host = str(host or "").strip()
    if ":" in host and not host.startswith("["):
        host = "[%s]" % host
    return "%s:%s" % (host, str(port or "").strip() or "51820")


def _schluessel(text, wofuer):
    text = (text or "").strip()
    try:
        if len(base64.b64decode(text, validate=True)) == 32:
            return text
    except ValueError:
        pass
    raise VpnFehler("%s ist kein WireGuard-Schlüssel (44 Zeichen, endet auf „=“)." % wofuer)


def conf_einlesen(text, lokal=()):
    """Client-Datei fuer den Container (wie man sie fuer ein Handy schreibt) -> Angaben, privater Schluessel, PSK.

    Uebernommen werden [Interface] PrivateKey + Address und [Peer] PublicKey, PresharedKey, Endpoint, AllowedIPs.
    Alles ueber den Tunnel (0.0.0.0/0, ::/0) wird auf das VPN-Netz beschraenkt, DNS/MTU/IPv6 bleiben weg.
    Rueckgabe: ({server, schluessel, adresse, netze, server_ip}, privat, psk oder None, [hinweise])."""
    if len(text or "") > 4000:
        raise VpnFehler("Die Datei ist zu groß für eine WireGuard-Config.")
    werte, abschnitt, peers, hinweise = {"interface": {}, "peer": {}}, None, 0, []
    for zeile in (text or "").splitlines():
        z = zeile.split("#", 1)[0].strip()
        if not z:
            continue
        m = re.fullmatch(r"\[(\w+)\]", z)
        if m:
            abschnitt = m.group(1).lower()
            peers += abschnitt == "peer"
            continue
        if "=" in z and abschnitt in werte:
            k, v = z.split("=", 1)
            werte[abschnitt].setdefault(k.strip().lower(), v.strip())
    i, pe = werte["interface"], werte["peer"]
    if not i or not pe:
        raise VpnFehler("Das ist keine WireGuard-Config: Es fehlt [Interface] oder [Peer].")
    if peers > 1:
        raise VpnFehler("Die Datei hat mehrere [Peer]. Für den Container gehört nur der Server hinein.")
    privat = _schluessel(i.get("privatekey"), "PrivateKey unter [Interface]")
    psk = _schluessel(pe["presharedkey"], "PresharedKey") if pe.get("presharedkey") else None
    if not pe.get("endpoint"):
        raise VpnFehler("Unter [Peer] fehlt Endpoint (Adresse:Port des Servers).")
    adressen = [a.strip() for a in i.get("address", "").split(",") if a.strip()]
    v4 = [a for a in adressen if ":" not in a]
    if not v4:
        raise VpnFehler("Unter [Interface] fehlt eine IPv4-Adresse (Address = 10.8.0.20/24).")
    if len(adressen) > 1:
        hinweise.append("Nur die IPv4-Adresse %s wird verwendet." % v4[0].split("/")[0])
    try:
        eigen = ipaddress.IPv4Interface(v4[0] if "/" in v4[0] and not v4[0].endswith("/32") else v4[0].split("/")[0] + "/24")
    except ValueError:
        raise VpnFehler("Address unter [Interface] ist keine IPv4-Adresse.") from None
    netze = []
    for n in pe.get("allowedips", "").split(","):
        n = n.strip()
        if not n or ":" in n:
            continue
        try:
            netz = ipaddress.IPv4Network(n, strict=False)
        except ValueError:
            raise VpnFehler("AllowedIPs: %s ist kein Netz." % n) from None
        if netz.prefixlen < 8:
            hinweise.append("AllowedIPs %s (alles über den Tunnel) gilt für den Container nicht, er nutzt nur das VPN-Netz." % n)
            continue
        ueberschneidung = [name for name, lnetz in lokal if netz.overlaps(lnetz)]
        if ueberschneidung:
            hinweise.append("%s bleibt draußen: Es überschneidet sich mit dem Netz von %s." % (n, ueberschneidung[0]))
            continue
        netze.append(netz)
    if not any(eigen.ip in n for n in netze):
        netze.insert(0, eigen.network)
    if i.get("dns"):
        hinweise.append("DNS wird nicht übernommen, der Container nutzt sein eigenes.")
    adresse, netze, server_ip = pruefen(pe["endpoint"], pe.get("publickey"), str(eigen.ip), " ".join(map(str, netze)), "", lokal)
    return ({"server": pe["endpoint"].strip(), "schluessel": pe["publickey"].strip(), "adresse": adresse,
             "netze": " ".join(netze), "server_ip": server_ip}, privat, psk, hinweise)


def angaben_pruefen(d, lokal=()):
    """Auftrag aus dem Formular oder der Anfrage-Datei -> bereinigtes dict, sonst VpnFehler.
    Mit einer Client-Datei (conf) kommen privat, psk und hinweise dazu; die gehen nie an die Seite zurueck."""
    aktion = d.get("aktion")
    if aktion not in AKTIONEN:
        raise VpnFehler("Unbekannte Aktion.")
    if aktion != "einrichten":
        return {"aktion": aktion}
    schnitt = str(d.get("server_if") or "").strip() or "wg0"
    if not SCHNITTSTELLE.fullmatch(schnitt):
        raise VpnFehler("Name der WireGuard-Schnittstelle auf dem Server bitte wie in /etc/wireguard, z. B. wg0.")
    if d.get("conf"):
        angaben, privat, psk, hinweise = conf_einlesen(str(d["conf"]), lokal)
        return dict(angaben, aktion=aktion, server_if=schnitt, privat=privat, psk=psk, hinweise=hinweise)
    server = str(d.get("server") or "").strip()
    schluessel = str(d.get("schluessel") or "").strip()
    adresse, netze, server_ip = pruefen(server, schluessel, str(d.get("adresse") or ""), str(d.get("netze") or ""),
                                        str(d.get("server_ip") or ""), lokal)
    return {"aktion": aktion, "server": server, "schluessel": schluessel, "adresse": adresse, "netze": " ".join(netze),
            "server_ip": server_ip, "server_if": schnitt}


def schluessel_ablegen(privat, psk):
    """Als root: Schluessel aus der Client-Datei nach /etc/wireguard (nur root lesbar), PSK oder keinen."""
    os.makedirs(os.path.dirname(SCHLUESSEL), mode=0o700, exist_ok=True)
    for pfad, inhalt in ((SCHLUESSEL, privat), (PSK, psk)):
        if inhalt is None:
            if os.path.exists(pfad):
                os.remove(pfad)
            continue
        fd = os.open(pfad + ".neu", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(inhalt + "\n")
        os.replace(pfad + ".neu", pfad)


def eingerichtet():
    return os.path.exists(EINHEIT)


def _protokoll():
    try:
        with open(os.path.join(VPN_DIR, "protokoll.txt"), encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-200:])
    except OSError:
        return ""


def _laeuft(lauf):
    if not lauf or not lauf.get("beginn") or lauf.get("ende"):
        return False
    try:
        return datetime.datetime.fromisoformat(db.jetzt()) - datetime.datetime.fromisoformat(lauf["beginn"]) < LAUF_MAX
    except ValueError:
        return False


def web_stand(daten_dir):
    lauf = _lesen("lauf.json")
    return {"eingerichtet": eingerichtet(), "einrichtung": _lesen("einrichtung.json"), "sperrtest": kurz(), "lauf": lauf,
            "laeuft": _laeuft(lauf), "wartet": os.path.exists(_anfrage_pfad(daten_dir)), "protokoll": _protokoll()}


def anfordern(daten_dir, daten):
    if not eingerichtet():
        raise VpnFehler("Das VPN lässt sich über die Seite nur im Container einrichten (nach dem nächsten Update über "
                        "die Konsole).")
    s = web_stand(daten_dir)
    if s["laeuft"] or s["wartet"]:
        raise VpnFehler("Es läuft schon ein Auftrag. Bitte kurz warten.")
    d = dict(daten)
    if d.get("aktion") == "einrichten" and not d.get("conf"):
        d["server"] = server_text(d.get("server"), d.get("port"))
    try:
        lokal = eigene_netze()
    except (OSError, ValueError):
        lokal = []   # root prueft ohnehin noch einmal
    angaben = angaben_pruefen(d, lokal)
    # Mit Client-Datei geht die Datei selbst an root (sie enthaelt den privaten Schluessel des Containers): nur fuer den
    # Webdienst lesbar und nur, bis root sie abholt.
    auftrag = {"aktion": angaben["aktion"], "conf": d["conf"], "server_if": angaben["server_if"]} if "privat" in angaben \
        else {k: v for k, v in angaben.items() if k != "hinweise"}
    pfad = _anfrage_pfad(daten_dir)
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    fd = os.open(pfad + ".neu", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(dict(auftrag, zeit=db.jetzt()), f)
    os.replace(pfad + ".neu", pfad)
    return {k: v for k, v in angaben.items() if k not in ("privat", "psk")}


def anfrage_lesen(pfad):
    """Als root: Anfrage-Datei lesen und loeschen. Kein Symlink, nur eine kleine regulaere Datei."""
    try:
        fd = os.open(pfad, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        raise VpnFehler("Keine Anfrage gefunden.") from None
    try:
        roh = os.read(fd, 8192) if stat.S_ISREG(os.fstat(fd).st_mode) else b""
    finally:
        os.close(fd)
        try:
            os.unlink(pfad)
        except OSError:
            pass
    try:
        d = json.loads(roh.decode("utf-8"))
    except ValueError:
        raise VpnFehler("Die Anfrage ist unlesbar.") from None
    if not isinstance(d, dict):
        raise VpnFehler("Die Anfrage ist unlesbar.")
    return angaben_pruefen(d, eigene_netze())


def _conf_angaben(text):
    angaben, privat, psk, hinweise = conf_einlesen(text, eigene_netze())
    return dict(angaben, privat=privat, psk=psk, hinweise=hinweise)


def _oeffentlicher_schluessel(text):
    try:
        if len(base64.b64decode((text or "").strip(), validate=True)) == 32:
            return text.strip()
    except ValueError:
        pass
    raise VpnFehler("Öffentlicher Schlüssel des Containers ungültig.")


def info_ablegen(container_schluessel, aktiv, server_if=None, aus_datei=None):
    """Als root nach dem Einrichten/Ausschalten: was die Seite fuer Peer-Block und VPS-Befehle braucht.
    aus_datei: eingerichtet mit einer Client-Datei (der Server kennt den Container dann meist schon)."""
    with open(KONF, encoding="utf-8") as f:
        text = f.read()
    adresse, netze, server_ip = konf_lesen(text)
    werte = dict(re.findall(r"^\s*(Endpoint|PublicKey)\s*=\s*(\S+)", text, re.M))
    alt = _lesen("einrichtung.json") or {}
    konf = "\n".join(z for z in text.splitlines() if not z.strip().lower().startswith(("privatekey", "presharedkey"))) + "\n"
    info = {"zeit": db.jetzt(), "aktiv": bool(aktiv), "name": socket.gethostname().split(".")[0],
            "adresse": str(adresse), "netze": [str(n) for n in netze], "server_ip": str(server_ip) if server_ip else None,
            "server": werte.get("Endpoint"), "server_schluessel": werte.get("PublicKey"),
            "container_schluessel": _oeffentlicher_schluessel(container_schluessel),
            "server_if": server_if or alt.get("server_if") or "wg0", "konf": konf,
            "aus_datei": alt.get("aus_datei", False) if aus_datei is None else aus_datei, "psk": os.path.exists(PSK)}
    _schreiben("einrichtung.json", info)
    return info


TEXTE = {
    "dicht": "Sperre wirkt: über das VPN ist vom Container aus nichts erreichbar.",
    "offen": "ACHTUNG: Der Container erreicht über das VPN andere Geräte. Sperre auf dem Server einrichten oder prüfen "
             "(vps/sperre.sh).",
    "keine_verbindung": "Keine Verbindung zum Server (kein Handshake in den letzten 5 Minuten), Sperre nicht geprüft.",
    "aus": "VPN ist aus (wg0 nicht aktiv).",
}


def _sperrtest_main(leise):
    try:
        with open(KONF, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        print("VPN nicht eingerichtet (trackingdrs vpn einrichten).", file=sys.stderr)
        return 1
    try:
        erg = sperrtest(text)
    except (KeyError, ValueError) as f:
        print("Fehler: %s lässt sich nicht lesen (%s)." % (KONF, f), file=sys.stderr)
        return 1
    ablegen(erg)
    if not leise:
        print("Sperrtest: versuche als root %s zu erreichen (Ping, TCP %s)." % (", ".join(erg["ziele"]),
                                                                              ", ".join(map(str, PORTS))))
        for z in erg["ziele"]:
            durch = [p["art"] for p in erg["proben"] if p["ziel"] == z and p["durch"]]
            if erg["proben"]:
                print("  %-15s %s" % (z, "DURCHGEKOMMEN: " + ", ".join(durch) if durch else "gesperrt"))
    print(TEXTE[erg["ergebnis"]])
    return {"dicht": 0, "aus": 0, "offen": 2}.get(erg["ergebnis"], 1)


def main(argv):
    if argv[:1] == ["sperrtest"]:
        return _sperrtest_main("--leise" in argv)
    try:
        if argv[:1] in (["anfrage-lesen"], ["conf-lesen"]) and len(argv) == 2:
            if argv[0] == "anfrage-lesen":
                a = anfrage_lesen(argv[1])
            else:   # trackingdrs vpn einrichten --conf <datei>
                with open(argv[1], encoding="utf-8") as f:
                    a = dict(aktion="einrichten", server_if="", **_conf_angaben(f.read()))
            if a.get("privat"):
                schluessel_ablegen(a["privat"], a["psk"])
            for h in a.get("hinweise", []):
                print("Hinweis: %s" % h, file=sys.stderr)
            print("|".join([*(a.get(k, "") for k in ("aktion", "server", "schluessel", "adresse", "netze", "server_ip",
                                                     "server_if")), "1" if a.get("psk") else "", "1" if a.get("privat") else ""]))
            return 0
        if argv[:1] == ["info-ablegen"] and len(argv) in (3, 4, 5):
            info_ablegen(argv[1], argv[2] == "1", argv[3] if len(argv) >= 4 and argv[3] else None,
                         (argv[4] == "1") if len(argv) == 5 and argv[4] else None)
            return 0
    except (VpnFehler, OSError, KeyError, ValueError) as f:
        print("Fehler: %s" % f, file=sys.stderr)
        return 1
    if len(argv) < 5 or argv[0] != "pruefen":
        print(__doc__)
        return 1
    try:
        a, netze, s = pruefen(argv[1], argv[2], argv[3], argv[4], argv[5] if len(argv) > 5 else "", eigene_netze())
    except VpnFehler as f:
        print("Fehler: %s" % f, file=sys.stderr)
        return 1
    print("%s|%s|%s" % (a, " ".join(netze), s))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
