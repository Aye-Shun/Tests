"""Tests for npc_lock.py against a pretend Roblox camera (no Mac or Roblox needed).

Run:  python3 -m unittest test_npc_lock.py
"""

import math
import queue
import sys
import types
import unittest
from collections import namedtuple

import cv2
import numpy as np

import npc_lock
from npc_lock import RIGHT_ARROW, Sighting, Tracker, find_matches, prepare, sharpen

W, H = 1280, 800
TAN_HALF_FOV = math.tan(math.radians(npc_lock.ROBLOX_FOV / 2)) * W / H


def name_tag(text, scale=0.7):
    """A Roblox-style name tag: white letters with a dark outline. Returns (image, opacity)."""
    font = cv2.FONT_HERSHEY_DUPLEX
    (tw, th), base = cv2.getTextSize(text, font, scale, 1)
    image = np.zeros((th + base + 8, tw + 8), np.uint8)
    opacity = np.zeros_like(image)
    cv2.putText(opacity, text, (4, th + 4), font, scale, 255, 5, cv2.LINE_AA)
    cv2.putText(image, text, (4, th + 4), font, scale, 255, 1, cv2.LINE_AA)
    return image, opacity / 255.0


def scenery(seed=1):
    """A 360-degree strip of lumpy ground and blocks, 10 pixels per degree."""
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 255, (H // 16, 3600 // 16), dtype=np.uint8)
    strip = cv2.resize(noise, (3600, H), interpolation=cv2.INTER_CUBIC)
    for _ in range(150):
        x, y = int(rng.integers(0, 3600)), int(rng.integers(0, H))
        size = (x + int(rng.integers(10, 120)), y + int(rng.integers(10, 120)))
        cv2.rectangle(strip, (x, y), size, int(rng.integers(0, 255)), -1)
    return strip


def paste(frame, image, opacity, x, y):
    """Draw a name tag with its top-left corner at (x, y), clipped to the frame."""
    h, w = image.shape
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, frame.shape[1]), min(y + h, frame.shape[0])
    if x1 > x0 and y1 > y0:
        img = image[y0 - y:y1 - y, x0 - x:x1 - x]
        op = opacity[y0 - y:y1 - y, x0 - x:x1 - x]
        frame[y0:y1, x0:x1] = (frame[y0:y1, x0:x1] * (1 - op) + img * op).astype(np.uint8)


class World:
    """Roblox's default camera circling your character at (0, 0), with NPCs around it.

    It has the same methods as npc_lock.MacIO, so a Tracker can drive it.
    """

    SCENERY = scenery()

    def __init__(self, npcs, yaw=0.0, distance=12.0, key_turns=1, mouse_sensitivity=1.0):
        self.npcs = npcs  # dicts: name, x, z (studs) and optional vx, vz (studs per second)
        self.yaw = yaw  # degrees clockwise from north (+z)
        self.distance = distance  # how far the camera sits behind the character
        self.key_turns = key_turns  # 1 normal, -1 backwards, 0 arrow keys do nothing
        self.mouse_sensitivity = mouse_sensitivity
        self.clock = 0.0
        self.screen_size = (W, H)
        self.front = True
        self.tags = {}

    # --- what Tracker calls ---

    def now(self):
        return self.clock

    def sleep(self, seconds):
        self.advance(seconds)

    def roblox_in_front(self):
        return self.front

    def tap_arrow(self, code, seconds):
        direction = 1 if code == RIGHT_ARROW else -1
        for _ in range(max(1, round(seconds * 60))):  # Roblox turns a bit each frame at 60 fps
            self.yaw += self.key_turns * direction * npc_lock.KEY_TURN_SPEED / 60
            self.advance(1 / 60)

    def move_mouse(self, dx):
        self.yaw += dx * npc_lock.MOUSE_TURN_SPEED * self.mouse_sensitivity
        self.advance(0.01)

    def grab(self, x, y, w, h):
        self.advance(0.05)  # taking a screenshot and searching it takes a moment
        return self.render()[y:y + h, x:x + w].copy()

    # --- the pretend game ---

    def advance(self, seconds):
        self.clock += seconds
        for npc in self.npcs:
            npc["x"] += npc.get("vx", 0) * seconds
            npc["z"] += npc.get("vz", 0) * seconds

    def bearing_of(self, npc):
        """Degrees from the middle of the screen to the NPC (right is positive), None if behind."""
        yaw = math.radians(self.yaw)
        look, right = (math.sin(yaw), math.cos(yaw)), (math.cos(yaw), -math.sin(yaw))
        dx, dz = npc["x"] + self.distance * look[0], npc["z"] + self.distance * look[1]
        ahead, side = dx * look[0] + dz * look[1], dx * right[0] + dz * right[1]
        return math.degrees(math.atan2(side, ahead)) if ahead > 0.1 else None

    def tag(self, name):
        if name not in self.tags:
            self.tags[name] = name_tag(name)
        return self.tags[name]

    def tag_box(self, npc):
        """(x, y, w, h) of the NPC's name tag on screen."""
        image, _ = self.tag(npc["name"])
        centre = W / 2 + W / 2 * math.tan(math.radians(self.bearing_of(npc))) / TAN_HALF_FOV
        x, y = centre - image.shape[1] / 2, npc.get("y", 0.4 * H) - image.shape[0] / 2
        return int(round(x)), int(round(y)), image.shape[1], image.shape[0]

    def render(self):
        bearings = np.degrees(np.arctan((np.arange(W) - W / 2) / (W / 2) * TAN_HALF_FOV))
        frame = self.SCENERY[:, ((self.yaw + bearings) * 10).astype(int) % 3600]
        for npc in self.npcs:
            bearing = self.bearing_of(npc)
            if bearing is not None and abs(bearing) < 80:
                x, y, _, _ = self.tag_box(npc)
                paste(frame, *self.tag(npc["name"]), x, y)
        return frame


def npc_at(name, distance, angle, **extra):
    """An NPC `distance` studs from your character, `angle` degrees right of where you face."""
    a = math.radians(angle)
    return dict(name=name, x=distance * math.sin(a), z=distance * math.cos(a), **extra)


def start(world, target, use_mouse=False, reverse=False):
    """A Tracker that captured `target`'s name the way a player would, with lock-on on."""
    tracker = Tracker(world)
    tracker.save_path = None
    tracker.use_mouse, tracker.reverse = use_mouse, reverse
    x, y, w, h = world.tag_box(target)
    tracker.add_corner(x, y)
    tracker.add_corner(x + w, y + h)
    tracker.toggle()
    return tracker


def run(tracker, world, target, steps):
    """Step the tracker; return the NPC's bearing after each step."""
    bearings = []
    for _ in range(steps):
        tracker.step()
        bearings.append(world.bearing_of(target))
    return bearings


class Quiet(unittest.TestCase):
    """Collects what the script would print instead of printing it."""

    def setUp(self):
        self.messages = []
        self.real_say = npc_lock.say
        npc_lock.say = self.messages.append

    def tearDown(self):
        npc_lock.say = self.real_say

    def said(self, text):
        return any(text in message for message in self.messages)


def captured(world, npc):
    """The NPC's name tag, cut out of the screen the way a player would box it."""
    return world.grab(*world.tag_box(npc))


class FindMatchesTest(Quiet):
    def test_finds_the_npc_name_but_not_other_names(self):
        npc = npc_at("Bandit Boss", 40, 12)
        player = npc_at("xXSlayerXx", 30, -25)
        world = World([npc, player])
        templates = prepare(captured(world, npc), [1.0])
        world.yaw = 8  # turn so different scenery is behind the name
        hits = find_matches(sharpen(world.render()), templates, npc_lock.MATCH_THRESHOLD)
        self.assertEqual(len(hits), 1)
        x, _, w, _ = world.tag_box(npc)
        self.assertAlmostEqual(hits[0].x, x + w / 2, delta=2)

    def test_plain_areas_do_not_match(self):
        # Blank patches used to score a perfect 1.0 by accident.
        world = World([npc_at("Bandit Boss", 40, 0)])
        templates = prepare(captured(world, world.npcs[0]), [0.8, 1.0, 1.25])
        world.npcs.clear()
        frame = world.render()
        frame[100:400, 50:500] = 90  # a big flat wall
        frame[450:700, 700:1200] = np.linspace(120, 200, 500, dtype=np.uint8)  # smooth sky
        self.assertEqual(find_matches(sharpen(frame), templates, npc_lock.MATCH_THRESHOLD), [])
        self.assertLess(npc_lock.best_score(sharpen(frame), templates), 0.5)

    def test_finds_a_name_tag_that_got_bigger(self):
        # The NPC came closer, so its name is drawn at a bigger font size.
        world = World([])
        image, opacity = name_tag("Bandit Boss")
        frame = world.render()
        paste(frame, image, opacity, 300, 300)
        tracker = Tracker(world, frame[300:300 + image.shape[0], 300:300 + image.shape[1]].copy())
        world.yaw = 30
        for growth in (1.05, 1.1, 1.2, 1.3):
            bigger = world.render()
            big_image, big_opacity = name_tag("Bandit Boss", scale=0.7 * growth)
            paste(bigger, big_image, big_opacity, 700, 200)
            match = tracker.find(sharpen(bigger))
            self.assertIsNotNone(match, growth)
            self.assertAlmostEqual(match.x, 700 + big_image.shape[1] / 2, delta=4)
            self.assertAlmostEqual(match.size, growth, delta=0.06)

    def test_follows_a_name_tag_that_grows_steadily(self):
        npc = npc_at("Bandit Boss", 40, 0)
        world = World([npc])
        tracker = start(world, npc)
        for step in range(15):  # grows about 2% per look, 32% in total
            world.tags["Bandit Boss"] = name_tag("Bandit Boss", scale=0.7 * 1.02 ** step)
            tracker.step()
            self.assertIsNotNone(tracker.last, step)
            self.assertLess(world.clock - tracker.last.time, 0.2, step)
        self.assertAlmostEqual(tracker.best_size, 1.02 ** 14, delta=0.06)


class TrackingTest(Quiet):
    def assert_centred(self, tracker, bearings, within):
        """The NPC reaches the middle within `within` steps and stays there."""
        settled = next((i for i, b in enumerate(bearings) if b is not None and abs(b) <= tracker.deadzone), None)
        self.assertIsNotNone(settled, f"never centred: {bearings}")
        self.assertLessEqual(settled, within, f"too slow: {bearings}")
        for b in bearings[settled:]:
            self.assertLessEqual(abs(b), tracker.deadzone * 1.5, f"drifted: {bearings}")

    def test_far_npc(self):
        npc = npc_at("Bandit Boss", 60, 30)
        world = World([npc])
        tracker = start(world, npc)
        self.assert_centred(tracker, run(tracker, world, npc, 15), within=5)

    def test_close_npc(self):
        # Close NPCs barely move on screen as the camera circles, so it has to learn to turn harder.
        npc = npc_at("Bandit Boss", 5, 60)
        world = World([npc])
        tracker = start(world, npc)
        self.assert_centred(tracker, run(tracker, world, npc, 20), within=10)

    def test_close_npc_zoomed_out(self):
        npc = npc_at("Bandit Boss", 5, 50)
        world = World([npc], distance=25)
        tracker = start(world, npc)
        self.assert_centred(tracker, run(tracker, world, npc, 25), within=15)

    def test_npc_to_the_left(self):
        npc = npc_at("Bandit Boss", 20, -40)
        world = World([npc])
        tracker = start(world, npc)
        self.assert_centred(tracker, run(tracker, world, npc, 20), within=10)

    def test_follows_a_running_npc(self):
        npc = npc_at("Bandit Boss", 15, 10, vx=-8)  # runs across in front of you
        world = World([npc])
        tracker = start(world, npc)
        bearings = run(tracker, world, npc, 40)[5:]
        close = [b for b in bearings if b is not None and abs(b) <= tracker.deadzone * 2]
        self.assertGreaterEqual(len(close), 0.8 * len(bearings), bearings)
        self.assertFalse(self.said("REVERSE"))  # a moving NPC isn't mistaken for a backwards camera

    def test_stays_on_the_npc_nearest_the_middle(self):
        near_middle = npc_at("Bandit", 30, 6)
        other = npc_at("Bandit", 25, -35)
        world = World([near_middle, other])
        tracker = start(world, near_middle)
        self.assert_centred(tracker, run(tracker, world, near_middle, 15), within=5)
        self.assertGreater(abs(world.bearing_of(other)), 20)

    def test_ignores_other_names(self):
        npc = npc_at("Bandit Boss", 30, 5)
        player = npc_at("xXSlayerXx", 30, 25)
        world = World([npc, player])
        tracker = start(world, npc)
        world.npcs.remove(npc)  # the NPC is gone; only the player is left
        run(tracker, world, player, 15)
        self.assertEqual(world.yaw, 0)
        self.assertTrue(self.said("Lost the NPC"))

    def test_turns_after_an_npc_that_left_the_side_of_the_screen(self):
        npc = npc_at("Bandit Boss", 60, 30)
        world = World([npc])
        tracker = start(world, npc)
        # It was just seen near the right edge, then got knocked off the screen.
        tracker.last = Sighting(world.now(), W * 0.9, tracker.bearing(W * 0.9))
        tracker.turned = 0.0
        npc.update(npc_at("Bandit Boss", 60, 68))
        self.assertGreater(world.bearing_of(npc), 55)  # well off the right edge
        bearings = run(tracker, world, npc, 20)
        self.assertGreater(world.yaw, 30)
        self.assertLessEqual(abs(bearings[-1]), tracker.deadzone)

    def test_says_when_it_loses_and_finds_the_npc(self):
        npc = npc_at("Bandit Boss", 40, 2)
        world = World([npc])
        tracker = start(world, npc)
        run(tracker, world, npc, 3)
        world.npcs.remove(npc)  # hidden behind something
        run(tracker, world, npc, 12)
        self.assertTrue(self.said("Lost the NPC"))
        world.npcs.append(npc)
        run(tracker, world, npc, 3)
        self.assertTrue(self.said("Found it"))

    def test_turning_with_the_mouse(self):
        npc = npc_at("Bandit Boss", 40, 25)
        world = World([npc], mouse_sensitivity=0.6)
        tracker = start(world, npc, use_mouse=True)
        self.assert_centred(tracker, run(tracker, world, npc, 15), within=6)

    def test_reverse_setting(self):
        npc = npc_at("Bandit Boss", 40, 25)
        world = World([npc], key_turns=-1)
        tracker = start(world, npc, reverse=True)
        self.assert_centred(tracker, run(tracker, world, npc, 15), within=5)

    def test_hint_when_turning_the_wrong_way(self):
        npc = npc_at("Bandit Boss", 60, 20)
        world = World([npc], key_turns=-1)
        tracker = start(world, npc)
        run(tracker, world, npc, 10)
        self.assertTrue(self.said("REVERSE = True"))

    def test_hint_when_the_camera_does_not_turn(self):
        npc = npc_at("Bandit Boss", 40, 25)
        world = World([npc], key_turns=0)
        tracker = start(world, npc)
        run(tracker, world, npc, 10)
        self.assertTrue(self.said("USE_MOUSE = True"))

    def test_waits_while_roblox_is_not_in_front(self):
        npc = npc_at("Bandit Boss", 40, 25)
        world = World([npc])
        tracker = start(world, npc)
        world.front = False
        run(tracker, world, npc, 5)
        self.assertEqual(world.yaw, 0)


class CaptureTest(Quiet):
    def test_needs_a_capture_before_locking_on(self):
        tracker = Tracker(World([]))
        tracker.toggle()
        self.assertFalse(tracker.enabled)
        self.assertTrue(self.said("Capture the NPC's name tag first"))

    def test_rejects_a_tiny_box(self):
        tracker = Tracker(World([]))
        tracker.save_path = None
        tracker.add_corner(100, 100)
        tracker.add_corner(104, 102)
        self.assertIsNone(tracker.target)
        self.assertTrue(self.said("too small"))

    def test_rejects_a_plain_box(self):
        world = World([])
        world.grab = lambda x, y, w, h: np.full((h, w), 128, np.uint8)
        tracker = Tracker(world)
        tracker.save_path = None
        tracker.add_corner(100, 100)
        tracker.add_corner(220, 130)
        self.assertIsNone(tracker.target)
        self.assertTrue(self.said("There isn't much in that box"))


Point = namedtuple("Point", "x y")


class FakeQuartz:
    """Just enough of macOS's Quartz (from PyObjC) to run MacIO without a Mac."""

    kCGWindowListOptionOnScreenOnly, kCGWindowListExcludeDesktopElements, kCGNullWindowID = 1, 16, 0
    kCGWindowLayer, kCGWindowOwnerName = "kCGWindowLayer", "kCGWindowOwnerName"
    kCGHIDEventTap, kCGSessionEventTap, kCGHeadInsertEventTap, kCGEventTapOptionListenOnly = 0, 1, 0, 1
    kCGEventMouseMoved, kCGEventKeyDown, kCGEventFlagsChanged = 5, 10, 12
    kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput = 0xFFFFFFFE, 0xFFFFFFFF
    kCGMouseButtonLeft, kCGMouseEventDeltaX, kCGMouseEventDeltaY = 0, 4, 5
    kCGKeyboardEventAutorepeat, kCGKeyboardEventKeycode = 8, 9
    kCFRunLoopCommonModes = "common"

    def __init__(self):
        self.posted, self.windows, self.requested = [], [], []
        self.granted = {}
        self.tap_callback = None

    def CGEventCreateKeyboardEvent(self, source, code, down):
        return {"code": code, "down": down, "flags": 0x100}

    def CGEventCreate(self, source):
        return {"location": Point(10, 20)}

    def CGEventCreateMouseEvent(self, source, kind, where, button):
        return {"location": where, "fields": {}}

    def CGEventGetFlags(self, event):
        return event["flags"]

    def CGEventSetFlags(self, event, flags):
        event["flags"] = flags

    def CGEventGetLocation(self, event):
        return event["location"]

    def CGEventGetIntegerValueField(self, event, field):
        return event["fields"].get(field, 0)

    def CGEventSetIntegerValueField(self, event, field, value):
        event["fields"][field] = value

    def CGEventPost(self, tap, event):
        self.posted.append(dict(event))

    def CGWindowListCopyWindowInfo(self, options, window):
        return self.windows

    def CGEventTapCreate(self, where, place, options, mask, callback, refcon):
        self.tap_callback = callback
        return "tap"

    def CFMachPortCreateRunLoopSource(self, allocator, tap, order):
        return "source"

    def CFRunLoopGetCurrent(self):
        return "loop"

    def CFRunLoopAddSource(self, loop, source, mode):
        pass

    def CGEventTapEnable(self, tap, enable):
        pass

    def CFRunLoopRun(self):
        pass

    def __getattr__(self, name):  # CGPreflight...Access / CGRequest...Access
        if name.startswith("CGPreflight"):
            return lambda: self.granted.get(name, True)
        if name.startswith("CGRequest"):
            return lambda: self.requested.append(name)
        raise AttributeError(name)


class FakeScreenshot:
    def __init__(self, w, h):  # Retina: two pixels per point
        self.pixels = np.full((h * 2, w * 2, 4), 200, np.uint8)

    def __array__(self, dtype=None, copy=None):
        return self.pixels


class FakeMss:
    monitors = [{}, {"left": 0, "top": 0, "width": 1440, "height": 900}]

    def grab(self, box):
        return FakeScreenshot(box["width"], box["height"])


class MacIOTest(unittest.TestCase):
    def setUp(self):
        self.Q = FakeQuartz()
        self.saved = {name: sys.modules.get(name) for name in ("mss", "Quartz")}
        sys.modules["mss"] = types.SimpleNamespace(mss=FakeMss)
        sys.modules["Quartz"] = self.Q
        self.io = npc_lock.MacIO()

    def tearDown(self):
        for name, module in self.saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_screenshots_have_one_pixel_per_point(self):
        self.assertEqual(self.io.screen_size, (1440, 900))
        self.assertEqual(self.io.grab(10, 20, 300, 40).shape, (40, 300))

    def test_knows_when_roblox_is_in_front(self):
        menu_bar = {"kCGWindowLayer": 25, "kCGWindowOwnerName": "Control Center"}
        self.Q.windows = [menu_bar, {"kCGWindowLayer": 0, "kCGWindowOwnerName": "Roblox"}]
        self.assertTrue(self.io.roblox_in_front())
        self.io.front_checked = 0
        self.Q.windows = [menu_bar, {"kCGWindowLayer": 0, "kCGWindowOwnerName": "Terminal"},
                          {"kCGWindowLayer": 0, "kCGWindowOwnerName": "Roblox"}]
        self.assertFalse(self.io.roblox_in_front())

    def test_taps_an_arrow_key(self):
        self.io.tap_arrow(npc_lock.RIGHT_ARROW, 0.001)
        self.assertEqual([(e["code"], e["down"]) for e in self.Q.posted], [(124, True), (124, False)])
        for event in self.Q.posted:  # keeps existing flags, adds the arrow-key ones
            self.assertEqual(event["flags"], 0x100 | npc_lock.ARROW_FLAGS)

    def test_moves_the_mouse_in_small_steps(self):
        self.io.move_mouse(-95)
        self.assertEqual([e["fields"][self.Q.kCGMouseEventDeltaX] for e in self.Q.posted], [-40, -40, -15])

    def test_lists_and_asks_for_missing_permissions(self):
        self.Q.granted = {"CGPreflightPostEventAccess": False}
        self.assertEqual(self.io.missing_permissions(), ["Accessibility"])
        self.assertEqual(self.Q.requested, ["CGRequestPostEventAccess"])

    def test_hotkeys(self):
        events = queue.Queue()
        self.io.listen({54: "capture", 100: "toggle"}, events)
        tap = self.Q.tap_callback

        def key(code, flags=0, repeat=0):
            fields = {self.Q.kCGKeyboardEventKeycode: code, self.Q.kCGKeyboardEventAutorepeat: repeat}
            return {"fields": fields, "flags": flags, "location": Point(300, 200)}

        tap(None, self.Q.kCGEventFlagsChanged, key(54, flags=0x100010), None)  # right command down
        tap(None, self.Q.kCGEventFlagsChanged, key(55, flags=0x100018), None)  # left command too: not a hotkey
        tap(None, self.Q.kCGEventFlagsChanged, key(54, flags=0x100008), None)  # right command up
        tap(None, self.Q.kCGEventKeyDown, key(100), None)  # F8
        tap(None, self.Q.kCGEventKeyDown, key(100, repeat=1), None)  # F8 held down: ignored
        tap(None, self.Q.kCGEventKeyDown, key(0), None)  # "a": not a hotkey
        received = []
        while not events.empty():
            received.append(events.get())
        self.assertEqual(received, [("capture", 300, 200), ("toggle", 300, 200)])


if __name__ == "__main__":
    unittest.main()
