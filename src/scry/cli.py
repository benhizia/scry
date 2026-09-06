"""Acces en ligne de commande, sans OpenGL ni ImGui.

Indispensable pour deboguer la chaine castxml sans dependre du rendu, et pour
brancher Scry dans un build ou une CI.

    scry check                  verifie la configuration et l'outillage
    scry dump                   affiche l'arbre des structures
    scry gen                    ecrit le header C++ d'introspection
    scry json modele.json       exporte le modele brut
    scry ui                     visualiseur ImGui
    scry dump -H autre.h        cible un autre header
"""

import argparse
import sys

from scry.config import load_config
from scry.parsing.introspect import Introspector


def cmd_check(args, cfg):
    print(cfg.describe())
    print()
    if cfg.compiler == "msvc":
        from scry.parsing import msvc_env
        return msvc_env.main(cfg)
    from pygccxml import utils
    print("castxml : %s" % (utils.find_xml_generator(),))
    return 0


def cmd_dump(args, cfg):
    structs = Introspector(cfg).parse(args.header)
    for s in structs:
        print("=== %s  %s  sizeof=%s  alignof=%s  padding=%s%s"
              % (s.name, s.kind, s.size, s.align, s.padding_bytes(),
                 "  polymorphe" if s.is_polymorphic else ""))
        for field, depth in s.walk():
            note = ("  [%s]" % field.truncated) if field.truncated else ""
            print("  %s%-24s %-24s %-12s @%-5s %s o%s"
                  % ("  " * depth, field.label(), field.type_name, field.kind,
                     field.abs_offset, field.size, note))
        print()
    return 0


def cmd_gen(args, cfg):
    from scry.codegen import generator as codegen
    structs = Introspector(cfg).parse(args.header)
    path = codegen.generate(structs, cfg, header=args.header)
    print("Ecrit : %s" % path)
    return 0


def cmd_json(args, cfg):
    from scry.codegen import generator as codegen
    structs = Introspector(cfg).parse(args.header)
    print("Ecrit : %s" % codegen.dump_json(structs, args.out))
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
    common.add_argument("-H", "--header", default=argparse.SUPPRESS,
                        help="header a parser, sinon [paths] header")
    common.add_argument("-c", "--config", default=argparse.SUPPRESS,
                        help="fichier ini alternatif")

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

    args = ap.parse_args(argv)
    args.header = getattr(args, "header", None)
    args.config = getattr(args, "config", None)
    cfg = load_config(args.config) if args.config else load_config()

    handlers = {"check": cmd_check, "dump": cmd_dump, "gen": cmd_gen,
                "json": cmd_json, "ui": cmd_ui}
    handler = handlers.get(args.cmd)
    if handler is None:
        ap.print_help()
        return 1
    try:
        return handler(args, cfg)
    except Exception as exc:
        print("[erreur] %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
