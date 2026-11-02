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
  python3 -m app.vpn info-ablegen <oeffentlicher schluessel des containers> <aktiv 0|1> [<schnittstelle auf dem server>]
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


def angaben_pruefen(d, lokal=()):
    """Auftrag aus dem Formular oder der Anfrage-Datei -> bereinigtes dict, sonst VpnFehler."""
    aktion = d.get("aktion")
    if aktion not in AKTIONEN:
        raise VpnFehler("Unbekannte Aktion.")
    if aktion != "einrichten":
        return {"aktion": aktion}
    server = str(d.get("server") or "").strip()
    schluessel = str(d.get("schluessel") or "").strip()
    adresse, netze, server_ip = pruefen(server, schluessel, str(d.get("adresse") or ""), str(d.get("netze") or ""),
                                        str(d.get("server_ip") or ""), lokal)
    schnitt = str(d.get("server_if") or "").strip() or "wg0"
    if not SCHNITTSTELLE.fullmatch(schnitt):
        raise VpnFehler("Name der WireGuard-Schnittstelle auf dem Server bitte wie in /etc/wireguard, z. B. wg0.")
    return {"aktion": aktion, "server": server, "schluessel": schluessel, "adresse": adresse, "netze": " ".join(netze),
            "server_ip": server_ip, "server_if": schnitt}


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
    if d.get("aktion") == "einrichten":
        d["server"] = server_text(d.get("server"), d.get("port"))
    try:
        lokal = eigene_netze()
    except (OSError, ValueError):
        lokal = []   # root prueft ohnehin noch einmal
    angaben = dict(angaben_pruefen(d, lokal), zeit=db.jetzt())
    pfad = _anfrage_pfad(daten_dir)
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad + ".neu", "w", encoding="utf-8") as f:
        json.dump(angaben, f)
    os.replace(pfad + ".neu", pfad)
    return angaben


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


def _oeffentlicher_schluessel(text):
    try:
        if len(base64.b64decode((text or "").strip(), validate=True)) == 32:
            return text.strip()
    except ValueError:
        pass
    raise VpnFehler("Öffentlicher Schlüssel des Containers ungültig.")


def info_ablegen(container_schluessel, aktiv, server_if=None):
    """Als root nach dem Einrichten/Ausschalten: was die Seite fuer Peer-Block und VPS-Befehle braucht."""
    with open(KONF, encoding="utf-8") as f:
        text = f.read()
    adresse, netze, server_ip = konf_lesen(text)
    werte = dict(re.findall(r"^\s*(Endpoint|PublicKey)\s*=\s*(\S+)", text, re.M))
    alt = _lesen("einrichtung.json") or {}
    konf = "\n".join(z for z in text.splitlines() if not z.strip().lower().startswith("privatekey")) + "\n"
    info = {"zeit": db.jetzt(), "aktiv": bool(aktiv), "name": socket.gethostname().split(".")[0],
            "adresse": str(adresse), "netze": [str(n) for n in netze], "server_ip": str(server_ip) if server_ip else None,
            "server": werte.get("Endpoint"), "server_schluessel": werte.get("PublicKey"),
            "container_schluessel": _oeffentlicher_schluessel(container_schluessel),
            "server_if": server_if or alt.get("server_if") or "wg0", "konf": konf}
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
        if argv[:1] == ["anfrage-lesen"] and len(argv) == 2:
            a = anfrage_lesen(argv[1])
            print("|".join(a.get(k, "") for k in ("aktion", "server", "schluessel", "adresse", "netze", "server_ip", "server_if")))
            return 0
        if argv[:1] == ["info-ablegen"] and len(argv) in (3, 4):
            info_ablegen(argv[1], argv[2] == "1", argv[3] if len(argv) == 4 and argv[3] else None)
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
