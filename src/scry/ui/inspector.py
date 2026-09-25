"""Inspecteur : tout ce que le modele sait du noeud selectionne.

facts() est une fonction pure, testee sans imgui ; render() se contente de
l'afficher. L'import d'imgui est local a render() pour que les tests tournent
sur une machine sans OpenGL.
"""

from typing import List, Optional, Tuple

from scry import model
from scry.codegen.generator import _cpp_identifier
from scry.runtime.memory import MemorySource, decode
from scry.ui.tree import TreeNode

# Valeurs cliquables pour les copier dans le presse-papiers.
COPYABLE = ("Chemin", "offsetof", "Lecture C++")

MAX_BYTES = 32

TRUNCATION_TEXT = {
    "cycle": "type deja present dans la branche : descente interrompue pour "
             "eviter une boucle",
    "depth": "profondeur maximale atteinte, voir [introspection] max_depth",
    "pointer": "pointeur non suivi, voir [introspection] follow_pointers",
    "opaque": "type incomplet : declare mais jamais defini, taille inconnue",
    "virtual": "base virtuelle : son offset depend du type le plus derive et se lit "
               "a l'execution dans la vtable, il n'est pas constant",
    "offset": "offset de la base non fourni par castxml",
}

Facts = List[Tuple[str, str]]


def _num(n: Optional[int]) -> str:
    return "-" if n is None else "%d  (0x%X)" % (n, n)


def _bytes(source: Optional[MemorySource], offset: int, size: Optional[int]) -> Optional[str]:
    if source is None or not size:
        return None
    raw = source.read(offset, min(size, MAX_BYTES))
    if raw is None:
        return None
    text = " ".join("%02X" % b for b in raw)
    return text + (" ..." if size > MAX_BYTES else "")


def facts(node: Optional[TreeNode], struct: Optional[model.Struct],
          source: Optional[MemorySource] = None, namespace: str = "scry") -> Facts:
    if node is None or struct is None:
        return []
    if node.is_root:
        return _root_facts(struct)
    if node.is_padding:
        return _padding_facts(node, source)
    return _field_facts(node, struct, source, namespace)


def _root_facts(s: model.Struct) -> Facts:
    out = [
        ("Nature", s.kind + (", polymorphe" if s.is_polymorphic else "")),
    ]
    if s.doc:
        out.append(("Doc", s.doc))
    out += [
        ("sizeof", "-" if s.size is None else "%d o" % s.size),
        ("alignof", "-" if s.align is None else "%d o" % s.align),
        ("Padding", "-" if s.size is None else "%d o" % s.padding_bytes()),
    ]
    holes = s.padding_spans()
    if holes:
        out.append(("Trous", ", ".join("%d o @%d" % (end - start, start)
                                        for start, end in holes)))
    total = sum(1 for _ in s.walk())
    out.append(("Membres", "%d au premier niveau, %d au total" % (len(s.fields), total)))
    if s.is_polymorphic:
        out.append(("vptr", "offset 0 : pointeur de vtable, ajoute par le compilateur"))
    if s.header:
        out.append(("Header", s.header))
    return out


def _padding_facts(node: TreeNode, source: Optional[MemorySource]) -> Facts:
    start, end = node.span
    parent = node.parent
    if node.label.startswith("[vptr"):
        reason = "pointeur de vtable ajoute par le compilateur pour un type polymorphe"
    elif parent is not None and parent.offset is not None and parent.size is not None \
            and end == parent.offset + parent.size:
        reason = ("padding de fin : arrondit la taille de %s a un multiple de son "
                  "alignement" % parent.label)
    else:
        reason = "octets inseres pour aligner le membre suivant sur son alignement"
    out = [
        ("Nature", "vptr" if node.label.startswith("[vptr") else "padding"),
        ("Debut", _num(start)),
        ("Fin", _num(end)),
        ("Taille", "%d o" % (end - start)),
        ("Raison", reason),
    ]
    if parent is not None and parent.kind == model.CLASS:
        out.append(("Attention", "type class : des membres non publics, masques par "
                                 "[introspection] include_non_public = false, "
                                 "apparaissent aussi comme padding"))
    raw = _bytes(source, start, end - start)
    if raw:
        out.append(("Octets", raw))
    return out


def _field_facts(node: TreeNode, s: model.Struct, source: Optional[MemorySource],
                 namespace: str) -> Facts:
    f = node.field
    out = [("Chemin", f.access_path), ("Nature", f.kind), ("Type", f.type_name)]
    if f.doc:
        out.append(("Doc", f.doc))
    if f.is_static:
        out.append(("Statique", "membre statique : hors instance, pas d'offset"))
        return out

    parent = node.parent.label if node.parent is not None else s.name
    out += [
        ("Offset absolu", _num(f.abs_offset)),
        ("Offset relatif", "%d dans %s" % (f.offset, parent)),
        ("Taille", "-" if f.size is None else "%d o" % f.size),
    ]
    if f.size is not None:
        out.append(("Fin", _num(f.abs_offset + f.size)))

    bit = f.bit_offset or 0
    if f.is_bitfield:
        out.append(("Bits", "octet %d, bit %d, largeur %d"
                    % (f.abs_offset + bit // 8, bit % 8, f.bit_width)))
        mask = ((1 << f.bit_width) - 1) << bit
        out.append(("Masque", "0x%X sur une unite de %s o" % (mask, f.size)))
    if f.kind == model.ARRAY and f.array_len:
        stride = f.size // f.array_len if f.size else None
        out += [("Elements", str(f.array_len)),
                ("Pas", "-" if stride is None else "%d o" % stride),
                ("Type d'element", f.elem_type or "?")]
    if f.enum_values or f.enum_items:
        out.append(("Valeurs", ", ".join("%d %s" % (value, name)
                                          for value, name in model.enum_cases(f))))
    if f.truncated:
        out.append(("Descente", TRUNCATION_TEXT.get(f.truncated, f.truncated)))

    # offsetof : invalide sur un champ de bits. Un type template contient une
    # virgule qui couperait la macro : on passe alors par l'alias genere.
    if f.access != "public":
        out.append(("Acces", "%s : ni offsetof ni lecture par nom hors de la "
                             "classe, seule la lecture par offset reste possible"
                    % f.access))
    if f.kind == model.BASE:
        out.append(("Base", "sous-objet de %s : ses membres s'atteignent par le "
                            "chemin de la classe derivee" % f.type_name))
    member = f.access_path.split(".", 1)[1] if "." in f.access_path else ""
    if member and not f.is_bitfield and f.access == "public" and f.kind != model.BASE:
        target = s.name
        if "," in target:
            target = "%s::abi::abi_%s" % (namespace, _cpp_identifier(s.name))
        out.append(("offsetof", "offsetof(%s, %s)" % (target, member)))

    if f.is_readable:
        if f.is_bitfield:
            expr = "read_bits(base, %d, %d, %d, %d)" % (f.abs_offset, f.size, bit, f.bit_width)
        elif f.kind == model.POINTER:
            expr = "read_at<std::uintptr_t>(base, %d)" % f.abs_offset
        else:
            expr = "read_at<%s>(base, %d)" % (f.type_name, f.abs_offset)
        out.append(("Lecture C++", expr))

    if source is not None:
        value = decode(source, f)
        if value is not None:
            out.append(("Valeur", value))
        raw = _bytes(source, f.abs_offset, f.size)
        if raw:
            out.append(("Octets", raw))
    return out


# ---------------------------------------------------------------------------
# Rendu
# ---------------------------------------------------------------------------
def render(node: Optional[TreeNode], struct: Optional[model.Struct],
           source: Optional[MemorySource] = None, namespace: str = "scry"):
    import imgui

    if node is None or struct is None:
        imgui.text_disabled("Selectionner une structure ou un membre.")
        return

    imgui.text(node.label)
    imgui.separator()

    flags = (getattr(imgui, "TABLE_ROW_BACKGROUND", 0)
             | getattr(imgui, "TABLE_BORDERS_INNER_VERTICAL", 0)
             | getattr(imgui, "TABLE_SIZING_STRETCH_PROP", 0))
    if not imgui.begin_table("inspecteur", 2, flags):
        return
    imgui.table_setup_column("Propriete", getattr(imgui, "TABLE_COLUMN_WIDTH_FIXED", 0), 110)
    imgui.table_setup_column("Valeur", getattr(imgui, "TABLE_COLUMN_WIDTH_STRETCH", 0), 1.0)
    for label, value in facts(node, struct, source, namespace):
        imgui.table_next_row()
        imgui.table_next_column()
        imgui.text_disabled(label)
        imgui.table_next_column()
        if label in COPYABLE:
            clicked, _ = imgui.selectable("%s##%s" % (value, label), False)
            if imgui.is_item_hovered():
                imgui.set_tooltip("Clic : copier")
            if clicked:
                imgui.set_clipboard_text(value)
        else:
            imgui.text_wrapped(value)
    imgui.end_table()
