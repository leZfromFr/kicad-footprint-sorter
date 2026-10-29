r"""Sort the footprints of a KiCad board into a clean grid, grouped by type and in natural order.

Typical use: right after "Update PCB from Schematic", when KiCad drops every footprint in one heap.
Run it with the Python bundled with KiCad:
    "C:\Program Files\KiCad\10.0\bin\python.exe" sort_footprints.py my_board.kicad_pcb --out my_board_sorted.kicad_pcb

More KiCad scripting: https://scriptedpcb.com/en/footprints/
"""
import argparse
import re
import sys

import pcbnew
from pcbnew import FromMM, ToMM, VECTOR2I

# Groups placed first, in this order; any other prefix follows alphabetically.
GROUP_ORDER = ["U", "Q", "J", "P", "K", "Y", "X", "SW", "R", "RN", "C", "L", "FB", "D", "LED", "F", "TP", "H"]


def split_ref(ref):
    """'R10' -> ('R', 10). References without a number sort last in their group."""
    m = re.match(r"([A-Za-z_]+)(\d*)", ref)
    if not m:
        return ref, 0
    prefix, num = m.groups()
    return prefix.upper(), int(num) if num else 10 ** 9


def group_key(prefix):
    return (GROUP_ORDER.index(prefix), "") if prefix in GROUP_ORDER else (len(GROUP_ORDER), prefix)


def board_frame(board):
    """Board outline as (x0, y0, x1, y1) in mm, or None if the board has no Edge.Cuts."""
    box = board.GetBoardEdgesBoundingBox()
    if box.GetWidth() == 0:
        return None
    return ToMM(box.GetLeft()), ToMM(box.GetTop()), ToMM(box.GetRight()), ToMM(box.GetBottom())


def bounding_box(fp):
    """Bounding box including texts. KiCad 8 takes (include_text, include_invisible_text), 9/10 also accept one bool."""
    try:
        return fp.GetBoundingBox(True, False)
    except TypeError:
        return fp.GetBoundingBox(True)


def footprint_box(fp):
    """Footprint extent including its texts, in mm, relative to its anchor."""
    bb = bounding_box(fp)
    pos = fp.GetPosition()
    return (ToMM(bb.GetLeft() - pos.x), ToMM(bb.GetTop() - pos.y), ToMM(bb.GetRight() - pos.x), ToMM(bb.GetBottom() - pos.y))


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def sort_footprints(board, origin, width, gap, row_gap, keep_rotation):
    fps = [fp for fp in board.GetFootprints() if not fp.IsLocked()]
    # locked footprints stay where they are: the grid flows around them
    obstacles = []
    for fp in board.GetFootprints():
        if fp.IsLocked():
            bb = bounding_box(fp)
            obstacles.append((ToMM(bb.GetLeft()) - gap, ToMM(bb.GetTop()) - row_gap,
                              ToMM(bb.GetRight()) + gap, ToMM(bb.GetBottom()) + row_gap))
    groups = {}
    for fp in fps:
        groups.setdefault(split_ref(fp.GetReference())[0], []).append(fp)
    x0, y = origin
    placed = 0
    for prefix in sorted(groups, key=group_key):
        members = sorted(groups[prefix], key=lambda f: split_ref(f.GetReference()))
        if not keep_rotation:
            for fp in members:
                fp.SetOrientationDegrees(0)
        boxes = [footprint_box(fp) for fp in members]
        x, row_h = x0, 0.0
        for fp, (l, t, r, b) in zip(members, boxes):
            w, h = r - l, b - t
            while True:
                if x > x0 and x + w > x0 + width:    # wrap to the next row
                    x, y, row_h = x0, y + row_h + row_gap, 0.0
                hit = next((o for o in obstacles if overlaps((x, y, x + w, y + h), o)), None)
                if hit is None:
                    break
                x = hit[2]                           # jump past the locked footprint
            fp.SetPosition(VECTOR2I(FromMM(x - l), FromMM(y - t)))
            x += w + gap
            row_h = max(row_h, h)
            placed += 1
        y += row_h + row_gap * 2                     # a little more space between groups
    return placed, len(board.GetFootprints()) - len(fps), y - origin[1]


def main():
    ap = argparse.ArgumentParser(description="Sort a KiCad board's footprints into a grid, grouped by type, in natural order.")
    ap.add_argument("board", help="input .kicad_pcb")
    ap.add_argument("--out", help="output .kicad_pcb (default: <input>_sorted.kicad_pcb)")
    ap.add_argument("--origin", help="top-left corner of the grid 'x,y' in mm (default: inside the board outline)")
    ap.add_argument("--width", type=float, help="maximum row width in mm (default: board outline width)")
    ap.add_argument("--gap", type=float, default=1.5, help="horizontal gap between footprints, mm (default 1.5)")
    ap.add_argument("--row-gap", type=float, default=1.5, help="vertical gap between rows, mm (default 1.5)")
    ap.add_argument("--margin", type=float, default=3.0, help="margin inside the board outline, mm (default 3)")
    ap.add_argument("--keep-rotation", action="store_true", help="keep each footprint's current rotation")
    args = ap.parse_args()

    board = pcbnew.LoadBoard(args.board)
    if board is None:
        sys.exit(f"Could not load {args.board} (saved by a newer KiCad version than this Python's?)")
    frame = board_frame(board)
    if args.origin:
        origin = tuple(float(v) for v in args.origin.split(","))
    elif frame:
        origin = (frame[0] + args.margin, frame[1] + args.margin)
    else:
        origin = (100.0, 100.0)
    width = args.width or ((frame[2] - frame[0] - 2 * args.margin) if frame else 150.0)

    placed, locked, height = sort_footprints(board, origin, width, args.gap, args.row_gap, args.keep_rotation)
    out = args.out or re.sub(r"\.kicad_pcb$", "", args.board) + "_sorted.kicad_pcb"
    pcbnew.SaveBoard(out, board)
    note = f", {locked} locked footprint(s) left in place" if locked else ""
    fits = "" if not frame or height <= frame[3] - frame[1] - args.margin else "  (grid is taller than the board outline!)"
    print(f"{placed} footprints sorted{note} -> {out}{fits}")


if __name__ == "__main__":
    main()
