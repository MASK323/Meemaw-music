"""Minimal pure-Python QR encoder used for account login without extra deps."""

from __future__ import annotations

from typing import List, Tuple


def _gf_mul(a: int, b: int) -> int:
    result = 0
    while b:
        if b & 1:
            result ^= a
        a <<= 1
        if a & 0x100:
            a ^= 0x11D
        b >>= 1
    return result


def _gf_pow() -> List[int]:
    values = [1]
    for _ in range(254):
        values.append(_gf_mul(values[-1], 2))
    return values


def _gf_log() -> List[int]:
    values = _gf_pow()
    logs = [0] * 256
    for i, value in enumerate(values):
        logs[value] = i
    return logs


_EXP = _gf_pow()
_LOG = _gf_log()


def _gf_inv(value: int) -> int:
    if value == 0:
        return 0
    return _EXP[(255 - _LOG[value]) % 255]


def _generator_poly(degree: int) -> List[int]:
    poly = [1]
    for i in range(degree):
        next_poly = [0] * (len(poly) + 1)
        for j, coeff in enumerate(poly):
            next_poly[j] ^= coeff
            next_poly[j + 1] ^= _gf_mul(coeff, _EXP[i])
        poly = next_poly
    return poly


def _reed_solomon(data: List[int], degree: int) -> List[int]:
    gen = _generator_poly(degree)
    remainder = [0] * degree
    for byte in data:
        factor = byte ^ remainder[0]
        remainder = remainder[1:] + [0]
        for i in range(degree):
            remainder[i] ^= _gf_mul(gen[i + 1], factor)
    return remainder


_ALIGN = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50],
}

# (total codewords, ec codewords per block, number of blocks) for level L
_CAPACITY = {
    1: (26, 7, 1),
    2: (44, 10, 1),
    3: (70, 15, 1),
    4: (100, 20, 1),
    5: (134, 26, 1),
    6: (172, 18, 2),
    7: (196, 20, 2),
    8: (242, 24, 2),
    9: (292, 30, 2),
    10: (346, 18, 4),
}

_MODE_NUMERIC = 0x1
_MODE_ALNUM = 0x2
_MODE_BYTE = 0x4
_MODE_ECI = 0x7


def _bytes_to_bits(data: bytes) -> str:
    return "".join(f"{b:08b}" for b in data)


def _bits_to_bytes(bits: str) -> List[int]:
    bits += "0" * ((8 - len(bits) % 8) % 8)
    return [int(bits[i : i + 8], 2) for i in range(0, len(bits), 8)]


def _choose_version(bit_count: int, error_correction: str = "L") -> int:
    level = {"L": 0, "M": 1, "Q": 2, "H": 3}[error_correction]
    data_bits = {
        1: [152, 128, 104, 72],
        2: [272, 224, 176, 128],
        3: [440, 352, 272, 208],
        4: [640, 512, 384, 288],
        5: [864, 688, 496, 368],
        6: [1088, 864, 608, 480],
        7: [1248, 992, 704, 528],
        8: [1552, 1232, 880, 688],
        9: [1856, 1456, 1056, 800],
        10: [2192, 1728, 1232, 976],
    }
    for version in range(1, 11):
        if bit_count <= data_bits[version][level]:
            return version
    raise ValueError("QR data too large")


def _place_finder(matrix: List[List[bool]], row: int, col: int) -> None:
    for r in range(7):
        for c in range(7):
            dark = (
                r in (0, 6)
                or c in (0, 6)
                or (2 <= r <= 4 and 2 <= c <= 4)
            )
            matrix[row + r][col + c] = dark


def _place_align(matrix: List[List[bool]], row: int, col: int) -> None:
    for r in range(-2, 3):
        for c in range(-2, 3):
            matrix[row + r][col + c] = max(abs(r), abs(c)) != 1


def _place_format(matrix: List[List[bool]], bits: int) -> None:
    size = len(matrix)
    positions = []
    # First copy: down the left edge, then across the bottom of the top-left
    # finder.  Bit 0 goes to (0, 8) and the sequence follows module 8 downward.
    for i in range(6):
        positions.append((i, 8))
    positions.append((7, 8))
    positions.append((8, 8))
    positions.append((8, 7))
    for i in range(9, 15):
        positions.append((8, 14 - i))
    # Second copy: down the right edge, then across the bottom row.
    for i in range(7):
        positions.append((size - 1 - i, 8))
    positions.append((size - 8, 8))
    for i in range(8):
        positions.append((8, size - 8 + i))
    for i, (row, col) in enumerate(positions):
        matrix[row][col] = bool((bits >> i) & 1)


def _version_bits(version: int) -> int:
    data = version
    rem = data << 12
    gen = 0x1F25
    for i in range(17, 11, -1):
        if (rem >> (i + 12)) & 1:
            rem ^= gen << i
    return (data << 12) | rem


def _place_version(matrix: List[List[bool]], bits: int) -> None:
    size = len(matrix)
    for i in range(18):
        bit = bool((bits >> i) & 1)
        matrix[(size - 11) + (i % 3)][i // 3] = bit
        matrix[i // 3][(size - 11) + (i % 3)] = bit


def _build_matrix(
    version: int,
    data: List[int],
    mask: int,
    error_correction: str = "L",
) -> List[List[bool]]:
    size = 17 + version * 4
    matrix = [[False] * size for _ in range(size)]

    _place_finder(matrix, 0, 0)
    _place_finder(matrix, 0, size - 7)
    _place_finder(matrix, size - 7, 0)

    for i in range(8, size - 8):
        matrix[6][i] = i % 2 == 0
        matrix[i][6] = i % 2 == 0

    positions = _ALIGN[version]
    for r in positions:
        for c in positions:
            if (r, c) in ((6, 6), (6, size - 7), (size - 7, 6)):
                continue
            _place_align(matrix, r, c)

    matrix[size - 8][8] = True

    # reserve format/version function modules
    for i in range(9):
        for row, col in (
            (8, i),
            (i, 8),
            (size - 1 - i, 8),
            (8, size - 1 - i),
        ):
            if 0 <= row < size and 0 <= col < size:
                matrix[row][col] = False
    if version >= 7:
        for r in range(3):
            for c in range(6):
                matrix[size - 11 + r][c] = False
                matrix[c][size - 11 + r] = False

    data_bits = "".join(f"{b:08b}" for b in data)
    bit_index = 0
    upward = True
    col = size - 1
    while col > 0:
        if col == 6:
            col -= 1
        rows = list(range(size)) if upward else list(range(size - 1, -1, -1))
        for row in rows:
            for offset in (0, 1):
                c = col - offset
                if c < 0 or matrix[row][c]:
                    continue
                if bit_index < len(data_bits):
                    matrix[row][c] = data_bits[bit_index] == "1"
                    bit_index += 1
        upward = not upward
        col -= 2

    _place_format(matrix, _format_bits(error_correction, mask))
    if version >= 7:
        _place_version(matrix, _version_bits(version))
    return matrix


def _format_bits(error_correction: str, mask: int) -> int:
    levels = {"L": 1, "M": 0, "Q": 3, "H": 2}
    data = (levels[error_correction] << 3) | mask
    rem = data << 10
    gen = 0x537
    for i in range(14, 9, -1):
        if (rem >> (i + 10)) & 1:
            rem ^= gen << i
    return ((data << 10) | rem) ^ 0x5412


def _is_function(matrix: List[List[bool]], row: int, col: int) -> bool:
    size = len(matrix)
    if row < 9 and col < 9:
        return True
    if row < 9 and col >= size - 8:
        return True
    if row >= size - 8 and col < 9:
        return True
    if row == 6 or col == 6:
        return True
    if row == 8 or col == 8:
        return True
    return False


def _mask_condition(mask: int, row: int, col: int) -> bool:
    if mask == 0:
        return (row + col) % 2 == 0
    if mask == 1:
        return row % 2 == 0
    if mask == 2:
        return col % 3 == 0
    if mask == 3:
        return (row + col) % 3 == 0
    if mask == 4:
        return (row // 2 + col // 3) % 2 == 0
    if mask == 5:
        return ((row * col) % 2) + ((row * col) % 3) == 0
    if mask == 6:
        return (((row * col) % 2) + ((row * col) % 3)) % 2 == 0
    return (((row + col) % 2) + ((row * col) % 3)) % 2 == 0


def _penalty(matrix: List[List[bool]]) -> int:
    size = len(matrix)
    penalty = 0

    def runs(values) -> int:
        total = 0
        current = 1
        for i in range(1, len(values)):
            if values[i] == values[i - 1]:
                current += 1
            else:
                if current >= 5:
                    total += 3 + current - 5
                current = 1
        if current >= 5:
            total += 3 + current - 5
        return total

    for row in range(size):
        penalty += runs(matrix[row])
    for col in range(size):
        penalty += runs([matrix[row][col] for row in range(size)])

    for row in range(size - 1):
        for col in range(size - 1):
            if (
                matrix[row][col]
                == matrix[row][col + 1]
                == matrix[row + 1][col]
                == matrix[row + 1][col + 1]
            ):
                penalty += 3

    pattern = [True, False, True, True, True, False, True, False, False, False, False]
    for row in range(size):
        for i in range(size - 10):
            window = matrix[row][i : i + 11]
            if window == pattern or window == pattern[::-1]:
                penalty += 40
    for col in range(size):
        values = [matrix[row][col] for row in range(size)]
        for i in range(size - 10):
            window = values[i : i + 11]
            if window == pattern or window == pattern[::-1]:
                penalty += 40

    dark = sum(sum(row) for row in matrix)
    percent = dark * 100 // (size * size)
    penalty += min(abs(percent - 50) // 5, 20) * 10
    return penalty


def _apply_mask(matrix: List[List[bool]], mask: int) -> List[List[bool]]:
    size = len(matrix)
    result = [list(row) for row in matrix]
    for row in range(size):
        for col in range(size):
            if not _is_function(result, row, col) and _mask_condition(mask, row, col):
                result[row][col] = not result[row][col]
    return result


def encode_qr(text: str, error_correction: str = "L") -> Tuple[int, List[List[bool]]]:
    """Return (version, boolean matrix including quiet zone)."""
    eci_bits = f"{_MODE_ECI:04b}" + "000010" + "00011010"  # ECI 26 = UTF-8
    body = text.encode("utf-8")
    bits = eci_bits + f"{_MODE_BYTE:04b}" + f"{len(body):08b}" + _bytes_to_bits(body)
    version = _choose_version(len(bits), error_correction)
    total, ec_per_block, block_count = _CAPACITY[version]
    data_words_total = total - ec_per_block * block_count
    capacity_bits = data_words_total * 8
    bits += "0000"
    bits = bits[:capacity_bits]
    bits += "0" * ((8 - len(bits) % 8) % 8)
    data_words = _bits_to_bytes(bits)
    pad = 0xEC
    while len(data_words) < data_words_total:
        data_words.append(pad)
        pad = 0x11 if pad == 0xEC else 0xEC

    data_per_block = data_words_total // block_count
    blocks: List[List[int]] = []
    ec_blocks: List[List[int]] = []
    for i in range(block_count):
        block_data = data_words[i * data_per_block : (i + 1) * data_per_block]
        blocks.append(block_data)
        ec_blocks.append(_reed_solomon(block_data, ec_per_block))

    final_words: List[int] = []
    for i in range(data_per_block):
        for block in blocks:
            final_words.append(block[i])
    for i in range(ec_per_block):
        for block in ec_blocks:
            final_words.append(block[i])

    best = None
    best_penalty = None
    for mask in range(8):
        candidate = _apply_mask(
            _build_matrix(version, final_words, mask, error_correction),
            mask,
        )
        score = _penalty(candidate)
        if best_penalty is None or score < best_penalty:
            best = candidate
            best_penalty = score
    if best is None:
        raise ValueError("QR encode failed")

    quiet = 4
    size = len(best) + quiet * 2
    matrix = [[False] * size for _ in range(size)]
    for row in range(len(best)):
        for col in range(len(best)):
            matrix[row + quiet][col + quiet] = best[row][col]
    return version, matrix


def render_qr_pixmap(text: str, target_px: int = 240):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

    version, matrix = encode_qr(text, "L")
    modules = len(matrix)
    scale = max(1, target_px // modules)
    size = modules * scale
    image = QImage(size, size, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillRect(0, 0, size, size, QColor("#ffffff"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#111111"))
    for row in range(modules):
        for col in range(modules):
            if matrix[row][col]:
                painter.fillRect(
                    col * scale,
                    row * scale,
                    scale,
                    scale,
                    QColor("#111111"),
                )
    painter.end()
    return QPixmap.fromImage(image)
