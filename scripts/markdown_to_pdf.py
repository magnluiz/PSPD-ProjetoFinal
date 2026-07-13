#!/usr/bin/env python3
"""Small Markdown-to-PDF exporter tailored for docs/relatorio.md.

It intentionally avoids external dependencies beyond Pillow, because the
workspace does not provide pandoc/wkhtmltopdf/reportlab.
"""

from __future__ import annotations

import re
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PAGE_W, PAGE_H = 1240, 1754  # A4 at ~150 DPI
MARGIN_X = 90
MARGIN_Y = 80
CONTENT_W = PAGE_W - 2 * MARGIN_X
BG = "white"
FG = "#1f2933"
MUTED = "#52606d"
RULE = "#d9e2ec"
CODE_BG = "#f4f6f8"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


F_TITLE = font(34, True)
F_H2 = font(25, True)
F_H3 = font(21, True)
F_BODY = font(17)
F_BODY_BOLD = font(17, True)
F_SMALL = font(14)
F_CODE = font(14)


class PdfBuilder:
    def __init__(self, md_path: Path) -> None:
        self.md_path = md_path
        self.pages: list[Image.Image] = []
        self.new_page()

    def new_page(self) -> None:
        self.img = Image.new("RGB", (PAGE_W, PAGE_H), BG)
        self.draw = ImageDraw.Draw(self.img)
        self.y = MARGIN_Y
        self.pages.append(self.img)

    def ensure(self, needed: int) -> None:
        if self.y + needed > PAGE_H - MARGIN_Y:
            self.new_page()

    def text_width(self, text: str, fnt: ImageFont.FreeTypeFont) -> int:
        return int(self.draw.textlength(text, font=fnt))

    def write_wrapped(self, text: str, fnt=F_BODY, fill=FG, indent: int = 0, spacing: int = 7) -> None:
        text = cleanup_inline(text)
        if not text:
            self.y += 14
            return
        max_px = CONTENT_W - indent
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            trial = f"{current} {word}".strip()
            if self.text_width(trial, fnt) <= max_px:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)

        line_h = fnt.size + spacing
        self.ensure(len(lines) * line_h + 8)
        for line in lines:
            self.draw.text((MARGIN_X + indent, self.y), line, font=fnt, fill=fill)
            self.y += line_h
        self.y += 7

    def heading(self, text: str, level: int) -> None:
        text = cleanup_inline(text)
        if level == 1:
            fnt, gap = F_TITLE, 28
        elif level == 2:
            fnt, gap = F_H2, 22
        else:
            fnt, gap = F_H3, 16
        lines = wrap_px(text, fnt, CONTENT_W, self.draw)
        self.ensure(len(lines) * (fnt.size + 8) + 42)
        if self.y > MARGIN_Y:
            self.y += gap
        for line in lines:
            self.draw.text((MARGIN_X, self.y), line, font=fnt, fill=FG)
            self.y += fnt.size + 8
        self.y += 6
        if level == 1:
            self.draw.line((MARGIN_X, self.y, PAGE_W - MARGIN_X, self.y), fill=RULE, width=2)
            self.y += 18

    def code_block(self, lines: list[str]) -> None:
        line_h = F_CODE.size + 7
        height = len(lines) * line_h + 26
        self.ensure(height)
        self.draw.rounded_rectangle(
            (MARGIN_X, self.y, PAGE_W - MARGIN_X, self.y + height),
            radius=8,
            fill=CODE_BG,
            outline=RULE,
        )
        y = self.y + 13
        for line in lines:
            self.draw.text((MARGIN_X + 16, y), line, font=F_CODE, fill=FG)
            y += line_h
        self.y += height + 14

    def table(self, lines: list[str]) -> None:
        rows = [split_table_row(line) for line in lines if not re.match(r"^\|\s*:?-{3,}", line)]
        if not rows:
            return
        cols = max(len(row) for row in rows)
        col_w = CONTENT_W // cols
        line_h = F_SMALL.size + 10
        row_heights = []
        wrapped_rows = []
        for row in rows:
            wrapped = []
            max_lines = 1
            for cell in row + [""] * (cols - len(row)):
                cell_lines = wrap_px(cleanup_inline(cell), F_SMALL, max(60, col_w - 18), self.draw)
                wrapped.append(cell_lines)
                max_lines = max(max_lines, len(cell_lines))
            wrapped_rows.append(wrapped)
            row_heights.append(max_lines * line_h + 14)

        total_h = sum(row_heights)
        self.ensure(total_h + 20)
        y = self.y
        for r_idx, wrapped in enumerate(wrapped_rows):
            h = row_heights[r_idx]
            x = MARGIN_X
            fill = "#edf2f7" if r_idx == 0 else BG
            self.draw.rectangle((MARGIN_X, y, PAGE_W - MARGIN_X, y + h), fill=fill, outline=RULE)
            for c_idx, cell_lines in enumerate(wrapped):
                self.draw.line((x, y, x, y + h), fill=RULE, width=1)
                cy = y + 8
                for cell_line in cell_lines:
                    self.draw.text((x + 8, cy), cell_line, font=F_SMALL if r_idx else font(14, True), fill=FG)
                    cy += line_h
                x += col_w
            self.draw.line((PAGE_W - MARGIN_X, y, PAGE_W - MARGIN_X, y + h), fill=RULE, width=1)
            y += h
        self.y = y + 18

    def image(self, alt: str, rel_path: str) -> None:
        path = (self.md_path.parent / rel_path).resolve()
        if not path.exists():
            self.write_wrapped(f"[Imagem não encontrada: {rel_path}]", F_BODY_BOLD, fill="#b42318")
            return
        with Image.open(path) as original:
            image = original.convert("RGB")
        max_h = 600
        scale = min(CONTENT_W / image.width, max_h / image.height, 1.0)
        new_size = (int(image.width * scale), int(image.height * scale))
        image = image.resize(new_size, Image.LANCZOS)
        self.ensure(image.height + 46)
        x = MARGIN_X + (CONTENT_W - image.width) // 2
        self.draw.rectangle((x - 1, self.y - 1, x + image.width + 1, self.y + image.height + 1), outline=RULE)
        self.img.paste(image, (x, self.y))
        self.y += image.height + 12
        if alt:
            self.write_wrapped(alt, F_SMALL, fill=MUTED)

    def build(self, out_path: Path) -> None:
        lines = self.md_path.read_text(encoding="utf-8").splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("```"):
                block = []
                i += 1
                while i < len(lines) and not lines[i].startswith("```"):
                    block.append(lines[i])
                    i += 1
                self.code_block(block)
            elif line.startswith("# "):
                self.heading(line[2:], 1)
            elif line.startswith("## "):
                self.heading(line[3:], 2)
            elif line.startswith("### "):
                self.heading(line[4:], 3)
            elif line.startswith("!["):
                match = re.match(r"!\[(.*)\]\((.*)\)", line)
                if match:
                    self.image(match.group(1), match.group(2))
            elif line.startswith("|"):
                block = [line]
                i += 1
                while i < len(lines) and lines[i].startswith("|"):
                    block.append(lines[i])
                    i += 1
                self.table(block)
                continue
            elif line.startswith("- "):
                self.write_wrapped("• " + line[2:], F_BODY, indent=18)
            elif re.match(r"^\d+\. ", line):
                self.write_wrapped(line, F_BODY, indent=18)
            elif line.strip():
                self.write_wrapped(line)
            else:
                self.y += 8
            i += 1

        out_path.parent.mkdir(parents=True, exist_ok=True)
        first, rest = self.pages[0], self.pages[1:]
        first.save(out_path, "PDF", resolution=150, save_all=True, append_images=rest)


def cleanup_inline(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return text


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def wrap_px(text: str, fnt: ImageFont.FreeTypeFont, max_px: int, draw: ImageDraw.ImageDraw) -> list[str]:
    if not text:
        return [""]
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=fnt) <= max_px:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: markdown_to_pdf.py <input.md> <output.pdf>", file=sys.stderr)
        return 2
    PdfBuilder(Path(sys.argv[1])).build(Path(sys.argv[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
