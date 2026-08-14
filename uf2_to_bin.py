#!/usr/bin/env python3
"""Convert a UF2 file to a flat raw binary, starting at the lowest target address."""
import sys
import struct

MAGIC0 = 0x0A324655
MAGIC1 = 0x9E5D5157
MAGICE = 0x0AB16F30


def convert(uf2_path, bin_path):
    blocks = []
    with open(uf2_path, "rb") as f:
        data = f.read()

    if len(data) % 512 != 0:
        print(f"[-] Warning: file size {len(data)} is not a multiple of 512")

    n = len(data) // 512
    for i in range(n):
        block = data[i * 512:(i + 1) * 512]
        magic0, magic1, flags, target_addr, payload_size, block_no, num_blocks, file_size = \
            struct.unpack_from("<IIIIIIII", block, 0)
        magic_end = struct.unpack_from("<I", block, 508)[0]
        if magic0 != MAGIC0 or magic1 != MAGIC1 or magic_end != MAGICE:
            print(f"[-] Block {i}: bad magic, skipping")
            continue
        payload = block[32:32 + payload_size]
        blocks.append((target_addr, payload))

    if not blocks:
        print("[-] No valid UF2 blocks found")
        sys.exit(1)

    blocks.sort(key=lambda b: b[0])
    base = blocks[0][0]
    end = max(addr + len(payload) for addr, payload in blocks)
    size = end - base

    buf = bytearray([0xFF]) * size
    for addr, payload in blocks:
        offset = addr - base
        buf[offset:offset + len(payload)] = payload

    with open(bin_path, "wb") as f:
        f.write(buf)

    print(f"[+] {len(blocks)} blocks parsed")
    print(f"[+] Address range: 0x{base:08X} - 0x{end:08X} ({size} bytes)")
    print(f"[+] Wrote {bin_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: uf2_to_bin.py <input.uf2> <output.bin>")
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
