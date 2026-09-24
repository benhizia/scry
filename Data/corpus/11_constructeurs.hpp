#pragma once
// Constructeurs par defaut definis dans le header ou hors du header.
// Ajoute par Scry : le visualiseur natif ne doit construire que les types dont
// aucun constructeur par defaut (classe, bases, membres) n'est defini ailleurs,
// sans quoi il ne se lierait pas sans la bibliotheque du tiers.
#include <string>
#include <vector>

struct Implicit { int a = 1; std::string s; };
struct Defaulted { Defaulted() = default; int a; };
struct InClass { InClass() : a(2) {} int a; };
struct OutOfLine { OutOfLine(); int a; };
struct InlineLater { InlineLater(); int a; };
inline InlineLater::InlineLater() : a(3) {}
struct HasBadMember { int x; OutOfLine m; };
struct HasBadBase : OutOfLine { int y; };
struct HasBadArray { OutOfLine arr[2]; };
struct NoDefault { NoDefault(int); int a; };
struct VecOfBad { std::vector<OutOfLine> v; };
