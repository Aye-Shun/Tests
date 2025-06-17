# Tests

This repository now contains an expanded Game Boy emulator skeleton written in Python.  The emulator implements a small but growing subset of CPU instructions using an opcode table and helper methods for registers and flags.

## Usage

Run the emulator with a Game Boy ROM file:

```bash
python gameboy.py path/to/rom.gb
```

Execution stops when an unimplemented opcode is reached or when a HALT instruction is executed.  See `gameboy_old.py` for the earlier minimal version.
