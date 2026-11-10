from PyInstaller.utils.hooks import is_module_satisfies

# Pycparser 3 replaced PLY and no longer has generated lexer/parser table modules.
hiddenimports = [] if is_module_satisfies("pycparser >= 3") else ["pycparser.lextab", "pycparser.yacctab"]
