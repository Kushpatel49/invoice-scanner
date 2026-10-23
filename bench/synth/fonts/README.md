# Bundled fonts

These fonts are bundled so the synthetic benchmark renders identically on any machine. All of them come from the [google/fonts](https://github.com/google/fonts) repository and are licensed under the **SIL Open Font License 1.1** ([OFL.txt](OFL.txt)), which allows bundling and redistribution with software. Copyright for each font stays with its authors, as listed in each family's directory in google/fonts.

| File | Family | Source (google/fonts) | Used for |
|---|---|---|---|
| Kalam-Regular / Light / Bold.ttf | Kalam (Indian Type Foundry) | `ofl/kalam` | handwriting |
| Caveat.ttf | Caveat (Impallari Type) | `ofl/caveat` | handwriting |
| PatrickHand-Regular.ttf | Patrick Hand (Patrick Wagesreiter) | `ofl/patrickhand` | handwriting |
| GochiHand-Regular.ttf | Gochi Hand (Huerta Tipográfica) | `ofl/gochihand` | handwriting (pen notes) |
| ReenieBeanie.ttf | Reenie Beanie (James Grieshaber) | `ofl/reeniebeanie` | handwriting |
| CourierPrime-Regular / Bold.ttf | Courier Prime (Alan Dague-Greene) | `ofl/courierprime` | typewriter / dot-matrix |
| NotoSans.ttf | Noto Sans (Google) | `ofl/notosans` | printed text, ₹ sign |
| OpenSans.ttf | Open Sans (Steve Matteson) | `ofl/opensans` | printed text |
| RobotoMono.ttf | Roboto Mono (Christian Robertson) | `ofl/robotomono` | monospace |
| Oswald.ttf | Oswald (Vernon Adams et al.) | `ofl/oswald` | condensed headings |
| PT_Serif-Web-Regular / Bold.ttf | PT Serif (ParaType) | `ofl/ptserif` | serif letterheads |
| ArchivoNarrow.ttf | Archivo Narrow (Omnibus-Type) | `ofl/archivonarrow` | narrow table text |

Variable fonts (Caveat, NotoSans, OpenSans, RobotoMono, Oswald, ArchivoNarrow) are saved without the axis suffix from their original file names.

Only NotoSans, ArchivoNarrow and Oswald draw the rupee sign (U+20B9) correctly. PT Serif draws a ruble-like glyph, and OpenSans, RobotoMono and Courier Prime have no rupee sign at all. With those fonts, templates print "Rs." instead.
