"""redact.py: crop and redact screenshots before they leave the machine.

    python redact.py apply in.png out.png [--pixelate L,T,R,B ...]
                     [--fill L,T,R,B ...] [--color #FFFFFF] [--block 9]
                     [--crop L,T,R,B]
    python redact.py combine out.png a.png b.png [c.png ...] [--gap 24]

apply: boxes are pixel coordinates of the input image. Pixelate and fill
run first, the crop last, so every box uses the same coordinates as the
screenshot you read them from. Pixelate blurs a name or avatar beyond
reading; fill paints a solid block (use it for anything that must not be
recoverable, such as a server address or a token).

combine: places images side by side on a white background, centred
vertically (for example a dialog next to its result).

Needs Pillow.
"""
import argparse
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("redact needs Pillow (pip install pillow)")


def box_of(text):
    parts = [int(float(v)) for v in text.split(",")]
    if len(parts) != 4 or parts[0] >= parts[2] or parts[1] >= parts[3]:
        raise argparse.ArgumentTypeError("box must be L,T,R,B with L<R, T<B")
    return tuple(parts)


def pixelate(image, box, block=9):
    region = image.crop(box)
    width, height = region.size
    small = region.resize((max(1, width // block), max(1, height // block)),
                          Image.BILINEAR)
    image.paste(small.resize((width, height), Image.NEAREST), box)


def apply(args):
    image = Image.open(args.input).convert("RGB")
    for box in args.pixelate or []:
        pixelate(image, box, args.block)
    draw = ImageDraw.Draw(image)
    for box in args.fill or []:
        draw.rectangle(box, fill=args.color)
    if args.crop:
        image = image.crop(args.crop)
    image.save(args.output)
    print("%s %dx%d" % (args.output, image.size[0], image.size[1]))


def combine(args):
    images = [Image.open(p).convert("RGB") for p in args.images]
    width = sum(i.size[0] for i in images) + args.gap * (len(images) - 1)
    height = max(i.size[1] for i in images)
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    x = 0
    for image in images:
        canvas.paste(image, (x, (height - image.size[1]) // 2))
        x += image.size[0] + args.gap
    canvas.save(args.output)
    print("%s %dx%d" % (args.output, width, height))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("apply")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--pixelate", action="append", type=box_of)
    p.add_argument("--fill", action="append", type=box_of)
    p.add_argument("--color", default="#FFFFFF")
    p.add_argument("--block", type=int, default=9)
    p.add_argument("--crop", type=box_of)
    p.set_defaults(run=apply)
    p = sub.add_parser("combine")
    p.add_argument("output")
    p.add_argument("images", nargs="+")
    p.add_argument("--gap", type=int, default=24)
    p.set_defaults(run=combine)
    args = parser.parse_args(argv)
    args.run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
