"""deskctl.py: drive Windows desktop apps for UI tests: windows, window-only
screenshots, clicks, drags, typing and keys.

Commands (python deskctl.py <command> ...):
  wins [filter]                     list visible windows: hwnd pid exe title rect
  spotfire <analysis.dxp>           start a NEW Analyst process on the file;
                                    prints "pid hwnd" once its main window shows
  browser <url>                     open a new Chrome (or Edge) window; prints hwnd
  place <hwnd> <x> <y> <w> <h>      move and size a window (restores it first)
  focus <hwnd>                      bring a window to the front
  shot <hwnd> <out.png>             capture ONE window with PrintWindow
  click|dclick|rclick <hwnd> <x> <y>
  drag <hwnd> <x1> <y1> <x2> <y2>   press, move, release (marks a rectangle)
  wheel <hwnd> <x> <y> <clicks>     mouse wheel, positive = up
  type <hwnd> <text>                type text into the focused control
  keys <hwnd> <spec>                chords: "ctrl+a" "enter" "esc" "ctrl+shift+s"
  clip <file>                       put the text of a file on the clipboard
  close <pid>                       end a process this tool started (spotfire)
  selftest [folder]                 click and type into assets/selftest.html

Coordinates are window coordinates in physical pixels: pixel (x, y) of a
"shot" image is the same (x, y) for click, drag and wheel.

Input commands (click, dclick, rclick, drag, wheel, type, keys, selftest)
send real mouse and keyboard input. Inside a sandboxed shell Windows drops
that input without an error, so they must run unsandboxed. wins, spotfire,
browser, place and shot work in the sandbox. Windows only, standard library
only.
"""
import ctypes
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from ctypes import wintypes

if os.name != "nt":
    sys.exit("deskctl needs Windows")

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    ctypes.windll.user32.SetProcessDPIAware()

U = ctypes.windll.user32
G = ctypes.windll.gdi32
K = ctypes.windll.kernel32
HERE = os.path.dirname(os.path.abspath(__file__))
STARTED = os.path.join(tempfile.gettempdir(), "deskctl-started.json")


# ---------------------------------------------------------------- windows
def _title(hwnd):
    length = U.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    U.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _pid(hwnd):
    pid = wintypes.DWORD()
    U.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def rect(hwnd):
    r = wintypes.RECT()
    U.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def exe_name(pid):
    handle = K.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(260)
        if K.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        K.CloseHandle(handle)


def windows(text=None, pid=None):
    found = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _param):
        if U.IsWindowVisible(hwnd):
            title = _title(hwnd)
            owner = _pid(hwnd)
            if title and (pid is None or owner == pid):
                item = {"hwnd": hwnd, "pid": owner, "title": title,
                        "rect": rect(hwnd), "exe": exe_name(owner)}
                line = (item["exe"] + " " + title).lower()
                if text is None or text.lower() in line:
                    found.append(item)
        return True

    U.EnumWindows(proc(callback), 0)
    return found


def place(hwnd, x, y, w, h):
    U.ShowWindow(hwnd, 9)
    U.MoveWindow(hwnd, int(x), int(y), int(w), int(h), True)
    time.sleep(0.3)


def front(hwnd):
    """Bring hwnd to the front without sending keystrokes."""
    if U.GetForegroundWindow() == hwnd:
        return True
    if U.IsIconic(hwnd):
        U.ShowWindow(hwnd, 9)
    me = K.GetCurrentThreadId()
    other = U.GetWindowThreadProcessId(U.GetForegroundWindow(), None)
    U.AttachThreadInput(me, other, True)
    U.SetForegroundWindow(hwnd)
    U.BringWindowToTop(hwnd)
    U.AttachThreadInput(me, other, False)
    time.sleep(0.25)
    return U.GetForegroundWindow() == hwnd


# ---------------------------------------------------------------- capture
class _BIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def write_png(path, width, height, bgrx):
    """Write top-down 32-bit BGRX pixels as an 8-bit RGB PNG."""
    rgb = bytearray(width * height * 3)
    rgb[0::3] = bgrx[2::4]
    rgb[1::3] = bgrx[1::4]
    rgb[2::3] = bgrx[0::4]
    stride = width * 3
    raw = bytearray()
    for row in range(height):
        raw.append(0)
        raw += rgb[row * stride:(row + 1) * stride]

    def chunk(kind, data):
        body = kind + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                     + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
                     + chunk(b"IEND", b""))


def shot(hwnd, out):
    """PrintWindow with PW_RENDERFULLCONTENT: the image holds this window
    only, even when other windows overlap it."""
    if U.IsIconic(hwnd):
        U.ShowWindow(hwnd, 9)
        time.sleep(0.4)
    left, top, right, bottom = rect(hwnd)
    width, height = right - left, bottom - top
    hdc = U.GetWindowDC(hwnd)
    mdc = G.CreateCompatibleDC(hdc)
    bmp = G.CreateCompatibleBitmap(hdc, width, height)
    G.SelectObject(mdc, bmp)
    U.PrintWindow(hwnd, mdc, 2)
    info = _BIH(ctypes.sizeof(_BIH), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(width * height * 4)
    G.GetDIBits(mdc, bmp, 0, height, buf, ctypes.byref(info), 0)
    G.DeleteObject(bmp)
    G.DeleteDC(mdc)
    U.ReleaseDC(hwnd, hdc)
    write_png(out, width, height, buf.raw)
    return out, (width, height)


# ---------------------------------------------------------------- input
class _MI(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _KI(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _HI(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _IU(ctypes.Union):
    _fields_ = [("mi", _MI), ("ki", _KI), ("hi", _HI)]


class _IN(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _IU)]


def _send(*inputs):
    arr = (_IN * len(inputs))(*inputs)
    U.SendInput(len(inputs), arr, ctypes.sizeof(_IN))


def _mouse(flags, data=0):
    item = _IN()
    item.type = 0
    item.u.mi = _MI(0, 0, data, flags, 0, None)
    return item


def _to_screen(hwnd, x, y):
    left, top, _r, _b = rect(hwnd)
    return left + int(x), top + int(y)


def move(hwnd, x, y):
    U.SetCursorPos(*_to_screen(hwnd, x, y))
    time.sleep(0.05)


def click(hwnd, x, y, button="left", double=False):
    if not front(hwnd):
        raise SystemExit("window %s did not come to the front" % hwnd)
    move(hwnd, x, y)
    down, up = (0x0002, 0x0004) if button == "left" else (0x0008, 0x0010)
    for _ in range(2 if double else 1):
        _send(_mouse(down), _mouse(up))
        time.sleep(0.08)
    time.sleep(0.15)


def drag(hwnd, x1, y1, x2, y2, steps=20):
    if not front(hwnd):
        raise SystemExit("window %s did not come to the front" % hwnd)
    move(hwnd, x1, y1)
    _send(_mouse(0x0002))
    time.sleep(0.1)
    for i in range(1, steps + 1):
        move(hwnd, x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps)
        time.sleep(0.01)
    time.sleep(0.1)
    _send(_mouse(0x0004))
    time.sleep(0.2)


def wheel(hwnd, x, y, clicks):
    if not front(hwnd):
        raise SystemExit("window %s did not come to the front" % hwnd)
    move(hwnd, x, y)
    _send(_mouse(0x0800, (int(clicks) * 120) & 0xFFFFFFFF))
    time.sleep(0.2)


VK = {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12,
      "win": 0x5B, "enter": 0x0D, "return": 0x0D, "tab": 0x09,
      "esc": 0x1B, "escape": 0x1B, "space": 0x20, "backspace": 0x08,
      "delete": 0x2E, "del": 0x2E, "home": 0x24, "end": 0x23,
      "pgup": 0x21, "pgdn": 0x22, "left": 0x25, "up": 0x26, "right": 0x27,
      "down": 0x28, "insert": 0x2D, "apps": 0x5D}
VK.update({"f%d" % n: 0x6F + n for n in range(1, 13)})
EXTENDED = {0x2E, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0x2D}


def _key(vk, up=False):
    item = _IN()
    item.type = 1
    flags = 0x0002 if up else 0
    if vk in EXTENDED:
        flags |= 0x0001
    item.u.ki = _KI(vk, 0, flags, 0, None)
    return item


def _vk(name):
    name = name.lower()
    if name in VK:
        return VK[name]
    if len(name) == 1:
        return U.VkKeyScanW(ord(name)) & 0xFF
    raise SystemExit("unknown key " + name)


def _front_for_keys(hwnd):
    # No Alt-tap to force focus: an Alt tap moves keyboard focus to the
    # window's menu, and typed letters then fire menu shortcuts.
    if not front(hwnd):
        raise SystemExit("window %s is not in front: click into the target "
                         "control first, then type" % hwnd)


def keys(hwnd, spec, delay=0.12):
    _front_for_keys(hwnd)
    for chord in spec.split():
        codes = [_vk(part) for part in chord.split("+")]
        _send(*[_key(code) for code in codes])
        time.sleep(0.03)
        _send(*[_key(code, True) for code in reversed(codes)])
        time.sleep(delay)


def type_text(hwnd, text, delay=0.02):
    _front_for_keys(hwnd)
    for char in text:
        down, up = _IN(), _IN()
        down.type = up.type = 1
        down.u.ki = _KI(0, ord(char), 0x0004, 0, None)
        up.u.ki = _KI(0, ord(char), 0x0004 | 0x0002, 0, None)
        _send(down, up)
        time.sleep(delay)


def clip(path):
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    done = subprocess.run(["powershell", "-NoProfile", "-Command",
                           "$input | Set-Clipboard"], input=text, text=True,
                          encoding="utf-8")
    return done.returncode == 0


# ---------------------------------------------------------------- apps
def _remember(pid):
    try:
        with open(STARTED, encoding="utf-8") as handle:
            pids = json.load(handle)
    except (OSError, ValueError):
        pids = []
    pids.append(pid)
    with open(STARTED, "w", encoding="utf-8") as handle:
        json.dump(pids[-50:], handle)


def find_spotfire():
    home = os.environ.get("SPOTFIRE_HOME")
    if home and os.path.isfile(os.path.join(home, "Spotfire.Dxp.exe")):
        return os.path.join(home, "Spotfire.Dxp.exe")
    import glob
    found = []
    for root in (os.environ.get("LOCALAPPDATA", ""),
                 os.environ.get("ProgramFiles", "")):
        if root:
            found += glob.glob(os.path.join(root, "Spotfire", "*",
                                            "Spotfire.Dxp.exe"))
    if not found:
        raise SystemExit("Spotfire Analyst not found: set SPOTFIRE_HOME")
    return sorted(found)[-1]


def spotfire(analysis, timeout=240):
    """Start a new Analyst process on the analysis (absolute path: Analyst
    resolves a relative path against its own folder)."""
    path = os.path.abspath(analysis)
    if not os.path.isfile(path):
        raise SystemExit("not found: " + path)
    proc = subprocess.Popen([find_spotfire(), path], close_fds=True)
    _remember(proc.pid)
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    start = time.time()
    main_seen = None
    while time.time() - start < timeout:
        for item in windows(pid=proc.pid):
            title = item["title"].lower()
            if stem in title:
                time.sleep(3.0)
                return proc.pid, item["hwnd"]
            if "spotfire" in title and "login" not in title:
                main_seen = main_seen or (time.time(), item["hwnd"])
        # The title normally shows the analysis name once it has loaded;
        # fall back to the main window 30 s after it appeared.
        if main_seen and time.time() - main_seen[0] > 30:
            return proc.pid, main_seen[1]
        time.sleep(1.0)
    raise SystemExit("no Analyst window showing %s after %d s (pid %d; a "
                     "login or trust dialog may be waiting)"
                     % (os.path.basename(path), timeout, proc.pid))


def browser(url, timeout=20):
    candidates = [os.path.join(os.environ.get(root, ""), *parts)
                  for root, parts in (
                      ("ProgramFiles", ("Google", "Chrome", "Application",
                                        "chrome.exe")),
                      ("ProgramFiles(x86)", ("Google", "Chrome",
                                             "Application", "chrome.exe")),
                      ("LOCALAPPDATA", ("Google", "Chrome", "Application",
                                        "chrome.exe")),
                      ("ProgramFiles(x86)", ("Microsoft", "Edge",
                                             "Application", "msedge.exe")))]
    exe = next((c for c in candidates if os.path.isfile(c)), None)
    if exe is None:
        raise SystemExit("Chrome or Edge not found")
    image = os.path.basename(exe)
    before = {w["hwnd"] for w in windows(image)}
    subprocess.Popen([exe, "--new-window", url], close_fds=True)
    end = time.time() + timeout
    while time.time() < end:
        time.sleep(0.5)
        new = [w for w in windows(image) if w["hwnd"] not in before]
        if new:
            time.sleep(1.5)
            return new[0]["hwnd"]
    raise SystemExit("no new browser window within %d s" % timeout)


def close(pid, force=False):
    try:
        with open(STARTED, encoding="utf-8") as handle:
            started = json.load(handle)
    except (OSError, ValueError):
        started = []
    if pid not in started and not force:
        raise SystemExit("pid %d was not started by deskctl; it may be "
                         "the user's own session. Not closed." % pid)
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   capture_output=True)


def selftest(folder=None):
    folder = folder or os.path.join(tempfile.gettempdir(), "deskctl-selftest")
    page = os.path.join(HERE, "..", "assets", "selftest.html")
    hwnd = browser("file:///" + os.path.abspath(page).replace("\\", "/"))
    place(hwnd, 80, 80, 1100, 700)
    print("before", shot(hwnd, os.path.join(folder, "before.png")))
    left, top, right, bottom = rect(hwnd)
    click(hwnd, (right - left) // 2, (bottom - top) // 2 + 60)
    type_text(hwnd, "deskctl selftest: click and typing reached the page")
    time.sleep(0.5)
    print("after", shot(hwnd, os.path.join(folder, "after.png")))
    keys(hwnd, "ctrl+w")
    print("Read after.png: the sentence must show in the text box.")


def main(argv):
    if not argv:
        print(__doc__)
        return 0
    cmd, a = argv[0], argv[1:]
    if cmd == "wins":
        for item in windows(a[0] if a else None):
            print(item["hwnd"], item["pid"], item["exe"], repr(item["title"]),
                  item["rect"])
    elif cmd == "spotfire":
        print(*spotfire(a[0]))
    elif cmd == "browser":
        print(browser(a[0]))
    elif cmd == "place":
        place(int(a[0]), *[int(v) for v in a[1:5]])
    elif cmd == "focus":
        print(front(int(a[0])))
    elif cmd == "shot":
        print(*shot(int(a[0]), a[1]))
    elif cmd in ("click", "dclick", "rclick"):
        click(int(a[0]), float(a[1]), float(a[2]),
              button="right" if cmd == "rclick" else "left",
              double=cmd == "dclick")
    elif cmd == "drag":
        drag(int(a[0]), *[float(v) for v in a[1:5]])
    elif cmd == "wheel":
        wheel(int(a[0]), float(a[1]), float(a[2]), int(a[3]))
    elif cmd == "type":
        type_text(int(a[0]), a[1])
    elif cmd == "keys":
        keys(int(a[0]), a[1])
    elif cmd == "clip":
        print(clip(a[0]))
    elif cmd == "close":
        close(int(a[0]), force="--force" in a)
    elif cmd == "selftest":
        selftest(a[0] if a else None)
    else:
        print("unknown command " + cmd)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    sys.exit(main(sys.argv[1:]))
