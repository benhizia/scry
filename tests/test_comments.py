"""Commentaires de documentation relus dans le source, sans castxml."""

from scry.parsing import comments

HEADER = '''\
#pragma once
/// Doc de la struct
struct S {
    // Avant
    int value; // En ligne
    /* Bloc avant */
    double price; /* Bloc en ligne */

    /// Doxygen avant
    bool flag; ///< Doxygen en ligne
    /** Bloc
     *  sur deux lignes */
    char type;
    float ratio; //!< Bang
    bool multi; /* commence ici
                   et finit la */
    const char* url = "http://exemple"; // apres la chaine
    int nodoc;
    //!< documente nodoc, pas le suivant
    int suivant;
    int a; // doc de a
    int b;
};
'''
LINES = HEADER.splitlines()


def _doc(member):
    for i, line in enumerate(LINES):
        if (" %s;" % member) in line or (" %s =" % member) in line:
            return comments.comment_at(LINES, i + 1)
    raise AssertionError(member)


def test_struct():
    assert comments.comment_at(LINES, 3) == "Doc de la struct"


def test_avant_et_en_ligne_sont_concatenes():
    assert _doc("value") == "Avant En ligne"
    assert _doc("price") == "Bloc avant Bloc en ligne"
    # castxml n'en garde qu'un des deux.
    assert _doc("flag") == "Doxygen avant Doxygen en ligne"


def test_bloc_multiligne_avant():
    assert _doc("type") == "Bloc sur deux lignes"


def test_marqueurs_doxygen_retires():
    assert _doc("ratio") == "Bang"


def test_bloc_en_ligne_sur_plusieurs_lignes():
    assert _doc("multi") == "commence ici et finit la"


def test_double_barre_dans_une_chaine_ignoree():
    assert _doc("url") == "apres la chaine"


def test_ligne_vide_et_code_arretent_la_remontee():
    assert _doc("nodoc") == ""
    # Le commentaire de fin de ligne de a ne documente pas b.
    assert _doc("b") == ""


def test_post_commentaire_seul_n_est_pas_attribue_au_suivant():
    assert _doc("suivant") == ""


def test_brief_et_ligne_hors_limites():
    lines = ["/// @brief Resume", "int x;"]
    assert comments.comment_at(lines, 2) == "Resume"
    assert comments.comment_at(lines, 0) == ""
    assert comments.comment_at(lines, 99) == ""


def test_source_comments_lit_le_fichier_une_fois(tmp_path):
    header = tmp_path / "h.h"
    header.write_bytes("struct T {\n    int x; // \xe9t\xe9\n};\n".encode("cp1252"))

    class Loc(object):
        file_name = str(header)
        line = 2

    class Decl(object):
        location = Loc()

    src = comments.SourceComments()
    assert src.for_decl(Decl()) == "été"
    header.write_text("", encoding="utf-8")
    assert src.for_decl(Decl()) == "été"


def test_declaration_sans_emplacement():
    assert comments.SourceComments().for_decl(object()) == ""
