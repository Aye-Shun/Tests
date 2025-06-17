# Tests

This repository now contains an expanded Game Boy emulator skeleton written in Python.  The emulator implements a small but growing subset of CPU instructions using an opcode table and helper methods for registers and flags.

## Usage

Run the emulator with a Game Boy ROM file or choose one from the `roms/` folder:

```bash
# run with a specific ROM
python gameboy.py path/to/rom.gb
# or run without arguments and select from `roms/`
python gameboy.py
```

Execution stops when an unimplemented opcode is reached or when a HALT instruction is executed.  See `gameboy_old.py` for the earlier minimal version.

### Controls

The emulator reads simple keyboard input and writes it to the joypad register:

- `w`, `a`, `s`, `d` &ndash; Up, Left, Down, Right
- `z` &ndash; A button
- `x` &ndash; B button
- `SPACE` &ndash; Select
- `ENTER` &ndash; Start
