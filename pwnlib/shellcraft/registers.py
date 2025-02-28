from __future__ import absolute_import
from __future__ import division

import re

from pwnlib.context import context
from pwnlib.util.misc import register_sizes

mips = {
    '$0' :  0, '$zero': 0,
    '$1' :  1, '$at':  1,
    '$2' :  2, '$v0':  2,
    '$3' :  3, '$v1':  3,
    '$4' :  4, '$a0':  4,
    '$5' :  5, '$a1':  5,
    '$6' :  6, '$a2':  6,
    '$7' :  7, '$a3':  7,
    '$8' :  8, '$t0':  8,
    '$9' :  9, '$t1':  9,
    '$10': 10, '$t2': 10,
    '$11': 11, '$t3': 11,
    '$12': 12, '$t4': 12,
    '$13': 13, '$t5': 13,
    '$14': 14, '$t6': 14,
    '$15': 15, '$t7': 15,
    '$16': 16, '$s0': 16,
    '$17': 17, '$s1': 17,
    '$18': 18, '$s2': 18,
    '$19': 19, '$s3': 19,
    '$20': 20, '$s4': 20,
    '$21': 21, '$s5': 21,
    '$22': 22, '$s6': 22,
    '$23': 23, '$s7': 23,
    '$24': 24, '$t8': 24,
    '$25': 25, '$t9': 25,
    '$26': 26, '$k0': 26,
    '$27': 27, '$k1': 27,
    '$28': 28, '$gp': 28,
    '$29': 29, '$sp': 29,
    '$30': 30, '$s8': 30,
    '$31': 31, '$ra': 31,
}

mips_list = list(mips)

arm = list(map('r{}'.format, range(13)))
arm += ["sp", "lr", "pc", "cpsr"]

thumb = arm

aarch64 = list(map('x{}'.format, range(32)))
aarch64 += ["sp", "lr", "pc", "cpsr"]

i386_baseregs = [ "ax", "cx", "dx", "bx", "sp", "bp", "si", "di", "ip"]

i386 = list(map('e{}'.format, i386_baseregs))
i386 += i386_baseregs
i386 += [ "eflags", "cs", "ss", "ds", "es", "fs", "gs", ]

amd64 =  list(map('r{}'.format, i386_baseregs))
amd64 += list(map('r{}'.format, range(8,16)))
amd64 += list(map('r{}d'.format, range(8,16)))
amd64 += i386

powerpc =  list(map('r{}'.format, range(32)))
powerpc += ["pc", "msr", "cr", "lr", "ctr", "xer", "orig_r3", "trap" ]
powerpc =  list(map('%{}'.format, powerpc))

sparc =  list(map('g{}'.format, range(8)))
sparc += list(map('o{}'.format, range(5)))
sparc += list(map('l{}'.format, range(8)))
sparc += list(map('i{}'.format, range(5)))
sparc += ["pc", "sp", "fp", "psr" ]
sparc =  list(map('%{}'.format, sparc))

riscv = {
    'x0' :  0, 'zero': 0,
    'x1' :  1, 'ra':  1,
    'x2' :  2, 'sp':  2,
    'x3' :  3, 'gp':  3,
    'x4' :  4, 'tp':  4,
    'x5' :  5, 't0':  5,
    'x6' :  6, 't1':  6,
    'x7' :  7, 't2':  7,
    'x8' :  8, 's0':  8, 'fp':  8,
    'x9' :  9, 's1':  9,
    'x10': 10, 'a0': 10,
    'x11': 11, 'a1': 11,
    'x12': 12, 'a2': 12,
    'x13': 13, 'a3': 13,
    'x14': 14, 'a4': 14,
    'x15': 15, 'a5': 15,
    'x16': 16, 'a6': 16,
    'x17': 17, 'a7': 17,
    'x18': 18, 's2': 18,
    'x19': 19, 's3': 19,
    'x20': 20, 's4': 20,
    'x21': 21, 's5': 21,
    'x22': 22, 's6': 22,
    'x23': 23, 's7': 23,
    'x24': 24, 's8': 24,
    'x25': 25, 's9': 25,
    'x26': 26, 's10': 26,
    'x27': 27, 's11': 27,
    'x28': 28, 't3': 28,
    'x29': 29, 't4': 29,
    'x30': 30, 't5': 30,
    'x31': 31, 't6': 31,
}

riscv_list = list(riscv)

loongarch64 = {
    'r0' :  0, 'zero': 0,
    'r1' :  1, 'ra':  1,
    'r2' :  2, 'tp':  2,
    'r3' :  3, 'sp':  3,
    'r4' :  4, 'a0':  4, 'v0':  4,
    'r5' :  5, 'a1':  5, 'v1':  5,
    'r6' :  6, 'a2':  6,
    'r7' :  7, 'a3':  7,
    'r8' :  8, 'a4':  8,
    'r9' :  9, 'a5':  9,
    'r10': 10, 'a6': 10,
    'r11': 11, 'a7': 11,
    'r12': 12, 't0': 12,
    'r13': 13, 't1': 13,
    'r14': 14, 't2': 14,
    'r15': 15, 't3': 15,
    'r16': 16, 't4': 16,
    'r17': 17, 't5': 17,
    'r18': 18, 't6': 18,
    'r19': 19, 't7': 19,
    'r20': 20, 't8': 20,
    'r21': 21, 'u0': 21, # u0 is only used by Linux kernel
    'r22': 22, 'fp': 22, 's9': 22,
    'r23': 23, 's0': 23,
    'r24': 24, 's1': 24,
    'r25': 25, 's2': 25,
    'r26': 26, 's3': 26,
    'r27': 27, 's4': 27,
    'r28': 28, 't5': 28,
    'r29': 29, 't6': 29,
    'r30': 30, 't7': 30,
    'r31': 31, 't8': 31,
}

loongarch64_list = list(loongarch64)

# x86/amd64 registers in decreasing size
i386_ordered = [
    ['rax', 'eax', 'ax', 'al'],
    ['rbx', 'ebx', 'bx', 'bl'],
    ['rcx', 'ecx', 'cx', 'cl'],
    ['rdx', 'edx', 'dx', 'dl'],
    ['rdi', 'edi', 'di'],
    ['rsi', 'esi', 'si'],
    ['rbp', 'ebp', 'bp'],
    ['rsp', 'esp', 'sp'],
    ['r8', 'r8d', 'r8w', 'r8b'],
    ['r9', 'r9d', 'r9w', 'r9b'],
    ['r10', 'r10d', 'r10w', 'r10b'],
    ['r11', 'r11d', 'r11w', 'r11b'],
    ['r12', 'r12d', 'r12w', 'r12b'],
    ['r13', 'r13d', 'r13w', 'r13b'],
    ['r14', 'r14d', 'r14w', 'r14b'],
    ['r15', 'r15d', 'r15w', 'r15b']
]

all_regs, sizes, bigger, smaller = register_sizes(i386_ordered, [64, 32, 16, 8, 8])
native64 = {k:v[0] for k,v in bigger.items()}
native32 = {k:v[1] for k,v in bigger.items() if not k.startswith('r')}

class Register(object):
    #: Register name
    name = None

    #: List of larger registers, in order from largest to smallest
    bigger = None

    #: List of smaller regsters, in order from smallest to largest
    smaller = None

    #: Size of the register, in bits
    size = None

    #: Does this register have a 'high' register for mask 0xff00
    ff00 = None

    #: Flags for 64-bit mode.64-bit
    #: The first bit is set, if the register can be used with a REX-mode
    #: The second bit is set, if the register can be used without a REX-prefix
    rex_mode = 0

    #: Is this a 64-bit only register?
    is64bit = False

    #: Name of the native 64-bit register
    native64 = None

    #: Name of the native 32-bit register
    native32 = None

    #: Name of the register which should be used to clear
    #: this register, e.g. xor REG, REG.
    #: Useful for AMD64 for xor eax, eax is shorter than
    #: xor rax, rax and has the same effect.
    xor = None

    def __init__(self, name, size):
        self.name = name
        self.size = size

        for row in i386_ordered:
            if name in row:
                self.bigger  = row[0:row.index(name)]
                self.smaller = row[row.index(name)+1:]
                self.sizes   = {64>>i:r for i,r in enumerate(row)}
                self.native64 = row[0]
                self.native32 = row[1]
                self.xor = self.sizes[min(self.size, 32)]

        if self.size >= 32 and name.endswith('x'):
            self.ff00 = name[1] + 'h'

        if name[-1] != 'h':
            self.rex_mode |= 1

        if name[0] != 'r':
            self.rex_mode |= 2

        if name.startswith('r') or name[1:3].isdigit():
            self.is64bit = True

    @property
    def bits(self):
        return self.size

    @property
    def bytes(self):
        return self.bits // 8

    def fits(self, value):
        return self.size >= bits_required(value)

    def __str__(self):
        return self.name

    def __repr__(self):
        return "Register(%r)" % self.name

intel = {}

for row in i386_ordered:
    for i, reg in enumerate(row):
        intel[reg] = Register(reg, 64 >> i)

def get_register(name):
    if isinstance(name, Register):
        return name
    if isinstance(name, str):
        return intel.get(name, None)
    return None

def is_register(obj):
    if isinstance(obj, Register):
        return True
    return get_register(obj)


def bits_required(value):
    bits  = 0

    if value < 0:
        value = -(value)

    while value:
        value >>= 8
        bits += 8
    return bits

def current():
    return {
        'i386': i386,
        'amd64': amd64,
        'arm': arm,
        'thumb': arm,
        'aarch64': aarch64,
        'mips': mips_list,
        'powerpc': powerpc,
        'riscv32': riscv,
        'riscv64': riscv,
        'loongarch64': loongarch64,
    }[context.arch]

# def is_register(sz):
#     try:
#         sz = sz.lower()
#         return sz.lower() in {
#         'i386': i386,
#         'amd64': amd64,
#         'powerpc': powerpc,
#         'sparc': sparc,
#         'arm': arm,
#         'aarch64': arm,
#         'thumb': arm,
#         'mips': mips,
#         'mips64': mips
#         }[context.arch]
#     except:
#         return False

def register_size(reg):
    return sizes[reg]

def fits_in_register(reg, value):
    return register_size(reg) >= bits_required(value)
