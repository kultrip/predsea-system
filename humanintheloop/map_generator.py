import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1440
HEIGHT = 1800
BG = "#061621"
PANEL = "#0b2430"
GRID = "#1d4b59"
CYAN = "#22e6f0"
TEXT = "#f4fbff"
MUTED = "#a8bdc6"
GREEN = "#6ee65d"
YELLOW = "#ffd84d"
RED = "#ff6b6b"


def generate_route_decision_map(waves_path, currents_path, route, snapshot, output_path, target_time=None):
    try:
        import xarray as xr
    except ImportError as error:
        raise RuntimeError("xarray is required to generate PredSea Decision Maps") from error

    output_path = Path(output_path)
    with xr.open_dataset(waves_path) as waves, xr.open_dataset(currents_path) as currents:
        time_index = select_time_index(waves, target_time or snapshot.get("forecast", {}).get("wave_peak_time"))
        wave = waves["VHM0"].isel(time=time_index)
        current_u = currents["uo"].isel(time=min(time_index, currents.sizes.get("time", 1) - 1))
        current_v = currents["vo"].isel(time=min(time_index, currents.sizes.get("time", 1) - 1))
        time_label = str(waves["time"].dt.strftime("%H:%M UTC").values[time_index])

        image = Image.new("RGB", (WIDTH, HEIGHT), BG)
        draw = ImageDraw.Draw(image)
        fonts = load_fonts()

        draw_background(draw)
        draw_header(draw, fonts, route, time_label)

        map_box = (80, 330, 1360, 1260)
        bounds = route_bounds(route, wave)
        draw_wave_field(draw, wave, map_box, bounds)
        draw_grid(draw, map_box)
        draw_current_arrows(draw, current_u, current_v, map_box, bounds)
        draw_route(draw, route, map_box, bounds, snapshot)
        draw_legend(draw, map_box, fonts)
        draw_decision_panel(draw, fonts, snapshot)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)
        return output_path


def select_time_index(dataset, peak_time):
    if not peak_time or peak_time == "N/A" or "time" not in dataset:
        return 0
    labels = [str(value) for value in dataset["time"].dt.strftime("%H:%M").values]
    if peak_time in labels:
        return labels.index(peak_time)
    return 0


def route_bounds(route, wave):
    lons = [float(value) for value in wave["longitude"].values]
    lats = [float(value) for value in wave["latitude"].values]
    route_lons = [route["origin"]["longitude"], route["destination"]["longitude"]]
    route_lats = [route["origin"]["latitude"], route["destination"]["latitude"]]
    for point in route.get("sample_points", []):
        route_lons.append(point["longitude"])
        route_lats.append(point["latitude"])
    lon_min = max(min(lons), min(route_lons) - 0.25)
    lon_max = min(max(lons), max(route_lons) + 0.25)
    lat_min = max(min(lats), min(route_lats) - 0.25)
    lat_max = min(max(lats), max(route_lats) + 0.25)
    if lon_min == lon_max:
        lon_min -= 0.1
        lon_max += 0.1
    if lat_min == lat_max:
        lat_min -= 0.1
        lat_max += 0.1
    return lon_min, lon_max, lat_min, lat_max


def project(lon, lat, map_box, bounds):
    left, top, right, bottom = map_box
    lon_min, lon_max, lat_min, lat_max = bounds
    x = left + (float(lon) - lon_min) / (lon_max - lon_min) * (right - left)
    y = bottom - (float(lat) - lat_min) / (lat_max - lat_min) * (bottom - top)
    return x, y


def draw_background(draw):
    for y in range(0, HEIGHT, 90):
        draw.arc((-220, y - 380, WIDTH + 220, y + 520), 210, 340, fill="#0b2e3a", width=1)


def draw_header(draw, fonts, route, time_label):
    draw.text((80, 70), "PredSea", font=fonts["brand"], fill=TEXT)
    draw.text((80, 165), "ROUTE DECISION MAP", font=fonts["title"], fill=TEXT)
    draw.line((80, 245, 760, 245), fill=CYAN, width=4)
    draw.text((80, 278), route["name"], font=fonts["subtitle"], fill=CYAN)
    draw.text((980, 92), f"Model slice: {time_label}", font=fonts["small"], fill=MUTED)


def draw_wave_field(draw, wave, map_box, bounds):
    lons = [float(value) for value in wave["longitude"].values]
    lats = [float(value) for value in wave["latitude"].values]
    values = wave.values
    min_value = 0.0
    max_value = max(2.5, max(float(value) for row in values for value in row if value == value))
    for lat_index, lat in enumerate(lats):
        for lon_index, lon in enumerate(lons):
            value = float(values[lat_index][lon_index])
            if value != value:
                continue
            x, y = project(lon, lat, map_box, bounds)
            cell = 90
            left, top, right, bottom = map_box
            rect = (
                max(left, x - cell),
                max(top, y - cell),
                min(right, x + cell),
                min(bottom, y + cell),
            )
            if rect[2] < rect[0] or rect[3] < rect[1]:
                continue
            draw.rectangle(
                rect,
                fill=wave_color(value, min_value, max_value),
            )


def wave_color(value, min_value=0.0, max_value=2.5):
    ratio = max(0.0, min(1.0, (value - min_value) / (max_value - min_value)))
    if ratio < 0.45:
        local = ratio / 0.45
        return blend((9, 61, 80), (37, 229, 240), local)
    if ratio < 0.75:
        local = (ratio - 0.45) / 0.30
        return blend((37, 229, 240), (255, 216, 77), local)
    local = (ratio - 0.75) / 0.25
    return blend((255, 216, 77), (255, 107, 107), local)


def blend(start, end, ratio):
    rgb = tuple(round(start[index] + (end[index] - start[index]) * ratio) for index in range(3))
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def draw_grid(draw, map_box):
    left, top, right, bottom = map_box
    draw.rounded_rectangle(map_box, radius=28, outline="#2b6b7d", width=3)
    for fraction in (0.25, 0.5, 0.75):
        x = left + (right - left) * fraction
        y = top + (bottom - top) * fraction
        draw.line((x, top, x, bottom), fill=GRID, width=1)
        draw.line((left, y, right, y), fill=GRID, width=1)


def draw_current_arrows(draw, current_u, current_v, map_box, bounds):
    lons = [float(value) for value in current_u["longitude"].values]
    lats = [float(value) for value in current_u["latitude"].values]
    lon_step = max(1, len(lons) // 5)
    lat_step = max(1, len(lats) // 5)
    for lat_index in range(0, len(lats), lat_step):
        for lon_index in range(0, len(lons), lon_step):
            lon = lons[lon_index]
            lat = lats[lat_index]
            x, y = project(lon, lat, map_box, bounds)
            u = float(current_u.values[lat_index][lon_index])
            v = float(current_v.values[lat_index][lon_index])
            speed = math.hypot(u, v)
            if speed == 0 or speed != speed:
                continue
            length = min(54, 18 + speed * 110)
            angle = math.atan2(v, u)
            x2 = x + math.cos(angle) * length
            y2 = y - math.sin(angle) * length
            draw_arrow(draw, (x, y), (x2, y2), "#ffffff", width=3)


def draw_arrow(draw, start, end, fill, width=4):
    draw.line((*start, *end), fill=fill, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    for offset in (2.5, -2.5):
        head_angle = angle + offset
        x = end[0] + math.cos(head_angle) * 14
        y = end[1] + math.sin(head_angle) * 14
        draw.line((*end, x, y), fill=fill, width=width)


def draw_route(draw, route, map_box, bounds, snapshot):
    points = [(route["origin"]["longitude"], route["origin"]["latitude"])]
    points.extend((point["longitude"], point["latitude"]) for point in route.get("sample_points", []))
    points.append((route["destination"]["longitude"], route["destination"]["latitude"]))
    projected = [project(lon, lat, map_box, bounds) for lon, lat in points]
    color = severity_color(snapshot.get("recommendation", {}).get("vessel_severity"))
    if len(projected) >= 2:
        worst_segment = exposed_segment_index(snapshot, len(projected) - 1)
        for index, (start, end) in enumerate(zip(projected, projected[1:])):
            segment_color = color if index == worst_segment else "#e8fbff"
            width = 10 if index == worst_segment else 5
            draw.line((*start, *end), fill=segment_color, width=width)
    for x, y in projected:
        draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=TEXT, outline=BG, width=3)
    label_point(draw, route["origin"]["name"], projected[0], dx=18, dy=-44)
    label_point(draw, route["destination"]["name"], projected[-1], dx=18, dy=18)


def exposed_segment_index(snapshot, segment_count):
    hourly = snapshot.get("forecast", {}).get("hourly") or []
    if not hourly:
        return max(0, segment_count // 2)
    return max(0, segment_count // 2)


def label_point(draw, label, point, dx=12, dy=12):
    font = load_fonts()["small"]
    x, y = point
    draw.text((x + dx, y + dy), label, font=font, fill=TEXT)


def draw_legend(draw, map_box, fonts):
    left, top, right, bottom = map_box
    legend = (left + 32, bottom - 130, left + 500, bottom - 34)
    draw.rounded_rectangle(legend, radius=18, fill="#09202a", outline="#164552", width=2)
    draw.text((legend[0] + 24, legend[1] + 18), "Wave height field", font=fonts["small"], fill=TEXT)
    for index, color in enumerate(("#093d50", CYAN, YELLOW, RED)):
        x = legend[0] + 250 + index * 44
        draw.rectangle((x, legend[1] + 28, x + 38, legend[1] + 62), fill=color)
    draw.text((legend[0] + 250, legend[1] + 68), "calm", font=fonts["micro"], fill=MUTED)
    draw.text((legend[0] + 360, legend[1] + 68), "rougher", font=fonts["micro"], fill=MUTED)


def draw_decision_panel(draw, fonts, snapshot):
    forecast = snapshot.get("forecast", {})
    rec = snapshot.get("recommendation", {})
    panel = (80, 1315, 1360, 1705)
    draw.rounded_rectangle(panel, radius=28, fill=PANEL, outline="#174c5e", width=2)
    status = status_label(rec.get("vessel_severity"))
    color = severity_color(rec.get("vessel_severity"))
    draw.ellipse((122, 1372, 152, 1402), fill=color)
    draw.text((175, 1350), status, font=fonts["status"], fill=color)
    draw.text((175, 1410), rec.get("vessel_advice", "manual review needed"), font=fonts["body"], fill=TEXT)
    wave_min = forecast.get("wave_min_m")
    wave_max = forecast.get("wave_max_m")
    wave_text = "Wave range unavailable"
    if wave_min is not None and wave_max is not None:
        wave_text = f"Wave range: {wave_min:.1f}-{wave_max:.1f} m"
    draw.text((175, 1482), wave_text, font=fonts["body"], fill=CYAN)
    draw.text((175, 1538), f"Peak: {forecast.get('wave_peak_time', 'N/A')}", font=fonts["body"], fill=TEXT)
    current = forecast.get("current_max_kn")
    current_text = "Current max: unavailable" if current is None else f"Current max: {current:.1f} kn"
    draw.text((760, 1482), current_text, font=fonts["body"], fill=TEXT)
    draw.text((760, 1538), f"Confidence: {rec.get('confidence', 'low')}", font=fonts["body"], fill=TEXT)
    draw.text((175, 1622), "Ocean-first Decision Map. Wind context added only when operationally relevant.", font=fonts["small"], fill=MUTED)


def status_label(severity):
    if severity == "restricted":
        return "RESTRICTED"
    if severity == "caution":
        return "CONSERVATIVE"
    if severity == "manageable":
        return "WORKABLE"
    return "MANUAL REVIEW"


def severity_color(severity):
    if severity == "restricted":
        return RED
    if severity == "caution":
        return YELLOW
    return GREEN


def load_fonts():
    regular_candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    bold_candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    regular = next((path for path in regular_candidates if Path(path).exists()), None)
    bold = next((path for path in bold_candidates if Path(path).exists()), regular)
    if regular:
        return {
            "brand": ImageFont.truetype(bold, 44),
            "title": ImageFont.truetype(bold, 58),
            "subtitle": ImageFont.truetype(regular, 32),
            "status": ImageFont.truetype(bold, 42),
            "body": ImageFont.truetype(regular, 34),
            "small": ImageFont.truetype(regular, 25),
            "micro": ImageFont.truetype(regular, 18),
        }
    default = ImageFont.load_default()
    return {key: default for key in ("brand", "title", "subtitle", "status", "body", "small", "micro")}
