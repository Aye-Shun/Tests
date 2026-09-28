# GPO NPC Lock-On (macOS)

Keeps your camera pointed at the NPC you're fighting in Grand Piece Online, so you don't lose sight of it.

**What it does:** takes screenshots, finds the NPC's name tag, and taps the Left/Right arrow keys (Roblox's normal camera-turn keys) to keep the tag in the middle of the screen. It pauses whenever Roblox isn't the app in front.

**What it doesn't do:** it doesn't inject anything into Roblox, read the game's memory, or change any game files. It doesn't attack, move or farm for you. It only follows the one name tag you capture.

> **Status:** the tracking has been tested against a simulated Roblox camera, not in GPO itself yet, so expect to tweak a setting or two.

## Setup (once)

1. Put this folder somewhere easy to find, like your Desktop.
2. Open **Terminal** (press Command-Space, type `Terminal`, press Return).
3. Type `cd ` (with a space after it), drag this folder onto the Terminal window, and press Return.
4. Install what it needs:
   ```
   python3 -m pip install -r requirements.txt
   ```
   If your Mac offers to install "command line developer tools", click Install, wait for it to finish, then run that line again.
5. Start it:
   ```
   python3 npc_lock.py
   ```
   The first time, macOS asks for permission. Open **System Settings → Privacy & Security** and turn on **Terminal** under:
   - **Screen Recording** (called "Screen & System Audio Recording" on newer macOS), so it can see the name tag
   - **Accessibility**, so it can press the arrow keys
   - **Input Monitoring**, so it can notice its hotkeys

   Then quit Terminal completely (Command-Q), open it again, do step 3 again, and run `python3 npc_lock.py`.

## Using it

1. Run `python3 npc_lock.py`, then switch to Roblox.
2. **Capture the NPC's name tag.** Turn Shift Lock off so you can move your pointer. Point at the top-left corner of the NPC's name tag and press **Right Command**. Then point at the bottom-right corner and press **Right Command** again.
   - Box the whole tag, tightly, including a level like "[Lv. 50]" if it has one.
   - Do it from about the distance you usually fight at.
3. Press **Right Option** to turn lock-on on. Press it again to turn it off. Shift Lock can be on or off.
4. To quit, click the Terminal window and press **Control-C**.

It remembers the last name tag you captured. To farm a different NPC, capture its tag. The Terminal window tells you what it's doing ("Lock-on ON", "Lost the NPC", and so on).

## If something's off

The settings are at the top of `npc_lock.py`. Open it in TextEdit, change the value, save, and restart the script.

| Problem | Try |
|---|---|
| The camera doesn't turn at all | `USE_MOUSE = True`, and turn Shift Lock on |
| The camera turns away from the NPC | `REVERSE = True` |
| The camera wobbles back and forth | Lower `TURN_STRENGTH`, e.g. `0.5` |
| It says "Lost the NPC" while the NPC is on screen | Capture the tag again, more tightly, or lower `MATCH_THRESHOLD` to `0.5` |
| It loses the NPC when it's knocked far back or comes very close | Some name tags change size with distance, and matching is fussy about size. Capture from your usual fighting distance |
| It follows something that isn't the NPC | Raise `MATCH_THRESHOLD` to `0.7`, and include more of the tag when you capture |
| Right Command or Right Option already do something for you | Change `CAPTURE_KEY` / `TOGGLE_KEY` (the choices are in `KEY_CODES`). Keep the straight quotes: if TextEdit turns them curly, switch off Edit → Substitutions → Smart Quotes |

Good to know:

- It only sees your main display.
- Turn lock-on off before typing in the chat, since it presses the arrow keys.
- It can't tell NPCs from players by itself. It follows whatever name tag you capture, so only capture NPC names. If a player's name contains the NPC's name (like "MarineFan" and "Marine"), it could follow that player. Capturing the whole tag, level included, makes that much less likely.
- NPCs whose names differ by only a letter can get mixed up.

## Tests

`python3 -m unittest test_npc_lock.py` runs the tracking against a simulated Roblox camera (one that circles your character like the real one), and the Mac-specific parts against stand-ins for macOS's libraries. It doesn't need a Mac or Roblox, just `numpy` and `opencv-python`.
