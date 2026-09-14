"""Verifications lisibles.

    expect(x, "altitude").near(1200, tol=5)   # bloquante : leve et arrete le scenario
    check(x, "altitude").near(1200, tol=5)    # non bloquante : note l'echec et continue

Le message dit la valeur obtenue et l'attendu, pas seulement 'assert failed' :
dans un rapport d'autotest, c'est tout ce qu'on a pour comprendre.
"""


class ExpectationError(AssertionError):
    pass


def _fmt(value) -> str:
    name = getattr(value, "name", None)
    if isinstance(name, str) and hasattr(type(value), "__members__"):
        return name                                # enum pybind11
    if isinstance(value, float):
        return "%.6g" % value
    return repr(value)


class Expectation(object):
    def __init__(self, value, label=None, soft=False):
        self.value = value
        self.label = label or "valeur"
        self.soft = soft

    def _check(self, ok: bool, expected: str) -> "Expectation":
        if ok:
            return self
        message = "%s = %s, attendu %s" % (self.label, _fmt(self.value), expected)
        if self.soft:
            from autotest import runner
            if runner._ACTIVE is None:
                raise ExpectationError(message)
            runner._ACTIVE._soft_failure(message)
            return self
        raise ExpectationError(message)

    def eq(self, other):
        return self._check(self.value == other, _fmt(other))

    def ne(self, other):
        return self._check(self.value != other, "different de %s" % _fmt(other))

    def lt(self, other):
        return self._check(self.value < other, "< %s" % _fmt(other))

    def le(self, other):
        return self._check(self.value <= other, "<= %s" % _fmt(other))

    def gt(self, other):
        return self._check(self.value > other, "> %s" % _fmt(other))

    def ge(self, other):
        return self._check(self.value >= other, ">= %s" % _fmt(other))

    def between(self, low, high):
        return self._check(low <= self.value <= high, "dans [%s, %s]" % (_fmt(low), _fmt(high)))

    def near(self, target, tol=None, rel=None):
        """|valeur - cible| <= max(tol, rel * |cible|). Sans tolerance : 1e-9."""
        allowed = max(tol or 0.0, (rel or 0.0) * abs(target))
        if tol is None and rel is None:
            allowed = 1e-9
        return self._check(abs(self.value - target) <= allowed,
                           "%s +/- %s" % (_fmt(target), _fmt(float(allowed))))

    def true(self):
        return self._check(bool(self.value), "vrai")

    def false(self):
        return self._check(not self.value, "faux")

    def one_of(self, *values):
        return self._check(self.value in values, "parmi %s" % ", ".join(_fmt(v) for v in values))

    def satisfies(self, predicate, description="le predicat"):
        return self._check(bool(predicate(self.value)), "satisfaisant %s" % description)


def expect(value, label=None) -> Expectation:
    """Verification bloquante : un echec arrete le scenario."""
    return Expectation(value, label)


def check(value, label=None) -> Expectation:
    """Verification non bloquante : l'echec est note, le scenario continue, et
    il finira en echec."""
    return Expectation(value, label, soft=True)
