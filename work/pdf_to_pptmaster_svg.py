from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

import fitz
from PIL import Image


PDF_PATH = Path(r"C:\Users\小叮当\xwechat_files\wxid_8y2bb0rsxan122_4b61\msg\file\2026-05\千里眼DICT集成服务细化管理方案宣贯材料.pdf")
PROJECT = Path(r"D:\ai\work\projects\qly_dict_pptmaster_test_ppt169_20260528")
SVG_DIR = PROJECT / "svg_output"
IMG_DIR = PROJECT / "images"
W, H = 1280, 720


def color_hex(value: int | None) -> str:
    if value is None:
        return "#000000"
    return f"#{(value >> 16) & 255:02x}{(value >> 8) & 255:02x}{value & 255:02x}"


def render_white(page: fitz.Page, sx: float, sy: float) -> Image.Image:
    pix = page.get_pixmap(matrix=fitz.Matrix(sx, sy), alpha=True)
    rgba = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    white.alpha_composite(rgba)
    return white.convert("RGB")


def text_lines(page: fitz.Page) -> list[dict]:
    lines: list[dict] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text")]
            if "".join(s["text"] for s in spans).strip():
                lines.append({**line, "spans": spans})
    return lines


def redact_text_only(src: fitz.Document) -> fitz.Document:
    doc = fitz.open(src.name)
    for page in doc:
        for line in text_lines(page):
            rect = fitz.Rect(line["bbox"])
            rect.x0 -= 0.8
            rect.y0 -= 0.6
            rect.x1 += 0.8
            rect.y1 += 0.6
            page.add_redact_annot(rect)
        page.apply_redactions(images=0, graphics=0, text=0)
    return doc


def make_text_svg(line: dict, sx: float, sy: float) -> str:
    spans = line["spans"]
    first = spans[0]
    origin = first.get("origin") or (line["bbox"][0], line["bbox"][3])
    x = origin[0] * sx
    y = origin[1] * sy
    size = max(1.0, float(first.get("size", 10)) * sy)
    fill = color_hex(first.get("color"))
    flags = int(first.get("flags", 0))
    weight = "700" if flags & 16 else "400"
    style = "italic" if flags & 2 else "normal"
    parts = [
        f'<text x="{x:.2f}" y="{y:.2f}" font-family="Microsoft YaHei, Arial" '
        f'font-size="{size:.2f}" font-weight="{weight}" font-style="{style}" '
        f'fill="{fill}" xml:space="preserve">'
    ]
    for span in spans:
        txt = escape(span.get("text", ""))
        if not txt:
            continue
        span_size = max(1.0, float(span.get("size", first.get("size", 10))) * sy)
        span_fill = color_hex(span.get("color"))
        span_flags = int(span.get("flags", flags))
        span_weight = "700" if span_flags & 16 else "400"
        span_style = "italic" if span_flags & 2 else "normal"
        parts.append(
            f'<tspan font-size="{span_size:.2f}" fill="{span_fill}" '
            f'font-weight="{span_weight}" font-style="{span_style}">{txt}</tspan>'
        )
    parts.append("</text>")
    return "".join(parts)


def main() -> None:
    SVG_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)

    src = fitz.open(PDF_PATH)
    bg_doc = redact_text_only(src)

    for i, page in enumerate(src, start=1):
        sx = W / page.rect.width
        sy = H / page.rect.height
        bg = render_white(bg_doc[i - 1], sx, sy)
        bg_name = f"page_{i:02d}_background.png"
        bg.save(IMG_DIR / bg_name)

        elements = [
            f'<image x="0" y="0" width="{W}" height="{H}" href="../images/{bg_name}"/>'
        ]

        for drawing in page.get_drawings():
            fill = drawing.get("fill")
            stroke = drawing.get("color")
            width = drawing.get("width") or 0
            for item in drawing.get("items", []):
                if item[0] != "re":
                    continue
                rect = item[1]
                if rect.width < 2 or rect.height < 2:
                    continue
                if abs(rect.width - page.rect.width) < 2 and abs(rect.height - page.rect.height) < 2:
                    continue
                attrs = [
                    f'x="{rect.x0 * sx:.2f}"',
                    f'y="{rect.y0 * sy:.2f}"',
                    f'width="{rect.width * sx:.2f}"',
                    f'height="{rect.height * sy:.2f}"',
                ]
                attrs.append(f'fill="{color_hex_from_pdf(fill)}"' if fill is not None else 'fill="none"')
                attrs.append(f'stroke="{color_hex_from_pdf(stroke)}"' if stroke is not None else 'stroke="none"')
                attrs.append(f'stroke-width="{max(width * sx, 0.2):.2f}"')
                elements.append(f"<rect {' '.join(attrs)}/>")

        for line in text_lines(page):
            elements.append(make_text_svg(line, sx, sy))

        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}">\n'
            + "\n".join(elements)
            + "\n</svg>\n"
        )
        (SVG_DIR / f"{i:02d}.svg").write_text(svg, encoding="utf-8")

    print(f"wrote {src.page_count} SVG pages to {SVG_DIR}")


def color_hex_from_pdf(value) -> str:
    if value is None:
        return "#000000"
    return f"#{int(value[0] * 255):02x}{int(value[1] * 255):02x}{int(value[2] * 255):02x}"


if __name__ == "__main__":
    main()
