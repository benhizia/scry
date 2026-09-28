"""Chaine RAVEN de bout en bout, sans IHM.

demo_sim publie en memoire partagee, raven acquiert et enregistre sur ordre du
protocole texte, raven-cat relit le .rvn. C'est la preuve que le descripteur
genere par Scry, la glue du simulateur, l'anneau partage, l'enregistreur et le
relecteur s'accordent sur le meme layout.

Saute si les executables ne sont pas construits :

    cmake -S raven -B build/raven && cmake --build build/raven --config Release

RAVEN_BUILD_DIR designe un autre dossier de build.
"""

import os
import socket
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _build_dir():
    candidats = []
    if os.environ.get("RAVEN_BUILD_DIR"):
        candidats.append(Path(os.environ["RAVEN_BUILD_DIR"]))
    candidats += sorted((ROOT / "build").glob("raven*")) if (ROOT / "build").is_dir() else []
    for base in candidats:
        for exe_dir in (base / "Release", base):        # multi-config, puis simple
            raven = exe_dir / "raven.exe"
            if not raven.is_file():
                raven = exe_dir / "raven"
            desc = base / "demo_gen" / "demo.rvndesc"
            if raven.is_file() and desc.is_file():
                return base, exe_dir, desc
    return None, None, None


BUILD, EXE_DIR, DESC = _build_dir()

pytestmark = pytest.mark.skipif(
    BUILD is None,
    reason="RAVEN pas construit : cmake -S raven -B build/raven && "
           "cmake --build build/raven --config Release")


def _exe(nom):
    chemin = EXE_DIR / (nom + ".exe")
    return chemin if chemin.is_file() else EXE_DIR / nom


def _port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _lignes(sock, duree):
    """Tout ce que raven envoie pendant 'duree', en lignes."""
    sock.settimeout(duree)
    fin, morceaux = time.time() + duree, []
    while time.time() < fin:
        try:
            data = sock.recv(65536)
        except socket.timeout:
            break
        if not data:
            break
        morceaux.append(data.decode("utf-8", "replace"))
    return "".join(morceaux).splitlines()


@pytest.fixture(scope="module")
def enregistrement(tmp_path_factory):
    """Lance la chaine, enregistre quelques secondes, retourne le .rvn."""
    segment = "raven_e2e_%s" % uuid.uuid4().hex[:8]
    port = _port_libre()
    sortie = tmp_path_factory.mktemp("raven") / "vol.rvn"

    sim = subprocess.Popen([str(_exe("demo_sim")), "--name", segment, "--seconds", "30"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    rec = subprocess.Popen([str(_exe("raven")), "--desc", str(DESC),
                            "--source", "shm:" + segment, "--port", str(port)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    etats = []
    try:
        time.sleep(1.0)
        sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        sock.sendall(b"hello\n")
        accueil = _lignes(sock, 2.0)
        sock.sendall(b"rec_all 1\n")
        sock.sendall(("path %s\n" % sortie.as_posix()).encode())
        sock.sendall(b"arm\n")
        _lignes(sock, 1.0)
        # Lire pendant l'enregistrement, comme le fait le visualiseur. raven
        # envoie valeurs et traces en continu et son envoi est bloquant : un
        # client qui dort sans lire remplit le tampon TCP et fige le moteur.
        _lignes(sock, 3.0)
        sock.sendall(b"stop\n")
        etats = [ligne for ligne in _lignes(sock, 2.0) if ligne.startswith("st ")]
        sock.close()
    finally:
        for proc in (rec, sim):
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    return accueil, etats, sortie


def _etat(ligne):
    return dict(champ.split("=", 1) for champ in ligne.split()[2:] if "=" in champ)


def test_descripteur_publie_a_la_connexion(enregistrement):
    accueil = enregistrement[0]
    assert "desc_begin" in accueil and "desc_end" in accueil
    assert any(ligne.startswith("rvndesc ") for ligne in accueil)
    assert any(ligne.startswith("channel ") and "g_flight" in ligne for ligne in accueil)


def test_acquisition_sans_perte(enregistrement):
    etats = enregistrement[1]
    assert etats, "aucun etat renvoye apres stop"
    etat = _etat(etats[-1])
    assert int(etat["frames"]) > 50, etat
    assert int(etat["lost"]) == 0, "trames perdues : %s" % etat
    assert int(etat["dropped"]) == 0, etat


def test_enregistrement_relu_par_raven_cat(enregistrement):
    etats, sortie = enregistrement[1], enregistrement[2]
    assert sortie.is_file() and sortie.stat().st_size > 0
    assert int(_etat(etats[-1])["rec"]) > 20

    info = subprocess.run([str(_exe("raven-cat")), str(sortie), "--info"],
                          capture_output=True, text=True, errors="replace")
    assert info.returncode == 0, info.stderr
    assert "g_flight.pos.alt" in info.stdout and "g_sim.state" in info.stdout

    csv = subprocess.run([str(_exe("raven-cat")), str(sortie)],
                         capture_output=True, text=True, errors="replace")
    assert csv.returncode == 0, csv.stderr
    lignes = csv.stdout.splitlines()
    entete = lignes[0].split(",")
    assert entete[:2] == ["frame", "t_ns"] and "g_flight.phase" in entete
    assert len(lignes) - 1 == int(_etat(etats[-1])["rec"])
    # Enums en texte, booleens lisibles : le relecteur applique le descripteur.
    valeurs = lignes[1].split(",")
    assert valeurs[entete.index("g_flight.phase")] in {"Sol", "Montee", "Climb",
                                                       "Croisiere", "Cruise", "Descente"}
    assert valeurs[entete.index("g_flight.gear_down")] in {"true", "false"}


def test_reste_pilotable_quand_le_visualiseur_ne_lit_plus(tmp_path):
    """Un visualiseur qui cesse de lire ne doit pas figer l'enregistreur.

    raven publie environ vingt fois par seconde ; si l'envoi etait bloquant,
    le tampon TCP se remplissait et le moteur n'executait plus aucune
    commande : impossible d'arreter un enregistrement en cours. Ici, le
    client se tait volontairement, puis demande stop : la reponse doit
    arriver tout de suite, et l'enregistrement etre complet.
    """
    segment = "raven_mute_%s" % uuid.uuid4().hex[:8]
    port = _port_libre()
    sortie = tmp_path / "muet.rvn"

    sim = subprocess.Popen([str(_exe("demo_sim")), "--name", segment, "--seconds", "30"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    rec = subprocess.Popen([str(_exe("raven")), "--desc", str(DESC),
                            "--source", "shm:" + segment, "--port", str(port)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.0)
        sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        sock.sendall(b"hello\n")
        _lignes(sock, 1.5)
        sock.sendall(b"rec_all 1\n")
        sock.sendall(("path %s\n" % sortie.as_posix()).encode())
        sock.sendall(b"arm\n")

        # Le client se tait : il n'appelle plus recv du tout.
        time.sleep(3.0)

        depart = time.time()
        sock.sendall(b"stop\n")
        etats = []
        while time.time() - depart < 15.0 and not any("msg=arrete" in e for e in etats):
            etats += [x for x in _lignes(sock, 1.0) if x.startswith("st ")]
        delai = time.time() - depart
        sock.close()
    finally:
        for proc in (rec, sim):
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    arrets = [e for e in etats if "msg=arrete" in e]
    assert arrets, "raven n'a pas traite stop : %s" % etats[-1:]
    # Le temps de vider le retard accumule, pas des minutes.
    assert delai < 10.0, "stop traite en %.1f s" % delai
    assert int(_etat(arrets[-1])["rec"]) > 20, arrets[-1]
    assert sortie.is_file() and sortie.stat().st_size > 0
