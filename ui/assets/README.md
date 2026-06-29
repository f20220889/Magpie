# UI assets — drop your custom files here

These are **placeholders**. Replace them with your own art; filenames are
referenced by `ui/index.html` and `ui/css/styles.css`, so keep the names (or
update those two files).

| File | Used for | Notes |
|------|----------|-------|
| `logo.svg` | topbar brand mark (44×44) | any square SVG/PNG works |
| `favicon.svg` | browser tab icon | SVG favicons work in modern browsers |
| `cursor.svg` | default cursor | hotspot set in CSS as `4 2` |
| `cursor-pointer.svg` | hover/clickable cursor | hotspot set in CSS as `6 2` |

## Custom cursors — important
- CSS references them in `styles.css`:
  ```css
  :root  { cursor: url("../assets/cursor.svg") 4 2, auto; }
  a, button { cursor: url("../assets/cursor-pointer.svg") 6 2, pointer; }
  ```
- The two numbers are the **hotspot** (the active click point), in pixels from
  the top-left of the image.
- **Cross-browser tip:** SVG cursors work in Chrome/Firefox but Safari is
  picky. For maximum compatibility export **PNG** (≤32×32), then point the CSS
  at e.g. `cursor.png`.

## Fonts
The handwriting font is **Caveat** (Google Fonts, free), loaded in `index.html`.
To go fully offline, download the woff2 files into this folder and replace the
`<link>` with an `@font-face` rule in `styles.css`.
