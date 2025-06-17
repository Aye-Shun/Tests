# Expanded Game Boy emulator skeleton

FLAG_Z = 0x80
FLAG_N = 0x40
FLAG_H = 0x20
FLAG_C = 0x10


class CPU:
    """A more complete Game Boy CPU skeleton."""

    def __init__(self):
        # 8-bit registers
        self.A = 0
        self.F = 0
        self.B = 0
        self.C = 0
        self.D = 0
        self.E = 0
        self.H = 0
        self.L = 0
        # 16-bit registers
        self.SP = 0
        self.PC = 0
        # 64KB memory
        self.memory = bytearray(0x10000)
        # build opcode table
        self.opcodes = [self._unimplemented] * 0x100
        self._build_table()

    # Helper methods for combined registers
    def _get_bc(self):
        return (self.B << 8) | self.C

    def _set_bc(self, value):
        self.B = (value >> 8) & 0xFF
        self.C = value & 0xFF

    def _get_de(self):
        return (self.D << 8) | self.E

    def _set_de(self, value):
        self.D = (value >> 8) & 0xFF
        self.E = value & 0xFF

    def _get_hl(self):
        return (self.H << 8) | self.L

    def _set_hl(self, value):
        self.H = (value >> 8) & 0xFF
        self.L = value & 0xFF

    # Flag helpers
    def _set_flag(self, flag, condition):
        if condition:
            self.F |= flag
        else:
            self.F &= ~flag & 0xFF

    def _get_flag(self, flag):
        return 1 if (self.F & flag) else 0

    # Memory helpers
    def load_rom(self, data, start=0x0000):
        self.memory[start:start + len(data)] = data
        self.PC = start

    def read_byte(self, addr):
        return self.memory[addr]

    def write_byte(self, addr, value):
        self.memory[addr] = value & 0xFF

    def read_word(self, addr):
        lo = self.read_byte(addr)
        hi = self.read_byte((addr + 1) & 0xFFFF)
        return lo | (hi << 8)

    def write_word(self, addr, value):
        self.write_byte(addr, value & 0xFF)
        self.write_byte((addr + 1) & 0xFFFF, (value >> 8) & 0xFF)

    # Opcode table setup
    def _build_table(self):
        self.opcodes[0x00] = self._op_nop
        self.opcodes[0x01] = self._op_ld_bc_d16
        self.opcodes[0x02] = self._op_ld_bc_a
        self.opcodes[0x03] = self._op_inc_bc
        self.opcodes[0x04] = self._op_inc_b
        self.opcodes[0x05] = self._op_dec_b
        self.opcodes[0x06] = self._op_ld_b_d8
        self.opcodes[0x07] = self._op_rlca
        self.opcodes[0x0E] = self._op_ld_c_d8
        self.opcodes[0x76] = self._op_halt
        self.opcodes[0xAF] = self._op_xor_a
        self.opcodes[0xC3] = self._op_jp_a16
        self.opcodes[0xC9] = self._op_ret
        self.opcodes[0xCD] = self._op_call_a16

    # Opcode implementations
    def _op_nop(self):
        pass

    def _op_ld_bc_d16(self):
        value = self.read_word(self.PC)
        self.PC = (self.PC + 2) & 0xFFFF
        self._set_bc(value)

    def _op_ld_bc_a(self):
        self.write_byte(self._get_bc(), self.A)

    def _op_inc_bc(self):
        self._set_bc((self._get_bc() + 1) & 0xFFFF)

    def _op_inc_b(self):
        value = (self.B + 1) & 0xFF
        self._set_flag(FLAG_Z, value == 0)
        self._set_flag(FLAG_N, False)
        self._set_flag(FLAG_H, (self.B & 0x0F) + 1 > 0x0F)
        self.B = value

    def _op_dec_b(self):
        value = (self.B - 1) & 0xFF
        self._set_flag(FLAG_Z, value == 0)
        self._set_flag(FLAG_N, True)
        self._set_flag(FLAG_H, (self.B & 0x0F) == 0)
        self.B = value

    def _op_ld_b_d8(self):
        self.B = self.read_byte(self.PC)
        self.PC = (self.PC + 1) & 0xFFFF

    def _op_rlca(self):
        carry = (self.A >> 7) & 1
        self.A = ((self.A << 1) | carry) & 0xFF
        self._set_flag(FLAG_Z, False)
        self._set_flag(FLAG_N, False)
        self._set_flag(FLAG_H, False)
        self._set_flag(FLAG_C, carry)

    def _op_ld_c_d8(self):
        self.C = self.read_byte(self.PC)
        self.PC = (self.PC + 1) & 0xFFFF

    def _op_halt(self):
        return False

    def _op_xor_a(self):
        self.A ^= self.A
        self._set_flag(FLAG_Z, self.A == 0)
        self._set_flag(FLAG_N, False)
        self._set_flag(FLAG_H, False)
        self._set_flag(FLAG_C, False)

    def _op_jp_a16(self):
        addr = self.read_word(self.PC)
        self.PC = addr

    def _op_ret(self):
        lo = self.read_byte(self.SP)
        hi = self.read_byte((self.SP + 1) & 0xFFFF)
        self.SP = (self.SP + 2) & 0xFFFF
        self.PC = lo | (hi << 8)

    def _op_call_a16(self):
        addr = self.read_word(self.PC)
        self.PC = (self.PC + 2) & 0xFFFF
        self.SP = (self.SP - 2) & 0xFFFF
        self.write_word(self.SP, self.PC)
        self.PC = addr

    def _unimplemented(self):
        opcode = self.read_byte((self.PC - 1) & 0xFFFF)
        raise NotImplementedError(f"Opcode {opcode:02X} not implemented")

    # Execution
    def step(self):
        opcode = self.read_byte(self.PC)
        self.PC = (self.PC + 1) & 0xFFFF
        result = self.opcodes[opcode]()
        if result is False:
            return False
        return True

    def run(self, max_cycles=10**6):
        cycles = 0
        running = True
        while running and cycles < max_cycles:
            running = self.step()
            cycles += 1


def load_file(path):
    with open(path, 'rb') as f:
        return f.read()


def main(path):
    cpu = CPU()
    rom = load_file(path)
    cpu.load_rom(rom)
    try:
        cpu.run()
    except NotImplementedError as e:
        print(e)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python gameboy.py <rom_file>")
    else:
        main(sys.argv[1])
