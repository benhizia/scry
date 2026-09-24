#pragma once
// Heritage : bases simples, multiples, vides, polymorphes et virtuelles.
// Ajoute par Scry. Les offsets des bases viennent des elements <Base> de
// castxml, que pygccxml ne lit pas (voir scry/parsing/castxml_bases.py).

struct Empty {};

struct A { int a; double d; };
struct B { char b; };

// Heritage multiple : B est place apres A, a l'offset 16.
struct Multi : A, B { int m; };

// Base vide : 0 octet dans la derivee, malgre son sizeof de 1.
struct WithEmpty : Empty { int w; };

// Seul le destructeur est virtuel : le type est polymorphe quand meme. Il est
// defini hors du header, donc la vtable aussi : pas d'instance constructible.
struct Poly { virtual ~Poly(); int p; };
struct Derived : Poly { int x; };

// Polymorphe entierement inline : constructible.
struct InlinePoly { virtual ~InlinePoly() {} virtual int f() { return 1; } int q; };
struct FromInline : InlinePoly { int y; };

// Base virtuelle : offset dependant du type le plus derive.
struct VBase { int v; };
struct V1 : virtual VBase { int v1; };
struct Diamond : V1 { int dd; };

// Base d'une base, et nom masque : 'a' de la derivee cache celui de A.
struct Level2 : Multi { int l2; };
struct Shadow : A { int a; };

// Heritage non public : membres de la base inaccessibles par le nom.
struct PrivateBase : private A { int pb; };
