# Embedded report font

`VibeCJK-Regular.ttf` is a renamed, static weight-400 subset of Noto Sans CJK SC.
It covers Latin, Greek, Cyrillic, CJK ideographs, Japanese kana and Korean Hangul
used in reports. The renderer embeds the used glyphs in each PDF, so readers do
not need a system font, an Asian language pack or a network font download.

Upstream: [Noto CJK](https://github.com/notofonts/noto-cjk), revision
`f8d157532fbfaeda587e826d4cd5b21a49186f7c`,
`Sans/Variable/TTF/NotoSansCJKsc-VF.ttf`, Git blob
`e67840913223f5c5db60570ce5bf001b0e079d42`.
The original and this derivative are distributed under the SIL Open Font
License 1.1, reproduced in `OFL.txt`.

From the repository root, rebuild with `python tools/build_report_font.py`.
The script verifies the source blob, freezes the variable font, selects the
documented Unicode ranges, renames the derivative and includes its license.
No font download happens when users generate a report.
