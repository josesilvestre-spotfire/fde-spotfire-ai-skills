"""Python 3.4 literals with short lines for the HOME, STYLE and APP blocks of a standard-engine builder.

    literal("STYLE", value) -> 'STYLE = {...}' (lines <= 79, ASCII, double-quoted strings)
    home_literal(path)      -> 'HOME = r"..."' (raw string pieces when the path is long)

Layout, close to a hand-written builder: a value that fits stays on one line; the top-level
dict has one key per line; a container that starts near the left margin keeps its first item on
the bracket's line and aligns the rest under it; one that starts further right opens a block
indented four spaces; [scalar, ..., container] pairs hug the container ("["NAME", {" ... "}],");
long strings become implicit concatenations in parentheses. ast.literal_eval of the result must give
the value back, or ValueError is raised.
"""
import ast

LIMIT = 79
STEP = 4
ALIGN_MAX = 36           # align under the bracket only when it opens at or left of this column


def _quote(text):
    out = ['"']
    for ch in text:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif o < 32 or o == 127:
            out.append("\\x%02x" % o)
        elif o > 0xFFFF:
            out.append("\\U%08x" % o)
        elif o > 126:
            out.append("\\u%04x" % o)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def flat(obj):
    if isinstance(obj, str):
        return _quote(obj)
    if obj is None or isinstance(obj, bool):
        return repr(obj)
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        text = repr(obj)
        if text in ("nan", "inf", "-inf"):
            raise ValueError("%s has no Python 3.4 literal" % text)
        return text
    if isinstance(obj, dict):
        return "{" + ", ".join(_quote(k) + ": " + flat(v) for k, v in obj.items()) + "}"
    if isinstance(obj, (list, tuple)):
        return "[" + ", ".join(flat(v) for v in obj) + "]"
    raise TypeError("not a literal value: %r" % (obj,))


def _indent_of(text):
    return len(text) - len(text.lstrip(" "))


def _split_string(text, first_room, room):
    """Chunks of text whose quoted forms fit first_room (first chunk) and room (the others); breaks
    after spaces where possible."""
    chunks = []
    rest = text
    width = first_room
    while rest:
        if len(_quote(rest)) <= width:
            chunks.append(rest)
            break
        cut = 0
        best_space = 0
        for i in range(1, len(rest) + 1):
            if len(_quote(rest[:i])) > width:
                break
            cut = i
            if rest[i - 1] == " ":
                best_space = i
        if cut == 0:
            raise ValueError("cannot fit a string piece in %d characters" % width)
        if best_space > cut // 3:
            cut = best_space
        chunks.append(rest[:cut])
        rest = rest[cut:]
        width = room
    return chunks or [""]


def _lay_string(text, head, tail):
    """("piece one "
        "piece two") - aligned after the parenthesis, or a block under it when head is long."""
    close = len(")" + tail)
    if len(head) <= 44:
        lead = " " * (len(head) + 1)
        chunks = _split_string(text, LIMIT - len(head) - 1, LIMIT - len(lead) - close)
        lines = [head + "(" + _quote(chunks[0])]
    else:
        lead = " " * (_indent_of(head) + STEP)
        chunks = _split_string(text, LIMIT - len(lead), LIMIT - len(lead) - close)
        lines = [head + "(", lead + _quote(chunks[0])]
    for c in chunks[1:]:
        lines.append(lead + _quote(c))
    if len(lines[-1]) + close > LIMIT:
        lines.append(lead + ")" + tail)
    else:
        lines[-1] += ")" + tail
    return lines


def _items(obj):
    if isinstance(obj, dict):
        return "{", "}", [(_quote(k) + ": ", v) for k, v in obj.items()]
    return "[", "]", [("", v) for v in obj]


def _is_container(obj):
    return isinstance(obj, (dict, list, tuple)) and len(obj) > 0


def _lay(obj, head, tail, pack=True, top=False):
    """Lines that render head + literal(obj) + tail."""
    one = head + flat(obj) + tail
    if len(one) <= LIMIT:
        return [one]
    if isinstance(obj, str):
        return _lay_string(obj, head, tail)
    if not _is_container(obj):
        raise ValueError("cannot fit %s in %d characters" % (one.strip()[:60], LIMIT))
    opener, closer, items = _items(obj)
    # [scalar, ..., container]: hug the container ("NAME", {  ...  }),
    if (isinstance(obj, (list, tuple)) and len(obj) > 1 and _is_container(obj[-1])
            and not any(_is_container(x) for x in obj[:-1])):
        start = head + opener + "".join(flat(x) + ", " for x in obj[:-1])
        if len(start) + 2 <= LIMIT:
            # the block of the hugged container is indented from the list's bracket
            return _lay_block(obj[-1], start, closer + tail, min(len(head), LIMIT - 40))
    if top:
        return _lay_block(obj, head, tail, _indent_of(head), pack=False, own_closer=True)
    if len(head) + 1 > ALIGN_MAX:
        return _lay_block(obj, head, tail, _indent_of(head), pack=pack)
    return _lay_aligned(obj, head, tail)


def _lay_aligned(obj, head, tail):
    """First item on the bracket's line, the others aligned under it, packed while they fit."""
    opener, closer, items = _items(obj)
    lead = " " * (len(head) + 1)
    lines = [head + opener]
    fresh = True                                   # the last line ends with the opener
    prev_multi = False
    for n, (prefix, value) in enumerate(items):
        end = (closer + tail) if n == len(items) - 1 else ","
        one = prefix + flat(value) + end
        gap = "" if fresh else " "
        multi = False
        if not prev_multi and len(lines[-1]) + len(gap) + len(one) <= LIMIT:
            lines[-1] += gap + one
        elif len(lead) + len(one) <= LIMIT:
            lines.append(lead + one)
        elif fresh:
            sub = _lay(value, lines[-1] + prefix, end)
            lines[-1:] = sub
            multi = len(sub) > 1
        else:
            sub = _lay(value, lead + prefix, end)
            lines.extend(sub)
            multi = len(sub) > 1
        fresh = False
        prev_multi = multi
    return lines


def _lay_block(obj, head, tail, indent, pack=True, own_closer=False):
    """Opener at the end of the first line, items indented one step (packed while they fit), the
    closer after the last item (or on its own line for the top-level dict)."""
    opener, closer, items = _items(obj)
    lead = " " * (indent + STEP)
    lines = [head + opener]
    prev_multi = True                              # the first item starts a fresh line
    for n, (prefix, value) in enumerate(items):
        last = n == len(items) - 1
        end = (closer + tail) if (last and not own_closer) else ","
        one = prefix + flat(value) + end
        multi = False
        if pack and not prev_multi and len(lines[-1]) + 1 + len(one) <= LIMIT:
            lines[-1] += " " + one
        elif len(lead) + len(one) <= LIMIT:
            lines.append(lead + one)
        else:
            sub = _lay(value, lead + prefix, end)
            lines.extend(sub)
            multi = len(sub) > 1
        prev_multi = multi
    if own_closer:
        lines.append(" " * indent + closer + tail)
    return lines


def literal(name, value):
    """'name = <value>' with every line <= LIMIT; raises ValueError when it does not round-trip."""
    text = "\n".join(_lay(value, name + " = ", "", pack=False, top=isinstance(value, dict)))
    bad = [line for line in text.split("\n") if len(line) > LIMIT or not line.isascii()]
    if bad:
        raise ValueError("literal line too long or not ASCII: %s" % bad[0][:60])
    if ast.literal_eval(text[len(name) + 3:]) != _plain(value):
        raise ValueError("the %s literal does not round-trip" % name)
    return text


def dense(name, value, indent="    ", more="      "):
    """'name = {...}' for a dict: one top-level key per line (a list of containers: one element per
    line) and each value packed into lines of at most LIMIT; continuation lines start with `more`,
    long strings become adjacent literals, which Python joins inside the brackets. About 40 % smaller
    than literal() for big APP blocks; the standard engine uses it when the app uses a feature part
    (t3.assemble)."""
    lines = [name + " = {"]
    for key, item in value.items():
        head = _quote(key) + ": "
        if isinstance(item, list) and len(item) > 1 and any(_is_container(x) for x in item):
            lines.append(indent + head + "[")
            for n, x in enumerate(item):
                lines.extend(_flow(flat(x) + ("," if n < len(item) - 1 else "],"), more, more))
        else:
            lines.extend(_flow(head + flat(item) + ",", indent, more))
    lines.append("}")
    text = "\n".join(lines)
    bad = [line for line in lines if len(line) > LIMIT or not line.isascii()]
    if bad:
        raise ValueError("literal line too long or not ASCII: %s" % bad[0][:60])
    if ast.literal_eval(text[len(name) + 3:]) != _plain(value):
        raise ValueError("the %s literal does not round-trip" % name)
    return text


_GLUED = (",", ":", "]", "}")


def _flow(text, indent, more):
    """Wrap one flat literal at token boundaries; commas, colons and closing brackets stay on the
    line of the token before them."""
    import io
    import tokenize
    toks = [t for t in tokenize.generate_tokens(io.StringIO(text).readline)
            if t.type not in (tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER)]
    tails = [0] * len(toks)                      # length of the glued tokens after each token
    for i in range(len(toks) - 2, -1, -1):
        nxt = toks[i + 1].string
        tails[i] = len(nxt) + tails[i + 1] if nxt in _GLUED else 0
    lines = []
    cur = indent
    prev = None
    for i, tok in enumerate(toks):
        s = tok.string
        space = " " if prev in (",", ":") else ""
        need = len(space) + len(s) + (0 if s in _GLUED else tails[i])
        if len(cur) + need <= LIMIT or (s in _GLUED and len(cur) + len(s) <= LIMIT):
            cur += space + s
        elif tok.type == tokenize.STRING and len(more) + len(s) + tails[i] > LIMIT:
            room = LIMIT - len(cur) - len(space)
            last = LIMIT - len(more) - tails[i]
            value = ast.literal_eval(s)
            if room >= 12:
                chunks = _split_string(value, room, last)
                cur += space + _quote(chunks[0])
            else:
                chunks = [""] + _split_string(value, last, last)
            for c in chunks[1:]:
                lines.append(cur)
                cur = more + _quote(c)
        else:
            lines.append(cur)
            cur = more + s
        prev = s
    lines.append(cur)
    return lines


def _plain(value):
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return dict((k, _plain(v)) for k, v in value.items())
    return value


def home_literal(path, name="HOME"):
    """HOME = r"C:\\...": raw-string pieces split at backslashes so every line fits."""
    text = str(path)
    if '"' in text or text.endswith("\\") or not text.isascii() or "\n" in text:
        return literal(name, text)
    one = '%s = r"%s"' % (name, text)
    if len(one) <= LIMIT:
        return one
    head = name + " = ("
    lead = " " * len(head)
    parts = []
    rest = text
    room = LIMIT - len(head) - 3
    while rest:
        if len(rest) <= room:
            parts.append(rest)
            break
        cut = rest.rfind("\\", 1, room)
        if cut <= 0:
            return literal(name, text)
        parts.append(rest[:cut])
        rest = rest[cut:]
        room = LIMIT - len(lead) - 3
    lines = [head + 'r"' + parts[0] + '"'] + [lead + 'r"' + p + '"' for p in parts[1:]]
    lines[-1] += ")"
    out = "\n".join(lines)
    if ast.literal_eval(out[len(name) + 3:]) != text:
        return literal(name, text)
    return out
