#!/usr/bin/env python3
"""GPO NPC Lock-On for macOS.

Keeps your camera pointed at the NPC you're fighting in Grand Piece Online.

Nothing is injected into Roblox. This script only:
  - takes screenshots and looks for the NPC's name tag, and
  - taps the Left/Right arrow keys (Roblox's own "turn camera" keys) to keep
    that name tag in the middle of the screen.
It doesn't attack, move or farm for you, and it only follows the name tag you
capture, so only capture NPC names.

Keys (press them while playing):
  Right Command   capture the NPC's name tag: press it with the pointer on the
                  top-left corner of the tag, then on the bottom-right corner
  Right Option    lock-on on / off
  Control-C       quit (in the Terminal window)

Setup and troubleshooting are in README.md.
"""

import math
import queue
import sys
import threading
import time
from collections import namedtuple
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:
    sys.exit("Missing packages. In Terminal, run:  python3 -m pip install -r requirements.txt")

# --- Settings you can change -------------------------------------------------

CAPTURE_KEY = "right command"  # other choices are listed in KEY_CODES below
TOGGLE_KEY = "right option"

USE_MOUSE = False  # True: turn by moving the mouse (needs Shift Lock on) instead of arrow keys
REVERSE = False  # set to True if the camera turns away from the NPC

MATCH_THRESHOLD = 0.60  # 0 to 1: lower finds the name more easily, higher makes fewer mistakes
DEADZONE = 0.05  # stop turning once the NPC is this close to the middle (0.05 = 5% of half the screen)
TURN_STRENGTH = 0.8  # lower it if the camera wobbles, raise it if it's slow to catch up
SEARCH_AREA = (0.05, 0.85)  # only look between these heights (0 = top of the screen, 1 = bottom)
TARGET_FILE = Path(__file__).with_name("target.png")  # where the captured name tag is saved

# --- Things you shouldn't need to change --------------------------------------

KEY_CODES = {  # macOS key codes (F9 and F11 are taken by Roblox)
    "right command": 54, "right option": 61, "right shift": 60, "right control": 62,
    "f5": 96, "f6": 97, "f7": 98, "f8": 100, "f10": 109,
}
MODIFIER_SIDE_BITS = {54: 0x10, 61: 0x40, 60: 0x04, 62: 0x2000}  # tell left/right modifiers apart
LEFT_ARROW, RIGHT_ARROW = 123, 124
ARROW_FLAGS = 0x800000 | 0x200000  # the "fn" and "keypad" flags a real arrow-key press carries

ROBLOX_FOV = 70  # Roblox's default vertical field of view, degrees
KEY_TURN_SPEED = 120  # degrees per second Roblox turns while an arrow key is held
MOUSE_TURN_SPEED = 0.5  # degrees Roblox turns per mouse pixel at default sensitivity
MIN_TAP, MAX_TAP = 0.03, 0.3  # shortest and longest arrow-key tap, seconds
MAX_MOUSE_MOVE = 120  # pixels per turn
SETTLE_TIME = 0.03  # wait after turning so the next screenshot shows the new view
EDGE_SEARCH = 60  # degrees to keep turning after the NPC slips off the side of the screen

# Name tag sizes to try, compared to the size it was last seen at. Matching is
# fussy about size (2% off already costs a lot), so while following the NPC we
# check slightly bigger and smaller each time. When it's lost we check a wide
# range roughly at half resolution, then look closely at anything promising.
TRACK_SIZES = (1.0, 0.97, 1.03)
WIDE_SIZES = (0.75, 0.8, 0.86, 0.93, 1.0, 1.07, 1.15, 1.23, 1.32)
CLOSE_LOOK_SIZES = (0.96, 0.98, 1.0, 1.02, 1.04)
ROUGH_THRESHOLD = 0.4

Match = namedtuple("Match", "score x y w h size")
Sighting = namedtuple("Sighting", "time x bearing")


def say(message):
    print(message, flush=True)


def sharpen(gray):
    """Keep fine detail like letters and drop smooth background shading.

    This keeps a name tag recognisable when the sky or ground behind it changes.
    """
    gray = gray.astype(np.float32)
    return gray - cv2.GaussianBlur(gray, (0, 0), 3)


def scaled(image, factor):
    if factor == 1:
        return image
    interpolation = cv2.INTER_AREA if factor < 1 else cv2.INTER_LINEAR
    return cv2.resize(image, None, fx=factor, fy=factor, interpolation=interpolation)


def prepare(template, sizes):
    """Sharpened copies of the captured name tag, keyed by size. Too-small sizes are left out."""
    prepared = {}
    for size in sizes:
        resized = scaled(template, size)
        if resized.shape[0] >= 4 and resized.shape[1] >= 8:
            prepared[size] = sharpen(resized)
    return prepared


def local_std(image, w, h):
    """How much detail (standard deviation) each w-by-h patch of `image` has.

    Laid out like cv2.matchTemplate's output: entry (y, x) is the patch whose
    top-left corner is at (x, y).
    """
    mean = cv2.boxFilter(image, -1, (w, h), anchor=(0, 0))
    mean_sq = cv2.boxFilter(image * image, -1, (w, h), anchor=(0, 0))
    rows, cols = image.shape[0] - h + 1, image.shape[1] - w + 1
    return np.sqrt(np.maximum(mean_sq - mean * mean, 0))[:rows, :cols]


def match_scores(image, template):
    """cv2.matchTemplate scores, with plain patches of `image` ruled out.

    Plain areas (clear sky, flat walls) are almost blank after sharpen(), and
    the maths can give a blank patch a perfect score by accident.
    """
    th, tw = template.shape
    scores = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    scores[local_std(image, tw, th) < 0.3 * template.std()] = -1
    return scores


def find_matches(image, templates, threshold, limit=4):
    """Up to `limit` separate places where the name tag appears in `image`, best first.

    `image` must be sharpen()ed and `templates` must come from prepare().
    """
    hits = []
    for size, template in templates.items():
        th, tw = template.shape
        if th > image.shape[0] or tw > image.shape[1]:
            continue
        scores = match_scores(image, template)
        for _ in range(limit):
            _, score, _, (x, y) = cv2.minMaxLoc(scores)
            if score < threshold:
                break
            hits.append(Match(score, x + tw / 2, y + th / 2, tw, th, size))
            # Blank out this spot so the next pass finds a different one.
            scores[max(0, y - th // 2):y + th // 2 + 1, max(0, x - tw // 2):x + tw // 2 + 1] = -1
    hits.sort(reverse=True)
    kept = []
    for hit in hits:  # the same tag can match at several sizes; keep the best one
        if all(abs(hit.x - k.x) > k.w / 2 or abs(hit.y - k.y) > k.h / 2 for k in kept):
            kept.append(hit)
    return kept[:limit]


def best_score(image, templates):
    """How well the closest thing in `image` matches, even if it's below the threshold."""
    best = -1.0
    for template in templates.values():
        if template.shape[0] <= image.shape[0] and template.shape[1] <= image.shape[1]:
            best = max(best, float(match_scores(image, template).max()))
    return best


class Tracker:
    """Finds the captured name tag on screen and turns the camera toward it."""

    def __init__(self, io, template=None):
        self.io = io
        self.use_mouse = USE_MOUSE
        self.reverse = REVERSE
        self.save_path = TARGET_FILE
        self.enabled = False
        self.first_corner = None
        self.hints_given = set()
        self.width, self.height = io.screen_size
        self.top = int(self.height * SEARCH_AREA[0])
        self.bottom = int(self.height * SEARCH_AREA[1])
        self.tan_half_fov = math.tan(math.radians(ROBLOX_FOV / 2)) * self.width / self.height
        self.deadzone = self.bearing(self.width / 2 * (1 + DEADZONE))
        # How many degrees the NPC shifts on screen per degree the camera turns.
        # It's below 1 when the NPC is close, because Roblox's camera circles
        # your character instead of spinning in place. Learned as we go.
        self.response = 1.0
        self.target = template  # the captured name tag (grayscale), or None
        self.sized = {}  # prepared copies of it, by size
        self.reset()

    def reset(self):
        self.last = None  # the last Sighting of our NPC
        self.turned = None  # degrees turned since then (None: don't learn from it)
        self.best_size = 1.0
        self.searched = 0
        self.lost_since = None
        self.lost_said = False
        self.score_checked = False
        self.wrong_way = 0
        self.no_effect = 0

    # --- keys ---------------------------------------------------------------

    def toggle(self):
        if self.target is None:
            say(f"Capture the NPC's name tag first ({CAPTURE_KEY.title()}, twice).")
            return
        self.enabled = not self.enabled
        self.reset()
        say("Lock-on ON" if self.enabled else "Lock-on OFF")

    def add_corner(self, x, y):
        """Handle a press of the capture key with the pointer at (x, y)."""
        now = self.io.now()
        if self.first_corner is None or now - self.first_corner[2] > 30:
            self.first_corner = (x, y, now)
            say(f"Top-left corner saved. Now point at the bottom-right corner of the name tag "
                f"and press {CAPTURE_KEY.title()} again.")
            return
        (x0, y0, _), self.first_corner = self.first_corner, None
        left, right = sorted((int(x0), int(x)))
        top, bottom = sorted((int(y0), int(y)))
        if right - left < 12 or bottom - top < 6:
            say("That box is too small. If your pointer is stuck in the middle of the screen, "
                "turn Shift Lock off first. Start again at the top-left corner.")
            return
        patch = self.io.grab(left, top, right - left, bottom - top)
        if patch.std() < 10:
            say("There isn't much in that box. Box the NPC's name tag and try again.")
            return
        self.target, self.sized = patch, {}
        self.reset()
        if self.save_path:
            cv2.imwrite(str(self.save_path), patch)
        say(f"Got the NPC's name tag. Press {TOGGLE_KEY.title()} to lock on.")

    # --- tracking -------------------------------------------------------------

    def step(self):
        """Look once, and turn toward the NPC if it's off-centre."""
        if not self.enabled or not self.io.roblox_in_front():
            self.io.sleep(0.05)
            return
        frame = sharpen(self.io.grab(0, self.top, self.width, self.bottom - self.top))
        match = self.find(frame)
        if match is None:
            self.lost(frame)
            return
        if self.lost_said:
            say("Found it.")
        bearing = self.bearing(match.x)
        self.learn(bearing)
        self.last = Sighting(self.io.now(), match.x, bearing)
        self.turned, self.searched, self.best_size = 0.0, 0, match.size
        self.lost_since, self.lost_said, self.score_checked = None, False, False
        if abs(bearing) > self.deadzone:
            self.turn(TURN_STRENGTH * bearing / self.response)

    def find(self, frame):
        """Where our NPC's name tag is in this frame (a Match), or None."""
        recent = self.last is not None and self.io.now() - self.last.time < 0.5
        expected = self.width / 2
        if recent and self.turned is not None:  # where it should be after our last turn
            guess = self.last.bearing - self.response * self.turned
            expected = self.screen_x(max(-80, min(80, guess)))
        hits = []
        if recent:  # look near there first, at about the same size: much faster
            x0 = max(0, int(expected - self.width / 4))
            x1 = min(self.width, int(expected + self.width / 4))
            if x1 - x0 >= 8:
                templates = self.sizes(self.best_size * f for f in TRACK_SIZES)
                hits = [hit._replace(x=hit.x + x0)
                        for hit in find_matches(frame[:, x0:x1], templates, MATCH_THRESHOLD)]
        if not hits:
            hits = self.search_everywhere(frame)
        if not hits:
            return None
        return min(hits, key=lambda hit: abs(hit.x - expected))

    def search_everywhere(self, frame):
        """Search the whole frame at a wide range of sizes: roughly at half
        resolution first, then closely around anything that looks promising."""
        templates = self.sizes(self.best_size * f for f in WIDE_SIZES)
        rough = {size: scaled(t, 0.5) for size, t in templates.items() if min(t.shape) >= 8}
        if not rough:  # too small to shrink, so search at full resolution
            return find_matches(frame, templates, MATCH_THRESHOLD)
        hits = []
        for guess in find_matches(scaled(frame, 0.5), rough, ROUGH_THRESHOLD, limit=8):
            x, y, w, h = guess.x * 2, guess.y * 2, guess.w * 2, guess.h * 2
            x0, y0 = max(0, int(x - w)), max(0, int(y - h))
            area = frame[y0:int(y + h) + 1, x0:int(x + w) + 1]
            nearby = self.sizes(guess.size * f for f in CLOSE_LOOK_SIZES)
            hits += [hit._replace(x=hit.x + x0, y=hit.y + y0)
                     for hit in find_matches(area, nearby, MATCH_THRESHOLD, limit=1)]
        return hits

    def sizes(self, sizes):
        """Prepared copies of the captured name tag at these sizes, keyed by size."""
        found = {}
        for size in sizes:
            size = round(min(2.0, max(0.5, size)), 2)
            if size not in self.sized:
                self.sized[size] = prepare(self.target, [size]).get(size)
            if self.sized[size] is not None:
                found[size] = self.sized[size]
        return found

    def learn(self, bearing):
        """Compare where the NPC is now with where it was before our last turn."""
        if self.last is None or self.turned is None or abs(self.turned) < 4:
            return
        moved = (self.last.bearing - bearing) / self.turned
        if moved > 0.05:
            self.response = min(2.0, max(0.1, (self.response + min(moved, 2.0)) / 2))
            self.wrong_way = self.no_effect = 0
        elif moved < -0.15:
            # Usually the NPC is off screen after one or two backwards turns, so
            # a single clear one is enough to mention it.
            self.wrong_way += 1
            if self.wrong_way >= 2 or (moved < -0.5 and abs(self.turned) >= 8):
                self.hint("reverse", "The camera seems to turn away from the NPC. If it does, "
                                     "set REVERSE = True at the top of npc_lock.py.")
        else:
            self.no_effect += 1
            if self.no_effect >= 6:
                fix = ("USE_MOUSE = False" if self.use_mouse
                       else "USE_MOUSE = True at the top of npc_lock.py, and turn Shift Lock on")
                self.hint("stuck", f"The camera doesn't seem to turn. Try {fix}.")

    def turn(self, degrees):
        """Turn the camera about this many degrees (positive = right)."""
        sign = -1 if self.reverse else 1
        wanted = degrees * sign
        if self.use_mouse:
            pixels = int(max(-MAX_MOUSE_MOVE, min(MAX_MOUSE_MOVE, round(wanted / MOUSE_TURN_SPEED))))
            if pixels:
                self.io.move_mouse(pixels)
            done = pixels * MOUSE_TURN_SPEED
        else:
            seconds = max(MIN_TAP, min(MAX_TAP, abs(wanted) / KEY_TURN_SPEED))
            self.io.tap_arrow(RIGHT_ARROW if wanted > 0 else LEFT_ARROW, seconds)
            done = math.copysign(seconds * KEY_TURN_SPEED, wanted)
        if self.turned is not None:
            self.turned += done * sign
        self.io.sleep(SETTLE_TIME)

    def lost(self, frame):
        """The NPC isn't on screen. If it slipped off the side, turn after it."""
        now = self.io.now()
        if self.lost_since is None:
            self.lost_since = now
        gone = now - self.lost_since
        if gone > 0.5 and not self.lost_said:
            self.lost_said = True
            say("Lost the NPC. Looking for it...")
        if gone > 2 and not self.score_checked:
            self.score_checked = True
            score = best_score(frame, self.sizes(self.best_size * f for f in WIDE_SIZES))
            if 0.4 <= score < MATCH_THRESHOLD:
                say(f"(The closest thing on screen matches {score:.2f} and needs {MATCH_THRESHOLD:.2f}. "
                    "If the NPC is right there, capture its name tag again or lower MATCH_THRESHOLD.)")
        last = self.last
        limit = min(180, EDGE_SEARCH / self.response)
        if (last is not None and abs(last.x - self.width / 2) > self.width / 4
                and (self.searched > 0 or now - last.time < 0.5) and self.searched < limit):
            self.turned = None  # a search turn isn't a clean measurement
            step = min(10 / self.response, limit - self.searched)
            self.searched += step
            self.turn(math.copysign(step, last.bearing))
        else:
            self.io.sleep(0.02)

    # --- helpers ------------------------------------------------------------

    def bearing(self, x):
        """Degrees from the middle of the screen to screen position x (right is positive)."""
        half = self.width / 2
        return math.degrees(math.atan((x - half) / half * self.tan_half_fov))

    def screen_x(self, bearing):
        half = self.width / 2
        return half + half * math.tan(math.radians(bearing)) / self.tan_half_fov

    def hint(self, key, message):
        if key not in self.hints_given:
            self.hints_given.add(key)
            say(message)


class MacIO:
    """Screenshots, key presses and hotkeys on macOS."""

    def __init__(self):
        import mss
        import Quartz

        self.Q = Quartz
        self.sct = mss.mss()
        screen = self.sct.monitors[1]  # the main display, measured in points
        self.origin = (screen["left"], screen["top"])
        self.screen_size = (screen["width"], screen["height"])
        self.front_checked = 0.0
        self.front = False
        self.keep = []  # stops Python from freeing the hotkey listener

    now = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)

    def grab(self, x, y, w, h):
        """Grayscale screenshot of a box on the main display, one pixel per point."""
        box = {"left": self.origin[0] + x, "top": self.origin[1] + y, "width": w, "height": h}
        gray = cv2.cvtColor(np.asarray(self.sct.grab(box)), cv2.COLOR_BGRA2GRAY)
        if gray.shape[1] != w:  # Retina screens have 2 pixels per point
            gray = cv2.resize(gray, (w, h), interpolation=cv2.INTER_AREA)
        return gray

    def roblox_in_front(self):
        """Whether Roblox is the app you're using (checked twice a second)."""
        now = time.monotonic()
        if now - self.front_checked > 0.5:
            self.front_checked = now
            Q = self.Q
            windows = Q.CGWindowListCopyWindowInfo(
                Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements,
                Q.kCGNullWindowID) or []
            front = next((w for w in windows if w.get(Q.kCGWindowLayer) == 0), None)
            self.front = front is not None and "roblox" in str(front.get(Q.kCGWindowOwnerName, "")).lower()
        return self.front

    def key(self, code, down):
        Q = self.Q
        event = Q.CGEventCreateKeyboardEvent(None, code, down)
        Q.CGEventSetFlags(event, Q.CGEventGetFlags(event) | ARROW_FLAGS)
        Q.CGEventPost(Q.kCGHIDEventTap, event)

    def tap_arrow(self, code, seconds):
        self.key(code, True)
        try:
            time.sleep(seconds)
        finally:
            self.key(code, False)

    def move_mouse(self, dx):
        """Nudge the mouse sideways (this turns the camera while Shift Lock is on)."""
        Q = self.Q
        while dx:
            step = max(-40, min(40, dx))
            dx -= step
            where = Q.CGEventGetLocation(Q.CGEventCreate(None))
            event = Q.CGEventCreateMouseEvent(None, Q.kCGEventMouseMoved, where, Q.kCGMouseButtonLeft)
            Q.CGEventSetIntegerValueField(event, Q.kCGMouseEventDeltaX, step)
            Q.CGEventSetIntegerValueField(event, Q.kCGMouseEventDeltaY, 0)
            Q.CGEventPost(Q.kCGHIDEventTap, event)
            time.sleep(0.005)

    def missing_permissions(self):
        """macOS permissions Terminal still needs. Also makes macOS ask for them."""
        checks = [
            ("Screen Recording", "CGPreflightScreenCaptureAccess", "CGRequestScreenCaptureAccess"),
            ("Accessibility", "CGPreflightPostEventAccess", "CGRequestPostEventAccess"),
            ("Input Monitoring", "CGPreflightListenEventAccess", "CGRequestListenEventAccess"),
        ]
        missing = []
        for name, check, request in checks:
            if hasattr(self.Q, check) and not getattr(self.Q, check)():
                getattr(self.Q, request, lambda: None)()
                missing.append(name)
        return missing

    def listen(self, hotkeys, events):
        """Put (name, x, y) on `events` whenever a key in {key code: name} is pressed."""
        Q = self.Q
        down = set()

        def on_event(proxy, kind, event, refcon):
            if kind in (Q.kCGEventTapDisabledByTimeout, Q.kCGEventTapDisabledByUserInput):
                Q.CGEventTapEnable(tap, True)
                return event
            code = Q.CGEventGetIntegerValueField(event, Q.kCGKeyboardEventKeycode)
            if code not in hotkeys:
                return event
            if kind == Q.kCGEventFlagsChanged:  # modifier keys only send "flags changed"
                pressed = bool(Q.CGEventGetFlags(event) & MODIFIER_SIDE_BITS.get(code, 0))
                was_down = code in down
                (down.add if pressed else down.discard)(code)
                if not pressed or was_down:
                    return event
            elif Q.CGEventGetIntegerValueField(event, Q.kCGKeyboardEventAutorepeat):
                return event
            where = Q.CGEventGetLocation(event)
            events.put((hotkeys[code], where.x - self.origin[0], where.y - self.origin[1]))
            return event

        mask = (1 << Q.kCGEventKeyDown) | (1 << Q.kCGEventFlagsChanged)
        tap = Q.CGEventTapCreate(Q.kCGSessionEventTap, Q.kCGHeadInsertEventTap,
                                 Q.kCGEventTapOptionListenOnly, mask, on_event, None)
        if tap is None:
            raise PermissionError("can't listen for hotkeys")
        source = Q.CFMachPortCreateRunLoopSource(None, tap, 0)

        def run():
            Q.CFRunLoopAddSource(Q.CFRunLoopGetCurrent(), source, Q.kCFRunLoopCommonModes)
            Q.CGEventTapEnable(tap, True)
            Q.CFRunLoopRun()

        self.keep += [tap, source, on_event]
        threading.Thread(target=run, daemon=True).start()


PERMISSIONS_HELP = """\
macOS needs to let Terminal do this first (missing: {}).

  1. Open System Settings > Privacy & Security.
  2. Turn on Terminal under Screen Recording (called "Screen & System Audio
     Recording" on newer macOS), Accessibility, and Input Monitoring.
  3. Quit Terminal completely (Command-Q), open it again, and rerun this script.
"""


def main():
    if sys.platform != "darwin":
        sys.exit("This version only works on macOS.")
    if CAPTURE_KEY not in KEY_CODES or TOGGLE_KEY not in KEY_CODES:
        sys.exit(f"CAPTURE_KEY and TOGGLE_KEY must be one of: {', '.join(KEY_CODES)}")
    try:
        io = MacIO()
    except ImportError:
        sys.exit("Missing packages. In Terminal, run:  python3 -m pip install -r requirements.txt")
    missing = io.missing_permissions()
    if missing:
        sys.exit(PERMISSIONS_HELP.format(", ".join(missing)))

    template = cv2.imread(str(TARGET_FILE), cv2.IMREAD_GRAYSCALE) if TARGET_FILE.exists() else None
    tracker = Tracker(io, template)
    events = queue.Queue()
    try:
        io.listen({KEY_CODES[CAPTURE_KEY]: "capture", KEY_CODES[TOGGLE_KEY]: "toggle"}, events)
    except PermissionError:
        sys.exit(PERMISSIONS_HELP.format("Input Monitoring"))

    capture, toggle = CAPTURE_KEY.title(), TOGGLE_KEY.title()
    say(f"GPO NPC Lock-On is running. Switch to Roblox.\n"
        f"  1. Turn Shift Lock off so you can move the pointer. Press {capture} on the\n"
        f"     top-left corner of the NPC's name tag, then on its bottom-right corner.\n"
        f"  2. Press {toggle} to turn lock-on on or off.\n"
        f"  Press Control-C here to quit.")
    if template is not None:
        say("(Using the name tag you captured last time. Capture again to change it.)")

    try:
        while True:
            while not events.empty():
                name, x, y = events.get()
                if name == "toggle":
                    tracker.toggle()
                else:
                    tracker.add_corner(x, y)
            tracker.step()
    except KeyboardInterrupt:
        say("\nBye!")


if __name__ == "__main__":
    main()
