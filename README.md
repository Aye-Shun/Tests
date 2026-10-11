# Game Boy CPU experiments

An early Python CPU skeleton with registers, flag helpers, a byte array for memory, and a table that dispatches opcodes to methods. A small subset of instructions is implemented. This is incomplete and cannot run Game Boy games.

## Try a short program

Use Python 3; there are no external packages. From this repository, run:

```sh
python3 - <<'PYTHON'
from gameboy import CPU

cpu = CPU()
# Load 42 into B, increment B, then halt.
cpu.load_rom(bytes([0x06, 0x2A, 0x04, 0x76]))
cpu.run()
print(f"B={cpu.B}, PC={cpu.PC}")
PYTHON
```

Expected output:

```text
B=43, PC=4
```

The command-line entry point can also read raw bytes from a file:

```sh
python3 gameboy.py path/to/program.bin
```

It starts at byte zero and runs until HALT, an unsupported opcode, or the instruction limit. Successful runs have no output; unsupported opcodes print a message. Despite the `max_cycles` argument name, the limit counts calls to `step()`, not hardware clock cycles.

## What's implemented

`gameboy.py` contains the whole experiment. The opcode table currently covers NOP, some loads, increments/decrements, RLCA, XOR A, JP, CALL, RET, and HALT. The register-pair and flag helpers can also be called directly while inspecting CPU state.

## What's missing

Most instructions, hardware timing, interrupts, graphics, sound, input, and cartridge banking are absent. Memory is a plain byte array rather than the Game Boy's memory map. There is no boot sequence or ROM validation, so passing a game ROM does not make it playable.

There is no automated test suite or CI. The example above is a small smoke check, not a hardware-accuracy test.
