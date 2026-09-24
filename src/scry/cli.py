"""Acces en ligne de commande, sans OpenGL ni ImGui.

Indispensable pour deboguer la chaine castxml sans dependre du rendu, et pour
brancher Scry dans un build ou une CI.

    scry check                       verifie la configuration et l'outillage
    scry dump                        affiche l'arbre des structures
    scry gen                         ecrit le header C++ d'introspection
    scry json modele.json            exporte le modele brut
    scry ui                          visualiseur ImGui
    scry verify                      compile les assertions ABI (cl, g++, clang++), par profil
    scry viewer --run                compile et lance le visualiseur C++ natif

Selection des headers, cumulables et acceptant les motifs glob :

    scry dump -H Data/a.h -H Data/b.h
    scry dump -H "Data/**/*.h"
    scry dump                        utilise [paths] headers de scry.ini

Sans -H, ce sont [paths] headers puis, a defaut, [paths] header qui servent.
"""

import argparse
import os
import sys

from scry.config import load_config
from scry.parsing.introspect import Introspector


def _print_report(introspector, verbose):
    """Incidents de parsing, sur stderr pour ne pas polluer une sortie piped."""
    lines = introspector.report.lines(verbose=verbose)
    if not lines:
        return
    print(file=sys.stderr)
    for line in lines:
        print(line, file=sys.stderr)


def cmd_check(args, cfg):
    print(cfg.describe())
    print()
    try:
        files = Introspector(cfg).resolve_headers(args.header)
        print("Headers (%d) :" % len(files))
        for path in files:
            print("  %s" % path)
    except Exception as exc:
        print("Headers : %s" % exc)
    print()

    if cfg.compiler == "msvc":
        from scry.parsing import msvc_env
        return msvc_env.main(cfg)
    from scry.parsing.msvc_env import MsvcNotFound, locate_castxml
    try:
        castxml, origin = locate_castxml(cfg)
    except MsvcNotFound as exc:
        print("[erreur] %s" % exc)
        return 1
    print("castxml : %s  (%s)" % (castxml, origin))
    return 0


def cmd_dump(args, cfg):
    introspector = Introspector(cfg)
    structs = introspector.parse(args.header)

    for s in structs:
        print("=== %s  %s  sizeof=%s  alignof=%s  padding=%s%s"
              % (s.name, s.kind, s.size, s.align, s.padding_bytes(),
                 "  polymorphe" if s.is_polymorphic else ""))
        if args.verbose and s.header:
            print("    %s" % s.header)
        for field, depth in s.walk():
            note = ("  [%s]" % field.truncated) if field.truncated else ""
            print("  %s%-24s %-24s %-12s @%-5s %s o%s"
                  % ("  " * depth, field.label(), field.type_name, field.kind,
                     field.abs_offset, field.size, note))
        print()

    print("%d structure(s) depuis %d header(s)."
          % (len(structs), len(introspector.report.parsed)))
    _print_report(introspector, args.verbose)
    return 1 if introspector.report.conflicts else 0


def cmd_gen(args, cfg):
    from scry.codegen import generator as codegen
    introspector = Introspector(cfg)
    structs = introspector.parse(args.header)
    path = codegen.generate(structs, cfg, header=args.header)
    print("Ecrit : %s  (%d structures)" % (path, len(structs)))
    if cfg.emit_abi_checks:
        print("Ecrit : %s" % os.path.join(str(cfg.output_dir), cfg.abi_header))
    _print_report(introspector, args.verbose)
    return 1 if introspector.report.conflicts else 0


def cmd_json(args, cfg):
    from scry.codegen import generator as codegen
    introspector = Introspector(cfg)
    structs = introspector.parse(args.header)
    print("Ecrit : %s" % codegen.dump_json(structs, args.out))
    _print_report(introspector, args.verbose)
    return 1 if introspector.report.conflicts else 0


def cmd_verify(args, cfg):
    """Compile les assertions ABI avec cl, g++ ou clang++, pour chaque profil."""
    from scry import verify

    profiles = verify.load_profiles(cfg)
    if args.profile:
        wanted = set(args.profile)
        profiles = [p for p in profiles if p[0] in wanted]
        if not profiles:
            print("[erreur] aucun profil nomme %s dans [verify] profiles."
                  % ", ".join(sorted(wanted)), file=sys.stderr)
            return 1

    introspector = Introspector(cfg)
    structs = introspector.parse(args.header)
    abi_path, results = verify.run(structs, cfg, profiles, header=args.header)

    if verify.is_msvc(cfg):
        print("Modele castxml : cl_flags = %s" % (cfg.cl_flags or "aucune, build release"))
    else:
        print("Modele castxml : %s, compile avec %s" % (cfg.compiler, verify.compiler_label(cfg)))
    print("Header ABI     : %s  (%d structures)" % (abi_path, len(structs)))
    print()
    for r in results:
        print("[%-5s] %-10s %s" % ("OK" if r.ok else "ECHEC", r.name, r.flags))
        shown = r.errors if args.verbose else r.errors[:10]
        for line in shown:
            print("          %s" % line)
        if len(shown) < len(r.errors):
            print("          ... %d autre(s), -v pour tout voir"
                  % (len(r.errors) - len(shown)))
        if not r.ok and not r.errors:
            print(r.output)

    _print_report(introspector, args.verbose)
    failed = [r.name for r in results if not r.ok]
    if failed:
        print()
        print("Le modele ne correspond pas aux profils : %s. Regler [castxml] "
              "%s et defines sur la configuration visee."
              % (", ".join(failed), "cl_flags" if verify.is_msvc(cfg) else "extra_cflags"))
    return 1 if failed or introspector.report.conflicts else 0


def cmd_viewer(args, cfg):
    """Compile le visualiseur C++ natif a partir du header genere."""
    if cfg.compiler != "msvc":
        print("[erreur] scry viewer ne sait compiler qu'avec MSVC (compiler = %s)."
              % cfg.compiler, file=sys.stderr)
        return 1
    from scry.viewer import build as viewer_build

    introspector = Introspector(cfg)
    structs = introspector.parse(args.header)
    try:
        exe = viewer_build.build(structs, cfg, header=args.header, fetch=args.fetch_imgui)
    except viewer_build.ViewerError as exc:
        print("[erreur] %s" % exc, file=sys.stderr)
        return 1
    print("Visualiseur : %s  (%d structures)" % (exe, len(structs)))
    _print_report(introspector, args.verbose)
    if args.run:
        viewer_build.launch(exe)
        print("Lance.")
    return 0


def cmd_ui(args, cfg):
    """Le visualiseur ImGui.

    L'import est local : sans lui, une machine sans OpenGL ne pourrait plus
    lancer 'scry check', ce qui est justement le diagnostic dont elle a besoin.
    """
    try:
        from scry.ui import app
    except ImportError as exc:
        print("[erreur] interface graphique indisponible : %s" % exc, file=sys.stderr)
        print("Installer les dependances UI : pip install -e .[ui]", file=sys.stderr)
        return 1
    app.main(cfg=cfg, header=args.header)
    return 0


def main(argv=None):
    # Les options communes sont declarees dans un parent partage par le parseur
    # principal et par chaque sous-commande, pour que 'scry -H x dump' et
    # 'scry dump -H x' marchent tous les deux. SUPPRESS est indispensable :
    # sans lui, la sous-commande ecraserait avec None la valeur donnee avant.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-H", "--header", action="append",
                        default=argparse.SUPPRESS, metavar="CHEMIN",
                        help="header a parser, cumulable, motifs glob acceptes")
    common.add_argument("-c", "--config", default=argparse.SUPPRESS,
                        help="fichier ini alternatif")
    common.add_argument("-v", "--verbose", action="store_true",
                        default=argparse.SUPPRESS,
                        help="details : origine des types, doublons")
    common.add_argument("--traceback", action="store_true",
                        default=argparse.SUPPRESS,
                        help="pile complete en cas d'erreur")

    ap = argparse.ArgumentParser(description=__doc__, parents=[common],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("check", parents=[common],
                   help="verifie la configuration et l'outillage")
    sub.add_parser("dump", parents=[common], help="affiche l'arbre des structures")
    sub.add_parser("gen", parents=[common], help="genere le header C++")
    p_json = sub.add_parser("json", parents=[common], help="exporte le modele en JSON")
    p_json.add_argument("out", nargs="?", default="modele.json")
    sub.add_parser("ui", parents=[common], help="visualiseur ImGui")
    p_verify = sub.add_parser("verify", parents=[common],
                              help="compile les assertions ABI (cl, g++, clang++), par profil")
    p_verify.add_argument("-p", "--profile", action="append", metavar="NOM",
                          help="ne verifier que ce profil, cumulable")
    p_viewer = sub.add_parser("viewer", parents=[common],
                              help="compile le visualiseur C++ natif (ImGui, DirectX 11)")
    p_viewer.add_argument("--run", action="store_true",
                          help="lance l'executable apres compilation")
    p_viewer.add_argument("--fetch-imgui", action="store_true",
                          help="git clone de Dear ImGui s'il est absent ; sinon, "
                               "deposer les sources a la main (third_party/README.md)")

    args = ap.parse_args(argv)
    args.header = getattr(args, "header", None)
    args.config = getattr(args, "config", None)
    args.verbose = getattr(args, "verbose", False)
    args.traceback = getattr(args, "traceback", False)
    cfg = load_config(args.config) if args.config else load_config()

    handlers = {"check": cmd_check, "dump": cmd_dump, "gen": cmd_gen,
                "json": cmd_json, "ui": cmd_ui, "verify": cmd_verify,
                "viewer": cmd_viewer}
    handler = handlers.get(args.cmd)
    if handler is None:
        ap.print_help()
        return 1

    try:
        return handler(args, cfg)
    except Exception as exc:
        if args.traceback:
            import traceback
            traceback.print_exc()
        else:
            # Le type compte autant que le message : une KeyError n'affiche que
            # sa cle, ce qui ne dit rien de son origine sans le nom de classe.
            print("[%s] %s" % (type(exc).__name__, exc), file=sys.stderr)
            print("Relancer avec --traceback pour la pile complete.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
