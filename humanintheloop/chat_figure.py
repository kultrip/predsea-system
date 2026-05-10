import argparse
import re
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1080
HEIGHT = 1350
BG = "#071723"
CHAT_BG = "#0f2530"
HEADER_BG = "#06242d"
CAPTAIN_BUBBLE = "#1f3a46"
PREDSEA_BUBBLE = "#00c8d2"
PREDSEA_TEXT = "#002d35"
TEXT = "#f7fbff"
MUTED = "#9bb8c2"
SUCCESS = "#b8fff6"
IMPORTANT_PATTERNS = [
    re.compile(r"\bbefore midday\b", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+)?\s*m\b", re.IGNORECASE),
    re.compile(r"\b\d{1,2}:\d{2}\b"),
]


def parse_script(script_text):
    messages = []
    caption = None
    for raw_line in script_text.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith("illustrative whatsapp"):
            continue
        if line.lower().startswith("caption note:"):
            caption = line.split(":", 1)[1].strip()
            continue
        if ":" not in line:
            continue
        speaker, message = line.split(":", 1)
        speaker = speaker.strip()
        if speaker not in {"Captain", "PredSea"}:
            continue
        message = message.strip()
        messages.append(
            {
                "speaker": speaker,
                "text": message,
                "is_location": speaker == "Captain" and message == "[Shared live location]",
            }
        )
    return messages, caption


def emphasize_message(message):
    spans = []
    for pattern in IMPORTANT_PATTERNS:
        spans.extend(pattern.span() for pattern in pattern.finditer(message))
    if not spans:
        return [(message, False)]

    spans.sort()
    merged = []
    for start, end in spans:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)

    segments = []
    cursor = 0
    for start, end in merged:
        if start > cursor:
            segments.append((message[cursor:start], False))
        segments.append((message[start:end], True))
        cursor = end
    if cursor < len(message):
        segments.append((message[cursor:], False))
    return segments


def generate_chat_figure(script_path, logo_path, output_path, platform="WhatsApp"):
    script_path = Path(script_path)
    logo_path = Path(logo_path)
    output_path = Path(output_path)
    messages, caption = parse_script(script_path.read_text(encoding="utf-8"))

    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    fonts = load_fonts()

    phone = (110, 70, 970, 1240)
    draw.rounded_rectangle(phone, radius=48, fill=CHAT_BG, outline="#123744", width=3)
    draw.rounded_rectangle((110, 70, 970, 210), radius=48, fill=HEADER_BG)
    draw.rectangle((110, 150, 970, 210), fill=HEADER_BG)
    draw.line((150, 210, 930, 210), fill="#164853", width=2)

    avatar = make_avatar(logo_path, 96)
    draw.ellipse((146, 91, 250, 195), fill="#06313a", outline=PREDSEA_BUBBLE, width=2)
    image.paste(avatar, (150, 95), avatar)
    draw.text((265, 105), "PredSea", font=fonts["title"], fill=TEXT)
    draw.text((265, 152), f"{platform} route intelligence", font=fonts["small"], fill=MUTED)
    draw.text((810, 125), "09:30", font=fonts["small"], fill=MUTED)

    y = 250
    for item in messages:
        y = draw_message(draw, item, y, fonts)

    if caption:
        draw.text((145, 1260), caption, font=fonts["caption"], fill=MUTED)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def draw_message(draw, item, y, fonts):
    is_predsea = item["speaker"] == "PredSea"
    if item.get("is_location"):
        return draw_location_message(draw, y, fonts)

    max_chars = 44 if is_predsea else 38
    lines = textwrap.wrap(item["text"], width=max_chars) or [""]
    line_height = 31
    is_confidence = item["text"].lower().startswith("confidence:")
    bubble_width = min(650, max(260, max(draw.textlength(line, font=fonts["body"]) for line in lines) + 62))
    bubble_height = 58 + line_height * len(lines)

    if is_predsea:
        x1 = 160
        fill = PREDSEA_BUBBLE if not is_confidence else "#0fb7c0"
        text_fill = PREDSEA_TEXT
    else:
        x1 = WIDTH - 160 - bubble_width
        fill = CAPTAIN_BUBBLE
        text_fill = TEXT
    x2 = x1 + bubble_width
    y2 = y + bubble_height

    shadow = (x1 + 4, y + 6, x2 + 4, y2 + 6)
    draw.rounded_rectangle(shadow, radius=24, fill="#061116")
    draw.rounded_rectangle((x1, y, x2, y2), radius=24, fill=fill)
    if is_confidence:
        draw.rounded_rectangle((x1 + 26, y + 15, x1 + 154, y + 46), radius=15, fill=SUCCESS)
        draw.text((x1 + 46, y + 19), "CONFIDENCE", font=fonts["micro"], fill=PREDSEA_TEXT)
    else:
        draw.text((x1 + 28, y + 18), item["speaker"], font=fonts["label"], fill=text_fill)
    text_y = y + 50
    for line in lines:
        draw_emphasized_line(draw, x1 + 28, text_y, line, fonts, text_fill)
        text_y += line_height
    return y2 + 22


def draw_location_message(draw, y, fonts):
    bubble_width = 520
    bubble_height = 148
    x1 = WIDTH - 160 - bubble_width
    x2 = x1 + bubble_width
    y2 = y + bubble_height

    draw.rounded_rectangle((x1 + 4, y + 6, x2 + 4, y2 + 6), radius=24, fill="#061116")
    draw.rounded_rectangle((x1, y, x2, y2), radius=24, fill=CAPTAIN_BUBBLE)
    map_box = (x1 + 22, y + 22, x1 + 142, y + 126)
    draw.rounded_rectangle(map_box, radius=18, fill="#173f4a")
    draw.line((map_box[0] + 18, y + 52, map_box[2] - 16, y + 82), fill="#3f6b75", width=3)
    draw.line((map_box[0] + 12, y + 97, map_box[2] - 12, y + 64), fill="#315964", width=3)
    pin_x = map_box[0] + 66
    pin_y = y + 68
    draw.ellipse((pin_x - 14, pin_y - 14, pin_x + 14, pin_y + 14), fill=PREDSEA_BUBBLE)
    draw.ellipse((pin_x - 5, pin_y - 5, pin_x + 5, pin_y + 5), fill=TEXT)

    draw.text((x1 + 164, y + 28), "Shared live location", font=fonts["body_bold"], fill=TEXT)
    draw.text((x1 + 164, y + 66), "Near Palma Marina", font=fonts["body"], fill=TEXT)
    draw.text((x1 + 164, y + 104), "Tap to open map", font=fonts["small"], fill=MUTED)
    return y2 + 22


def draw_emphasized_line(draw, x, y, line, fonts, fill):
    cursor = x
    for text, is_bold in emphasize_message(line):
        font = fonts["body_bold"] if is_bold else fonts["body"]
        draw.text((cursor, y), text, font=font, fill=fill)
        cursor += draw.textlength(text, font=font)


def make_avatar(logo_path, size):
    logo = Image.open(logo_path).convert("RGB")
    logo.thumbnail((size, size))
    square = Image.new("RGB", (size, size), BG)
    square.paste(logo, ((size - logo.width) // 2, (size - logo.height) // 2))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    avatar = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    avatar.paste(square, (0, 0), mask)
    return avatar


def load_fonts():
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    bold_candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    font_path = next((path for path in candidates if Path(path).exists()), None)
    bold_path = next((path for path in bold_candidates if Path(path).exists()), font_path)
    if font_path:
        return {
            "title": ImageFont.truetype(font_path, 42),
            "body": ImageFont.truetype(font_path, 28),
            "body_bold": ImageFont.truetype(bold_path, 28),
            "label": ImageFont.truetype(font_path, 21),
            "small": ImageFont.truetype(font_path, 24),
            "micro": ImageFont.truetype(font_path, 13),
            "caption": ImageFont.truetype(font_path, 22),
        }
    return {
        "title": ImageFont.load_default(),
        "body": ImageFont.load_default(),
        "body_bold": ImageFont.load_default(),
        "label": ImageFont.load_default(),
        "small": ImageFont.load_default(),
        "micro": ImageFont.load_default(),
        "caption": ImageFont.load_default(),
    }


def main():
    parser = argparse.ArgumentParser(description="Generate a PredSea chat screenshot-style figure.")
    parser.add_argument("script_path")
    parser.add_argument("logo_path")
    parser.add_argument("output_path")
    parser.add_argument("--platform", default="WhatsApp", choices=["WhatsApp", "Telegram"])
    args = parser.parse_args()
    output = generate_chat_figure(args.script_path, args.logo_path, args.output_path, platform=args.platform)
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
