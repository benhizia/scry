"""Extraction du modele a partir de headers C++, via pygccxml et castxml.

Tout le savoir sur les pieges de pygccxml est concentre ici. Le reste du projet
ne voit que scry.model.

MULTI-FICHIERS
--------------
Chaque header est parse SEPAREMENT, et la fusion se fait sur le modele, pas sur
les arbres de declarations. Ce n'est pas un choix de confort.

parser.parse() passe par project_reader_t, qui execute systematiquement
_join_class_hierarchy(), une phase destinee a reconcilier les arbres issus de
plusieurs fichiers. Elle plante sur les hierarchies de templates de la STL :

    leaved_base = leaved_classes[self._create_key(base_info.related_class)]
    KeyError: (('...type_traits', 1874), ('::', 'std', 'type'))

La classe de base existe dans l'AST mais pas dans la liste aplatie construite
par la fusion. C'est reproductible des qu'un header inclut <variant>,
<optional>, <string> ou <map>, donc en pratique des qu'on sort du C 
structurel. On refait ici le pipeline utile a la main, et la fusion se passe
plus haut, sur des dataclasses plates ou elle est triviale et verifiable.

Bonus : la fusion au niveau du modele detecte qu'un meme type a deux layouts
differents selon le header d'ou on l'observe. C'est un signal d'ABI, pas un
detail d'implementation.

A ne pas confondre avec les repertoires d'include, qui restent de simples -I
passes a castxml via [castxml] include_paths.

PIEGES PYGCCXML, chacun rencontre pour de vrai
----------------------------------------------
  * class_t n'a pas de decl_type. Seuls variable_t et typedef_t en ont. Une
    struct imbriquee apparait dans la liste des membres au meme titre qu'un
    champ, d'ou l'AttributeError classique.
  * variables() est RECURSIF par defaut et remonte les membres des types
    imbriques melanges a ceux du parent. Il faut recursive=False.
  * byte_offset et byte_size sont des flottants. Pour un champ de bits,
    l'offset est fractionnaire : 392.125 signifie octet 392, bit 1.
  * remove_alias() reconstruit le type et perd byte_size. Un pointer_t qui
    annoncait 8 octets en annonce 0 apres resolution.
  * Les membres statiques ont un byte_offset de 0.0 qui ne veut rien dire.
  * Une struct ou union anonyme a un name vide, et son decl_string vaut le nom
    de la classe englobante, ce qui est trompeur.
  * classes() est recursif et remonte aussi les types imbriques et anonymes.
    Pour une liste de racines, filtrer sur parent == namespace.
  * Le filtre par fichier compare des chaines. Sur Windows, casse et
    separateurs different, d'ou des listes vides sans erreur.
  * Un type incomplet, pointe mais jamais defini, donne un class_declaration_t
    sans byte_size.
  * Les templates n'existent dans l'AST que s'ils sont instancies.
  * Les structures auto-referencantes bouclent sans garde-fou.
  * declarations.is_class() repond vrai sur un pointeur vers une classe.
    Tester is_pointer() avant, comme le fait _describe_type.
  * cls.bases ne donne ni l'offset des bases, ni leur caractere virtuel :
    is_virtual vaut toujours False. castxml les ecrit pourtant, dans des
    elements <Base> que pygccxml ne lit pas. Voir castxml_bases.
"""

import fnmatch
import glob
import hashlib
import os
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pygccxml import declarations, parser, utils
from pygccxml.parser import declarations_joiner, source_reader

from scry import model
from scry.config import Config, load_config
from scry.parsing import castxml_bases
from scry.parsing.comments import SourceComments

# pygccxml ignore les elements <Base> de castxml, donc l'offset des classes de
# base : on les recueille au passage (voir castxml_bases).
castxml_bases.install()


CACHE_FORMAT = "bases-1"


class IntrospectionError(RuntimeError):
    pass


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _int_or_none(value) -> Optional[int]:
    """byte_size et byte_offset sont des flottants chez pygccxml."""
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _qualified_name(decl) -> str:
    """Nom qualifie sans le :: initial.

    Indispensable en multi-fichiers : deux namespaces peuvent contenir un type
    du meme nom court. C'est aussi ce qu'il faut au C++ genere pour ecrire
    sizeof() et offsetof() correctement.
    """
    try:
        full = declarations.full_name(decl)
    except Exception:
        return decl.name
    return full[2:] if full.startswith("::") else full


class ParseReport(object):
    """Ce qui s'est passe pendant un parsing multi-fichiers.

    Separe du resultat : le modele reste une simple liste de Struct, et les
    incidents sont consultables sans polluer les consommateurs qui s'en fichent.
    """

    def __init__(self):
        self.parsed = []        # type: List[str]
        self.failures = []      # type: List[Tuple[str, str]]
        self.duplicates = []    # type: List[str]
        self.conflicts = []     # type: List[str]

    @property
    def ok(self) -> bool:
        return not self.failures and not self.conflicts

    def lines(self, verbose: bool = False) -> List[str]:
        """Incidents a afficher. Les doublons sont du bruit courant des qu'un
        header commun est inclus partout : ils ne sortent qu'en verbeux."""
        out = []
        for path, err in self.failures:
            out.append("[echec] %s : %s" % (os.path.basename(path), err))
        for msg in self.conflicts:
            out.append("[conflit] %s" % msg)
        if verbose:
            for msg in self.duplicates:
                out.append("[doublon] %s" % msg)
        return out


class Introspector(object):
    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or load_config()
        self._xml_config = None
        self.report = ParseReport()
        self._comments = SourceComments()

    # -- configuration ------------------------------------------------------
    def xml_config(self):
        if self._xml_config is not None:
            return self._xml_config

        cflags = ["-std=%s" % self.cfg.std]
        if self.cfg.extra_cflags:
            cflags.append(self.cfg.extra_cflags)

        common = dict(
            xml_generator="castxml",
            include_paths=list(self.cfg.include_paths),
            define_symbols=list(self.cfg.defines),
            cflags=" ".join(cflags),
        )

        if self.cfg.compiler == "msvc":
            from scry.parsing.msvc_env import build_castxml_config
            self._xml_config = build_castxml_config(self.cfg, **common)
        else:
            path = str(self.cfg.castxml_path) if self.cfg.castxml_path else None
            if path is None:
                path, _ = utils.find_xml_generator()
            self._xml_config = parser.xml_generator_configuration_t(
                xml_generator_path=path,
                compiler=self.cfg.compiler,
                **common
            )
        return self._xml_config

    @property
    def read_comments(self) -> bool:
        return self.cfg.get_bool("introspection", "comments", True)

    def _doc(self, decl) -> str:
        return self._comments.for_decl(decl) if self.read_comments else ""

    @property
    def stop_on_error(self) -> bool:
        return self.cfg.get_bool("introspection", "stop_on_error", False)

    @property
    def root_globs(self) -> List[str]:
        """Motifs de fichiers dont les types sont retenus comme racines.

        Par defaut, seuls les headers explicitement parses fournissent des
        racines. Ces motifs permettent d'elargir aux headers atteints via les
        repertoires d'include, sans pour autant remonter toute la STL.
        """
        return self.cfg.get_list("introspection", "root_globs")

    # -- resolution des chemins ---------------------------------------------
    def resolve_headers(self, headers=None) -> List[str]:
        """Liste de headers absolus, dedupliquee, ordre stable.

        Accepte une chaine, une liste, ou rien. Sans argument, prend
        [paths] headers puis, a defaut, [paths] header. Les motifs glob sont
        developpes, y compris ** en recursif.
        """
        if headers is None:
            raw = self.cfg.get_list("paths", "headers")
            if not raw and self.cfg.header:
                raw = [str(self.cfg.header)]
        elif isinstance(headers, str):
            raw = [headers]
        else:
            raw = [str(h) for h in headers]

        if not raw:
            raise IntrospectionError(
                "Aucun header. Renseigne [paths] headers dans scry.ini, "
                "ou passe -H."
            )

        resolved = []
        seen = set()
        for entry in raw:
            for path in self._expand(entry):
                key = _norm(path)
                if key not in seen:
                    seen.add(key)
                    resolved.append(path)

        if not resolved:
            raise IntrospectionError(
                "Aucun fichier ne correspond a : %s" % ", ".join(raw))
        return resolved

    def _expand(self, entry: str) -> List[str]:
        path = entry if os.path.isabs(entry) else os.path.join(str(self.cfg.root), entry)
        if any(ch in entry for ch in "*?["):
            matches = sorted(glob.glob(path, recursive=True))
            if not matches:
                self.report.failures.append((entry, "aucune correspondance"))
            return [os.path.abspath(m) for m in matches if os.path.isfile(m)]
        full = os.path.abspath(path)
        if not os.path.isfile(full):
            raise IntrospectionError("Header introuvable : %s" % full)
        return [full]

    # -- parsing ------------------------------------------------------------
    def parse(self, headers=None) -> List[model.Struct]:
        """Parse un ou plusieurs headers et retourne le modele fusionne."""
        self.report = ParseReport()
        files = self.resolve_headers(headers)

        cache = self._open_cache()
        merged = {}          # nom qualifie -> Struct
        order = []           # noms, pour un ordre de sortie stable

        for full in files:
            try:
                structs = self.parse_one(full, cache)
            except Exception as exc:
                if self.stop_on_error:
                    raise
                self.report.failures.append((full, self._describe_failure(exc)))
                continue

            self.report.parsed.append(full)
            for struct in structs:
                self._merge(merged, order, struct, full)

        if cache is not None:
            cache.flush()

        if not self.report.parsed and self.report.failures:
            raise IntrospectionError(
                "Aucun header n'a pu etre parse :\n  %s"
                % "\n  ".join(self.report.lines(verbose=True)))

        return [merged[name] for name in order]

    @staticmethod
    def _describe_failure(exc: Exception) -> str:
        # Quand castxml echoue, pygccxml ne remonte que l'absence du XML de
        # sortie. Les vraies erreurs de compilation sont deja sur stderr.
        if isinstance(exc, RuntimeError) and "xml file does not exist" in str(exc):
            return "castxml a echoue, voir ses erreurs de compilation ci-dessus"
        return "%s: %s" % (type(exc).__name__, exc)

    def parse_one(self, full: str, cache=None) -> List[model.Struct]:
        """Parse un seul header. Sert aussi de point d'entree pour les tests."""
        decls = self._read_declarations(full, cache)
        global_ns = declarations.get_global_namespace(decls)
        return [self.build_struct(cls) for cls in self._root_classes(global_ns, full)]

    def _open_cache(self):
        """Cache pygccxml, un fichier par configuration de compilateur.

        La signature de cache de pygccxml ignore compiler_path, or c'est par
        lui que passent /std: et [castxml] cl_flags, et elle ignore INCLUDE,
        qui porte la STL du toolset. Sans ce suffixe, passer cl_flags a /MDd
        resservirait le layout release en cache, sans aucun signal.
        """
        cache_file = self.cfg.cache_file
        if not cache_file:
            return None
        # CACHE_FORMAT invalide les caches ecrits avant que les declarations
        # ne portent l'offset de leurs bases.
        key = "|".join((
            CACHE_FORMAT,
            str(getattr(self.xml_config(), "compiler_path", "") or ""),
            os.environ.get("INCLUDE", ""),
        ))
        base, ext = os.path.splitext(str(cache_file))
        path = "%s.%s%s" % (base, hashlib.sha1(key.encode("utf-8")).hexdigest()[:10], ext)
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        return parser.file_cache_t(path)

    def _read_declarations(self, full: str, cache=None):
        """Lit un header sans passer par project_reader_t.

        Voir l'explication en tete de module : la phase de fusion de
        project_reader_t plante sur la STL et ne sert qu'au multi-fichiers,
        que l'on gere nous-memes plus haut. On refait donc les deux etapes
        utiles, jointure des declarations par namespace et liaison des
        typedefs, et on omet la fusion de hierarchie ainsi que la reliaison
        des types declares, qui n'ont d'objet que dans le cas multi-fichiers.
        """
        reader = source_reader.source_reader_t(self.xml_config(), cache, None)
        decls = reader.read_file(full)

        for ns in decls:
            if isinstance(ns, declarations.namespace_t):
                declarations_joiner.join_declarations(ns)
        declarations_joiner.bind_aliases(declarations.make_flatten(decls))
        return decls

    # -- fusion --------------------------------------------------------------
    def _merge(self, merged: Dict[str, model.Struct], order: List[str],
               struct: model.Struct, source: str):
        """Insere une Struct dans le modele fusionne.

        Un meme type vu depuis deux headers doit donner un seul noeud. S'il
        donne deux layouts differents, on garde le premier et on le signale :
        c'est une divergence d'ABI, pas un doublon anodin.
        """
        existing = merged.get(struct.name)
        if existing is None:
            merged[struct.name] = struct
            order.append(struct.name)
            return

        if self._same_layout(existing, struct):
            self.report.duplicates.append(
                "%s, defini dans %s, atteint aussi via %s"
                % (struct.name, os.path.basename(struct.header or ""),
                   os.path.basename(source)))
            return

        self.report.conflicts.append(
            "%s : sizeof=%s via %s, sizeof=%s via %s. "
            "Layouts divergents, le premier est conserve."
            % (struct.name, existing.size, os.path.basename(existing.header or ""),
               struct.size, os.path.basename(struct.header or "")))

    @staticmethod
    def _same_layout(a: model.Struct, b: model.Struct) -> bool:
        if a.size != b.size or a.align != b.align:
            return False
        fa = [(f.name, f.abs_offset, f.size) for f, _ in a.walk()]
        fb = [(f.name, f.abs_offset, f.size) for f, _ in b.walk()]
        return fa == fb

    # -- selection des racines ----------------------------------------------
    def _root_classes(self, global_ns, header_full: str):
        """Classes retenues comme racines pour ce header.

        Sont retenues celles definies dans le header lui-meme, plus celles
        dont le fichier correspond a [introspection] root_globs. Sans ce
        second filtre, les types apportes par les repertoires d'include
        resteraient invisibles ; avec un motif trop large, on remonterait
        toute la STL.
        """
        target = _norm(header_full)
        # normcase des deux cotes : sous Windows il abaisse la casse, ailleurs
        # il est neutre. Melanger normcase et lower() casse la comparaison sur
        # les systemes sensibles a la casse.
        patterns = [os.path.normcase(os.path.abspath(p)) if os.path.isabs(p)
                    else os.path.normcase(p.replace("/", os.sep))
                    for p in self.root_globs]

        out = []
        for cls in global_ns.classes(allow_empty=True):
            loc = getattr(cls, "location", None)
            if loc is None:
                continue
            where = _norm(loc.file_name)
            if where != target and not self._matches(where, patterns):
                continue
            # Ecarter les types imbriques et anonymes : ce sont des enfants,
            # ils seront visites lors de la descente dans leur parent.
            if not isinstance(cls.parent, declarations.namespace_t):
                continue
            if not cls.name:
                continue
            out.append(cls)

        out.sort(key=_qualified_name)
        return out

    @staticmethod
    def _matches(path: str, patterns: Sequence[str]) -> bool:
        for pattern in patterns:
            if fnmatch.fnmatch(path, pattern):
                return True
            # Motif relatif : on teste aussi la fin du chemin, pour que
            # "inc/*.h" attrape D:\proj\inc\truc.h sans chemin absolu.
            if not os.path.isabs(pattern) and fnmatch.fnmatch(
                    path, "*" + os.sep + pattern):
                return True
        return False

    # -- construction du modele ---------------------------------------------
    def build_struct(self, cls) -> model.Struct:
        struct = model.Struct(
            name=_qualified_name(cls),
            kind=str(cls.class_type),
            size=_int_or_none(getattr(cls, "byte_size", None)),
            align=_int_or_none(getattr(cls, "byte_align", None)),
            header=getattr(getattr(cls, "location", None), "file_name", ""),
            is_polymorphic=self._is_polymorphic(cls),
            inline_constructible=self._inline_constructible(cls),
            doc=self._doc(cls),
        )
        struct.fields = self._members(cls, base_offset=0, path="obj",
                                      depth=0, seen=(self._key(cls),))
        return struct

    def _is_polymorphic(self, cls) -> bool:
        """Methode virtuelle propre ou heritee, ou base virtuelle."""
        # Destructeurs et operateurs compris : 'virtual ~T();' suffit a
        # rendre un type polymorphe, et n'est pas un member_function_t.
        for m in cls.declarations:
            if isinstance(m, declarations.calldef_t) and getattr(m, "virtuality", None):
                if str(m.virtuality) != "not virtual":
                    return True
        layout = castxml_bases.base_layout(cls)
        if any(b.is_virtual for b in layout):
            return True
        return any(self._is_polymorphic(b.related_class) for b in getattr(cls, "bases", []))

    def _is_empty(self, cls) -> bool:
        """Classe sans donnee ni vtable : l'optimisation de base vide lui
        donne 0 octet dans la classe derivee, malgre son sizeof de 1."""
        if self._is_polymorphic(cls):
            return False
        if any(not getattr(v.type_qualifiers, "has_static", False)
               for v in cls.variables(allow_empty=True, recursive=False)):
            return False
        return all(self._is_empty(b.related_class) for b in getattr(cls, "bases", []))

    @property
    def include_bases(self) -> bool:
        return self.cfg.get_bool("introspection", "include_bases", True)

    def _bases(self, cls, base_offset: int, path: str, depth: int,
               seen: Tuple[str, ...]) -> List[model.Field]:
        """Un Field de nature BASE par classe de base, ses membres en enfants.

        Les membres herites s'atteignent par le meme chemin que ceux de la
        classe derivee : access_path reste celui du parent pour les enfants.
        Une base vide est omise, elle n'occupe aucun octet. Une base
        virtuelle n'a pas d'offset constant : elle est signalee sans etre
        placee.
        """
        infos = list(getattr(cls, "bases", []) or [])
        if not infos or not self.include_bases:
            return []
        layout = castxml_bases.base_layout(cls)
        out = []
        for i, info in enumerate(infos):
            decl = info.related_class
            access = str(info.access_type) if info.access_type else "public"
            if access != "public" and not self.cfg.include_non_public:
                continue
            if not isinstance(decl, declarations.class_t) or self._is_empty(decl):
                continue
            where = layout[i] if layout else None
            fld = model.Field(
                name="",
                type_name=_qualified_name(decl),
                kind=model.BASE,
                access_path="static_cast<const %s&>(%s)" % (_qualified_name(decl), path),
                size=_int_or_none(getattr(decl, "byte_size", None)),
                access=access,
                is_polymorphic=self._is_polymorphic(decl),
            )
            if where is None or where.is_virtual or where.offset is None:
                fld.truncated = "virtual" if where is not None and where.is_virtual else "offset"
                fld.size = None
                out.append(fld)
                continue
            fld.offset = where.offset
            fld.abs_offset = base_offset + where.offset
            key = self._key(decl)
            if key in seen:
                fld.truncated = "cycle"
            elif depth + 1 >= self.cfg.max_depth:
                fld.truncated = "depth"
            else:
                fld.children = self._members(decl, base_offset=fld.abs_offset, path=path,
                                             depth=depth + 1, seen=seen + (key,))
            out.append(fld)
        return out

    def _inline_constructible(self, cls, seen: Tuple[str, ...] = ()) -> bool:
        """Construire cls par defaut ne demande-t-il que du code du header ?

        Un constructeur declare dans la classe sans corps, 'Foo();', est
        defini dans la bibliotheque du tiers : l'appeler depuis le visualiseur
        echouerait a l'edition des liens. castxml marque inline les
        constructeurs implicites, '= default' et definis dans la classe.
        Recursif sur les bases et les membres, tableaux compris : un
        std::array ou un std::pair d'un tel type l'appelle aussi, pas un
        std::vector, qui ne construit rien. Une definition inline placee apres
        la classe n'est pas vue : le resultat est alors prudent, pas faux.
        """
        key = self._key(cls)
        if key in seen:
            return True
        cache = self.__dict__.setdefault("_ctor_cache", {})
        if key in cache:
            return cache[key]
        seen = seen + (key,)

        ok = True
        try:
            ctors = cls.constructors(allow_empty=True, recursive=False)
        except Exception:
            ctors = []
        for ct in ctors:
            if not ct.required_args and not ct.is_artificial and not ct.has_inline:
                ok = False
        # L'instance est statique : son destructeur est appele a la sortie. Et
        # une methode virtuelle definie hors du header porte la vtable dans la
        # bibliotheque du tiers : la construire demanderait ce symbole.
        for m in cls.declarations:
            if not isinstance(m, declarations.calldef_t) or m.is_artificial or m.has_inline:
                continue
            virtuality = str(getattr(m, "virtuality", "not virtual"))
            if isinstance(m, declarations.destructor_t) or virtuality == "virtual":
                ok = False
        if ok:
            for base in getattr(cls, "bases", []):
                if not self._inline_constructible(base.related_class, seen):
                    ok = False
                    break
        if ok:
            for var in cls.variables(allow_empty=True, recursive=False):
                if getattr(var.type_qualifiers, "has_static", False):
                    continue
                t = declarations.remove_cv(declarations.remove_alias(var.decl_type))
                while declarations.is_array(t):
                    t = declarations.remove_cv(declarations.remove_alias(
                        declarations.array_item_type(t)))
                # is_class() repond vrai sur un pointeur vers une classe : un
                # pointeur ne construit rien, il faut l'ecarter d'abord.
                if declarations.is_pointer(t) or declarations.is_reference(t) \
                        or not declarations.is_class(t):
                    continue
                if not self._inline_constructible(
                        declarations.class_traits.get_declaration(t), seen):
                    ok = False
                    break
        cache[key] = ok
        return ok

    def _key(self, decl) -> str:
        # decl_string d'un type anonyme renvoie le nom du parent : deux types
        # anonymes distincts partageraient la meme cle et le garde-fou
        # anti-cycle les couperait a tort.
        if not getattr(decl, "name", ""):
            return "anonyme@%d" % id(decl)
        try:
            return decl.decl_string
        except Exception:
            return "%s@%d" % (decl.name, id(decl))

    def _members(self, cls, base_offset: int, path: str, depth: int,
                 seen: Tuple[str, ...]) -> List[model.Field]:
        fields = self._bases(cls, base_offset, path, depth, seen)
        try:
            variables = cls.variables(allow_empty=True, recursive=False)
        except Exception:
            return fields

        for var in variables:
            is_static = bool(getattr(var.type_qualifiers, "has_static", False))
            if is_static and not self.cfg.include_static:
                continue
            access = getattr(var, "access_type", None)
            access = str(access) if access is not None else "public"
            if access != "public" and not self.cfg.include_non_public:
                continue
            fld = self._build_field(var, base_offset, path, depth, seen, is_static)
            fld.access = access
            fields.append(fld)
        return fields

    def _build_field(self, var, base_offset: int, path: str, depth: int,
                     seen: Tuple[str, ...], is_static: bool) -> model.Field:
        raw_offset = 0.0 if is_static else float(getattr(var, "byte_offset", 0.0) or 0.0)
        byte_offset = int(raw_offset)
        bit_width = getattr(var, "bits", None)
        bit_offset = None
        if bit_width is not None:
            total_bits = int(round(raw_offset * 8))
            byte_offset = total_bits // 8
            bit_offset = total_bits % 8

        access_path = "%s.%s" % (path, var.name) if var.name else path

        fld = model.Field(
            name=var.name,
            type_name=var.decl_type.decl_string,
            kind=model.UNKNOWN,
            offset=byte_offset,
            abs_offset=base_offset + byte_offset,
            access_path=access_path,
            bit_width=bit_width,
            bit_offset=bit_offset,
            is_static=is_static,
            doc=self._doc(var),
        )
        self._describe_type(fld, var.decl_type, depth, seen)
        return fld

    def _describe_type(self, fld: model.Field, decl_type, depth: int, seen: Tuple[str, ...]):
        """Renseigne kind, size et enfants a partir du type pygccxml."""
        # remove_alias reconstruit le type et perd byte_size : on lit la taille
        # sur le type d'origine d'abord, puis sur le type resolu en secours.
        size = _int_or_none(getattr(decl_type, "byte_size", None))

        t = declarations.remove_alias(decl_type)
        if declarations.is_const(t) or declarations.is_volatile(t):
            fld.is_const = declarations.is_const(t)
            t = declarations.remove_cv(t)

        if not size:
            size = _int_or_none(getattr(t, "byte_size", None))
        fld.size = size if size else None

        # --- tableau --------------------------------------------------------
        if declarations.is_array(t):
            item = declarations.array_item_type(t)
            length = _int_or_none(declarations.array_size(t))
            fld.kind = model.ARRAY
            fld.array_len = length
            fld.elem_type = item.decl_string
            item_size = self._sizeof(item)
            if item_size is not None and length is not None:
                fld.size = item_size * length
            # On ne deplie pas les elements : un char[50] ferait 50 noeuds.
            sub = model.Field(
                name="[]",
                type_name=item.decl_string,
                kind=model.UNKNOWN,
                offset=0,
                abs_offset=fld.abs_offset,
                access_path="%s[0]" % fld.access_path,
            )
            self._describe_type(sub, item, depth + 1, seen)
            if sub.kind in model.AGGREGATES and sub.children:
                fld.children = [sub]
            else:
                fld.elem_type = sub.type_name
            return

        # --- pointeur -------------------------------------------------------
        if declarations.is_pointer(t) or declarations.is_reference(t):
            fld.kind = model.POINTER
            fld.size = size or None
            if not self.cfg.follow_pointers:
                fld.truncated = "pointer"
                return
            pointee = declarations.remove_reference(declarations.remove_pointer(t))
            pointee = declarations.remove_cv(declarations.remove_alias(pointee))
            if declarations.is_class(pointee):
                self._descend_class(fld, pointee, depth, seen)
            return

        # --- enum -----------------------------------------------------------
        if declarations.is_enum(t):
            fld.kind = model.ENUM
            try:
                enum_decl = declarations.enum_declaration(t)
                fld.enum_values = [name for name, _ in enum_decl.values]
                fld.type_name = enum_decl.name or fld.type_name
            except Exception:
                pass
            return

        # --- classe, struct, union -------------------------------------------
        if declarations.is_class(t) or declarations.is_class_declaration(t):
            self._descend_class(fld, t, depth, seen)
            return

        # --- fondamental ------------------------------------------------------
        if declarations.is_fundamental(t):
            fld.kind = model.FUNDAMENTAL
            return

        fld.kind = model.UNKNOWN

    def _descend_class(self, fld: model.Field, t, depth: int, seen: Tuple[str, ...]):
        try:
            decl = declarations.class_traits.get_declaration(t)
        except Exception:
            try:
                decl = declarations.class_declaration_traits.get_declaration(t)
            except Exception:
                fld.kind = model.CLASS
                fld.truncated = "opaque"
                return

        # Type incomplet : declare mais jamais defini.
        if not isinstance(decl, declarations.class_t):
            fld.kind = model.CLASS
            fld.truncated = "opaque"
            return

        fld.kind = str(decl.class_type)
        fld.is_polymorphic = self._is_polymorphic(decl)
        fld.is_anonymous = not decl.name
        if fld.is_anonymous:
            fld.type_name = "<%s anonyme>" % fld.kind
        else:
            fld.type_name = decl.name
        fld.size = _int_or_none(getattr(decl, "byte_size", None)) or fld.size

        key = self._key(decl)
        if key in seen:
            fld.truncated = "cycle"
            return
        if depth + 1 >= self.cfg.max_depth:
            fld.truncated = "depth"
            return

        fld.children = self._members(
            decl,
            base_offset=fld.abs_offset,
            path=fld.access_path,
            depth=depth + 1,
            seen=seen + (key,),
        )

    def _sizeof(self, t) -> Optional[int]:
        direct = _int_or_none(getattr(t, "byte_size", None))
        if direct:
            return direct
        t = declarations.remove_cv(declarations.remove_alias(t))
        size = _int_or_none(getattr(t, "byte_size", None))
        if size:
            return size
        if declarations.is_array(t):
            item = self._sizeof(declarations.array_item_type(t))
            length = _int_or_none(declarations.array_size(t))
            if item is not None and length is not None:
                return item * length
            return None
        if declarations.is_class(t):
            try:
                return _int_or_none(declarations.class_traits.get_declaration(t).byte_size)
            except Exception:
                return None
        return None


# ---------------------------------------------------------------------------
# API de commodite
# ---------------------------------------------------------------------------
def parse_header(headers=None, cfg: Optional[Config] = None) -> List[model.Struct]:
    return Introspector(cfg).parse(headers)


def index_by_name(structs: Iterable[model.Struct]) -> Dict[str, model.Struct]:
    return dict((s.name, s) for s in structs)
