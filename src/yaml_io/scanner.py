"""A PyYAML scanner that understands dotted aliases such as ``*base.anchor1``.

This is a ``Scanner`` *subclass*, not a monkey-patch. Only loaders that mix it
in accept the extended grammar; plain PyYAML keeps rejecting dotted aliases.
"""

from yaml.scanner import Scanner, ScannerError

# Characters PyYAML allows to follow an anchor or alias name. Identical to the
# set in yaml.scanner.Scanner.scan_anchor. Two of them are invisible Unicode
# line separators, so they are spelled with chr() rather than embedded raw.
_LINE_SEP = chr(0x2028)
_PARA_SEP = chr(0x2029)
_NAME_END = "\0 \t\r\n\x85" + _LINE_SEP + _PARA_SEP + "?:,]}%@`"


def _is_name_char(ch: str) -> bool:
    return (
        "0" <= ch <= "9"
        or "A" <= ch <= "Z"
        or "a" <= ch <= "z"
        or ch in "-_"
    )


class DottedAliasScanner(Scanner):
    """Extends alias names with a single ``.`` separator.

    Anchor definitions (``&name``) keep PyYAML's grammar exactly: alphanumerics,
    ``-`` and ``_``. Only alias references (``*prefix.name``) may contain one
    dot, and it may be neither leading nor trailing. Restricting dots to aliases
    is what keeps a local anchor name from ever colliding with an imported one,
    since imported keys always contain a dot and local keys never do.
    """

    def scan_anchor(self, TokenClass):
        start_mark = self.get_mark()
        indicator = self.peek()
        is_alias = indicator == "*"
        name = "alias" if is_alias else "anchor"
        self.forward()

        length = 0
        dots = 0
        ch = self.peek(length)
        while True:
            if _is_name_char(ch):
                length += 1
            elif ch == "." and is_alias and dots == 0 and length > 0:
                dots += 1
                length += 1
            else:
                break
            ch = self.peek(length)

        if not length:
            raise ScannerError(
                "while scanning an %s" % name,
                start_mark,
                "expected alphabetic or numeric character, but found %r" % ch,
                self.get_mark(),
            )

        value = self.prefix(length)
        self.forward(length)

        # PyYAML validates the character that terminates the name; keeping this
        # check is what stops malformed anchors from being silently accepted.
        ch = self.peek()
        if ch not in _NAME_END:
            raise ScannerError(
                "while scanning an %s" % name,
                start_mark,
                "expected alphabetic or numeric character, but found %r" % ch,
                self.get_mark(),
            )

        if value.endswith("."):
            raise ScannerError(
                "while scanning an %s" % name,
                start_mark,
                "expected a name after '.', but found %r" % ch,
                self.get_mark(),
            )

        return TokenClass(value, start_mark, self.get_mark())


__all__ = ["DottedAliasScanner"]
