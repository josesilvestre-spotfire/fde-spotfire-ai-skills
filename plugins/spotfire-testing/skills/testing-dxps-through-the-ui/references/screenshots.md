# Documentation screenshots

Screenshots for articles, READMEs and tickets leave the machine. Capture and redact them so they
show the analysis and nothing else.

## Capture

- Use `deskctl.py shot <hwnd> out.png`: PrintWindow captures one window, so windows on top of it
  (chat, mail, notifications) never appear.
- Place the window at a fixed size first (`deskctl.py place`), so a series of screenshots lines
  up.
- For a browser page, crop away the toolbar: the bookmarks bar and the profile button show
  personal information.

## Remove before publishing

| Item | Where it shows | Treatment |
|---|---|---|
| user names, avatars, e-mail addresses | title bars, Git hosting pages, commit lists, Analyst's account menu | pixelate |
| local paths with a user folder | file dialogs, title bars, error messages | pixelate or crop |
| server addresses, tokens, keys | connection dialogs, terminals, URLs | fill (not recoverable) |
| other applications | anything outside the target window | prevent: window-only capture |
| customer or real well names | data tables, legends | use synthetic data in the test copy |

Pixelate makes text unreadable but keeps the layout. Use fill for anything that must not be
recovered.

## Commands

```
python scripts/redact.py apply in.png out.png --pixelate L,T,R,B --fill L,T,R,B --crop L,T,R,B
python scripts/redact.py combine out.png left.png right.png --gap 24
```

Boxes use the coordinates of the input image, the same ones you read off the screenshot.
Pixelate and fill run before the crop.

After redacting, open the output image and check every region again. A redaction that missed
by a few pixels leaves the first or last letters readable.
