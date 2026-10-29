"""shotdiff.py: measure which regions changed between two window screenshots.

    python shotdiff.py before.png after.png [--box NAME=L,T,R,B ...]
                       [--grid COLSxROWS] [--threshold 24] [--out diff.png]

For each named box (window pixel coordinates, read off the screenshot) it
prints the share of pixels whose color changed by more than the threshold
(0 to 255, largest channel difference). Use it to confirm that a marking
changed every visual it should and none it should not. --grid prints the
same share for a grid of cells over the whole image. --out writes the after
image with changed pixels tinted red and the boxes outlined.

Needs Pillow. Exit code 0; 2 for bad input.
"""
import argparse
import sys

try:
    from PIL import Image, ImageChops, ImageDraw
except ImportError:
    sys.exit("shotdiff needs Pillow (pip install pillow)")


def parse_box(text):
    name, _, coords = text.partition("=")
    parts = [int(float(v)) for v in coords.split(",")]
    if not name or len(parts) != 4:
        raise ValueError("box must be NAME=L,T,R,B, got %r" % text)
    return name, tuple(parts)


def change_mask(before, after, threshold=24):
    """1-bit style mask (L mode, 255 = changed) of two same-size images."""
    if before.size != after.size:
        raise ValueError("images differ in size: %s vs %s"
                         % (before.size, after.size))
    diff = ImageChops.difference(before.convert("RGB"), after.convert("RGB"))
    channels = diff.split()
    largest = ImageChops.lighter(ImageChops.lighter(channels[0],
                                                    channels[1]),
                                 channels[2])
    return largest.point(lambda v: 255 if v > threshold else 0)


def changed_share(mask, box):
    region = mask.crop(box)
    total = region.size[0] * region.size[1]
    if total == 0:
        return 0.0
    return region.histogram()[255] / float(total)


def compare(before_path, after_path, boxes, threshold=24):
    before = Image.open(before_path)
    after = Image.open(after_path)
    mask = change_mask(before, after, threshold)
    return mask, {name: changed_share(mask, box) for name, box in boxes}


def grid_shares(mask, cols, rows):
    width, height = mask.size
    out = []
    for r in range(rows):
        line = []
        for c in range(cols):
            box = (c * width // cols, r * height // rows,
                   (c + 1) * width // cols, (r + 1) * height // rows)
            line.append(changed_share(mask, box))
        out.append(line)
    return out


def write_overlay(after_path, mask, boxes, out):
    image = Image.open(after_path).convert("RGB")
    red = Image.new("RGB", image.size, (230, 30, 30))
    image = Image.composite(Image.blend(image, red, 0.6), image, mask)
    draw = ImageDraw.Draw(image)
    for name, box in boxes:
        draw.rectangle(box, outline=(20, 90, 220), width=3)
        draw.text((box[0] + 4, box[1] + 4), name, fill=(20, 90, 220))
    image.save(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--box", action="append", default=[])
    parser.add_argument("--grid")
    parser.add_argument("--threshold", type=int, default=24)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        boxes = [parse_box(b) for b in args.box]
        mask, shares = compare(args.before, args.after, boxes,
                               args.threshold)
    except (ValueError, OSError) as exc:
        print("shotdiff: %s" % exc, file=sys.stderr)
        return 2
    total = changed_share(mask, (0, 0) + mask.size)
    print("whole image  %5.1f%% changed" % (total * 100))
    for name, _box in boxes:
        print("%-12s %5.1f%% changed" % (name, shares[name] * 100))
    if args.grid:
        cols, rows = (int(v) for v in args.grid.lower().split("x"))
        for line in grid_shares(mask, cols, rows):
            print(" ".join("%5.1f" % (v * 100) for v in line))
    if args.out:
        write_overlay(args.after, mask, boxes, args.out)
        print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
