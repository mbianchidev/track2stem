from importlib.util import find_spec

hiddenimports = [
    name for name in ("scipy.special._ufuncs_cxx", "scipy.special._special_ufuncs", "scipy.special._cdflib")
    if find_spec(name) is not None
]
