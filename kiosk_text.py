"""Kannada / Hindi text for the kiosk TFT, drawn on the PC.

The ESP32's TFT fonts are ASCII only, and Kannada and Devanagari cannot be drawn
letter by letter anyway: vowel signs and conjuncts combine and reorder. So the
PC shapes the text with HarfBuzz (correct conjuncts and vowel signs), renders it
with FreeType in the Windows "Nirmala UI" font (Kannada, Devanagari and Latin,
so Kanglish/Hinglish answers render too), word-wraps it to the kiosk's text
width, and sends it as 1-bit bitmaps (see krishi_client.Esp32Link.send_glyphs).

If the shaping libraries or the font are missing, available() is False and the
kiosk falls back to the Latin-script text it always had.
"""
from __future__ import annotations

import os
from functools import lru_cache

import numpy as np

FONT = os.getenv("KIOSK_INDIC_FONT", r"C:\Windows\Fonts\Nirmala.ttc")
FONT_INDEX = int(os.getenv("KIOSK_INDIC_FONT_INDEX", "0"))      # 0 = Nirmala UI Regular

# Geometry of the chat bubble's text area - must match firmware/src/main.cpp
# (IN_W, IN_TOP, FOOT_Y and the question strip).
TEXT_W = 162
Q_TOP = 34 + 10            # IN_TOP + 10: below the "You asked" label
FOOT_Y = 214
ANSWER_GAP = 8             # rule under the question + spacing
MAX_PAGES = 12            # MAX_PAGES in the firmware


def has_indic(text: str) -> bool:
    return any(0x0900 <= ord(c) <= 0x097F or 0x0C80 <= ord(c) <= 0x0CFF for c in text or "")


@lru_cache(maxsize=1)
def _engine():
    import freetype
    import uharfbuzz as hb
    face = freetype.Face(FONT, FONT_INDEX)
    hb_face = hb.Face(hb.Blob.from_file_path(FONT), FONT_INDEX)
    return freetype, hb, face, hb_face


def available() -> bool:
    try:
        _engine()
        return True
    except Exception:
        return False


class Renderer:
    def __init__(self, px: int = 20):
        self.freetype, self.hb, self.face, hb_face = _engine()
        self.px = px
        self.font = self.hb.Font(hb_face)
        self.font.scale = (px * 64, px * 64)               # positions in 26.6 pixels
        self.face.set_pixel_sizes(0, px)
        # Nirmala's own line metrics are very generous; tight but safe for
        # Kannada's stacked vowel signs and subscript consonants:
        self.asc = int(round(px * 1.02))
        self.line_h = int(round(px * 1.38))

    def _shape(self, text: str):
        buf = self.hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        self.hb.shape(self.font, buf, {})
        return buf.glyph_infos, buf.glyph_positions

    def width(self, text: str) -> float:
        return sum(p.x_advance for p in self._shape(text)[1]) / 64

    def wrap(self, text: str, width: int = TEXT_W) -> list[str]:
        lines, cur = [], ""
        for word in text.split():
            cand = f"{cur} {word}" if cur else word
            if self.width(cand) <= width or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = word
            while self.width(cur) > width and len(cur) > 1:   # one word wider than the line
                cut = len(cur)
                while cut > 1 and self.width(cur[:cut]) > width:
                    cut -= 1
                lines.append(cur[:cut])
                cur = cur[cut:]
        if cur:
            lines.append(cur)
        return lines

    def render_line(self, text: str, width: int = TEXT_W) -> np.ndarray:
        img = np.zeros((self.line_h, width), dtype=np.uint8)
        infos, positions = self._shape(text)
        pen = 0.0
        ft = self.freetype
        for info, pos in zip(infos, positions):
            self.face.load_glyph(info.codepoint, ft.FT_LOAD_RENDER | ft.FT_LOAD_TARGET_LIGHT)
            g = self.face.glyph
            bm = g.bitmap
            if bm.width and bm.rows:
                a = np.array(bm.buffer, dtype=np.uint8).reshape(bm.rows, bm.pitch)[:, :bm.width]
                x = int(round(pen + pos.x_offset / 64)) + g.bitmap_left
                y = self.asc - int(round(pos.y_offset / 64)) - g.bitmap_top
                x0, y0 = max(0, x), max(0, y)
                x1, y1 = min(width, x + bm.width), min(self.line_h, y + bm.rows)
                if x1 > x0 and y1 > y0:
                    img[y0:y1, x0:x1] = np.maximum(img[y0:y1, x0:x1], a[y0 - y:y1 - y, x0 - x:x1 - x])
            pen += pos.x_advance / 64
        return img

    def render(self, text: str, max_lines: int | None = None, width: int = TEXT_W) -> np.ndarray:
        lines = self.wrap(" ".join((text or "").split()), width)
        if max_lines is not None and len(lines) > max_lines:
            lines = lines[:max_lines]
            last = lines[-1]
            while last and self.width(last + "...") > width:
                last = last[:-1]
            lines[-1] = last.rstrip() + "..."
        if not lines:
            return np.zeros((0, width), dtype=np.uint8)
        return np.vstack([self.render_line(l, width) for l in lines])


def to_rows(gray: np.ndarray, threshold: int = 80) -> list[bytes]:
    """8-bit coverage -> 1-bit rows, MSB first, (width + 7) // 8 bytes each."""
    bits = (gray >= threshold).astype(np.uint8)
    return [bytes(r) for r in np.packbits(bits, axis=1)]


Q_PX = int(os.getenv("KIOSK_INDIC_Q_PX", "18"))
A_PX = int(os.getenv("KIOSK_INDIC_A_PX", "18"))      # 18 px, threshold 80: chosen from rendered samples


def render_question(question: str) -> list[bytes]:
    """The question strip: up to two lines (ellipsis beyond)."""
    return to_rows(Renderer(Q_PX).render(question, max_lines=2))


def render_answer(answer: str, question_rows: int) -> tuple[list[list[bytes]], int]:
    """(pages, page height): whole lines per page, fitting under a question
    strip of question_rows rows. At most MAX_PAGES (the answer is still spoken in full)."""
    r = Renderer(A_PX)
    page_h = FOOT_Y - 2 - (Q_TOP + question_rows + ANSWER_GAP)
    per_page = max(1, page_h // r.line_h)
    lines = r.wrap(" ".join((answer or "").split()))
    pages = []
    for i in range(0, min(len(lines), per_page * MAX_PAGES), per_page):
        img = np.vstack([r.render_line(l) for l in lines[i:i + per_page]])
        img = np.vstack([img, np.zeros((page_h - img.shape[0], TEXT_W), dtype=np.uint8)])
        pages.append(to_rows(img))
    return pages, page_h


# --- screen labels (any kiosk text in Kannada / Hindi) ------------------------

# Pixel size per TFT font the firmware would have used: GLCD (1), font 2, font 4.
LABEL_PX = {1: 13, 2: 16, 4: 22}


def render_label(text: str, font: int, max_w: int, max_lines: int = 1) -> tuple[list[bytes], int, int]:
    """(rows, width, height) of `text` fitted into max_w x max_lines lines:
    wrapped, then shrunk down to 12 px, then cut with '...'. Width is the widest
    line actually drawn, so the firmware can align it (centre, right...)."""
    max_w = max(16, min(int(max_w or 300), 312))
    max_lines = max(1, min(int(max_lines or 1), 8))
    text = " ".join((text or "").split())
    px = LABEL_PX.get(int(font), 16)
    while True:
        r = Renderer(px)
        lines = r.wrap(text, max_w)
        if len(lines) <= max_lines or px <= 12:
            break
        px -= 1
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and r.width(last + "...") > max_w:
            last = last[:-1]
        lines[-1] = last.rstrip() + "..."
    width = max(1, min(max_w, int(max(r.width(l) for l in lines) + 1.5))) if lines else 1
    img = np.vstack([r.render_line(l, width) for l in lines]) if lines else np.zeros((1, width), np.uint8)
    return to_rows(img), width, img.shape[0]
