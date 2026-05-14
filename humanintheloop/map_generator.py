import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


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

        map_box = (80, 350, 1360, 1235)
        bounds = route_bounds(route, wave)
        route_values = route_sample_wave_values(wave, route)
        route_currents = route_sample_current_values(current_u, current_v, route)
        draw_operational_map_base(image, draw, map_box, bounds, route, route_values)
        draw_current_context(draw, route, route_currents, map_box, bounds)
        draw_route(draw, route, map_box, bounds, snapshot, route_values)
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
    route_lons = [route["origin"]["longitude"], route["destination"]["longitude"]]
    route_lats = [route["origin"]["latitude"], route["destination"]["latitude"]]
    for point in route.get("sample_points", []):
        route_lons.append(point["longitude"])
        route_lats.append(point["latitude"])
    lon_min = min(route_lons) - 0.45
    lon_max = max(route_lons) + 0.45
    lat_min = min(route_lats) - 0.35
    lat_max = max(route_lats) + 0.35
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
    return


def draw_header(draw, fonts, route, time_label):
    draw.text((80, 70), "PredSea", font=fonts["brand"], fill=TEXT)
    draw.text((80, 165), "ROUTE DECISION MAP", font=fonts["title"], fill=TEXT)
    draw.line((80, 245, 760, 245), fill=CYAN, width=4)
    draw.text((80, 278), route["name"], font=fonts["subtitle"], fill=CYAN)
    draw.text((980, 92), f"Model slice: {time_label}", font=fonts["small"], fill=MUTED)


def route_sample_wave_values(wave, route):
    values = []
    for point in route.get("sample_points", []):
        sample = wave.sel(longitude=point["longitude"], latitude=point["latitude"], method="nearest")
        values.append(float(sample.values))
    return values


def route_sample_current_values(current_u, current_v, route):
    values = []
    for point in route.get("sample_points", []):
        u = float(current_u.sel(longitude=point["longitude"], latitude=point["latitude"], method="nearest").values)
        v = float(current_v.sel(longitude=point["longitude"], latitude=point["latitude"], method="nearest").values)
        values.append({"u": u, "v": v, "speed": math.hypot(u, v)})
    return values


def draw_operational_map_base(image, draw, map_box, bounds, route, route_values):
    left, top, right, bottom = map_box
    draw.rounded_rectangle(map_box, radius=34, fill="#082331", outline="#1a6374", width=3)
    draw_bathymetry(draw, map_box)
    draw_island_context(draw, map_box, bounds)
    draw_route_condition_halos(image, route, route_values, map_box, bounds)
    draw.rounded_rectangle(map_box, radius=34, outline="#2b7c8f", width=3)
    draw.text((left + 34, top + 30), "Ocean route exposure", font=load_fonts()["small"], fill=MUTED)


def draw_bathymetry(draw, map_box):
    left, top, right, bottom = map_box
    for fraction in (0.25, 0.5, 0.75):
        y = top + (bottom - top) * fraction
        draw.line((left + 40, y, right - 40, y), fill="#0e3442", width=1)


ISLAND_SHAPES = {
    "mallorca": [
        (2.35, 39.30), (2.65, 39.52), (3.05, 39.82), (3.55, 39.92), (3.95, 39.78),
        (4.25, 39.48), (4.05, 39.25), (3.55, 39.18), (3.10, 39.18), (2.70, 39.22),
    ],
    "ibiza": [
        (1.18, 38.83), (1.32, 39.02), (1.62, 39.08), (1.75, 38.96),
        (1.60, 38.78), (1.30, 38.74),
    ],
    "formentera": [
        (1.25, 38.66), (1.42, 38.73), (1.62, 38.72), (1.58, 38.62), (1.36, 38.58),
    ],
    "menorca": [
        (3.78, 39.86), (4.15, 40.08), (4.65, 40.08), (4.35, 39.86),
    ],
    "cabrera": [
        (2.88, 39.12), (2.98, 39.17), (3.05, 39.11), (2.96, 39.06),
    ],
}


def draw_island_context(draw, map_box, bounds):
    for points in ISLAND_SHAPES.values():
        projected = [project(lon, lat, map_box, bounds) for lon, lat in points]
        if not all(point_inside_map(point, map_box, margin=10) for point in projected):
            continue
        draw.polygon(projected, fill="#12313d", outline="#77aebc")


def point_inside_map(point, map_box, margin=0):
    x, y = point
    left, top, right, bottom = map_box
    return left - margin <= x <= right + margin and top - margin <= y <= bottom + margin


def draw_route_condition_halos(image, route, route_values, map_box, bounds):
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    for point, value in zip(route.get("sample_points", []), route_values):
        x, y = project(point["longitude"], point["latitude"], map_box, bounds)
        color = rgba_for_wave(value, alpha=120)
        overlay_draw.ellipse((x - 145, y - 145, x + 145, y + 145), fill=color)
    overlay = overlay.filter(ImageFilter.GaussianBlur(42))
    image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))


def rgba_for_wave(value, alpha=255):
    hex_color = segment_color_for_wave(value)
    return tuple(int(hex_color[index : index + 2], 16) for index in (1, 3, 5)) + (alpha,)


def segment_color_for_wave(value):
    if value is None or value != value:
        return MUTED
    if value >= 1.8:
        return RED
    if value >= 1.2:
        return YELLOW
    return GREEN


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


def draw_current_context(draw, route, route_currents, map_box, bounds):
    fonts = load_fonts()
    for point, current in zip(route.get("sample_points", []), route_currents):
        x, y = project(point["longitude"], point["latitude"], map_box, bounds)
        speed = current["speed"]
        if speed == 0 or speed != speed:
            continue
        length = min(68, 28 + speed * 130)
        angle = math.atan2(current["v"], current["u"])
        end = (x + math.cos(angle) * length, y - math.sin(angle) * length)
        draw_arrow(draw, (x, y), end, "#d8fbff", width=4)
    draw.text((map_box[0] + 34, map_box[3] - 80), "small arrows: surface current context", font=fonts["micro"], fill=MUTED)


def draw_route(draw, route, map_box, bounds, snapshot, route_values=None):
    points = [(route["origin"]["longitude"], route["origin"]["latitude"])]
    points.extend((point["longitude"], point["latitude"]) for point in route.get("sample_points", []))
    points.append((route["destination"]["longitude"], route["destination"]["latitude"]))
    projected = [project(lon, lat, map_box, bounds) for lon, lat in points]
    color = severity_color(snapshot.get("recommendation", {}).get("vessel_severity"))
    if len(projected) >= 2:
        worst_segment = worst_segment_from_route_values(route_values or [], len(projected) - 1)
        for index, (start, end) in enumerate(zip(projected, projected[1:])):
            local_value = segment_wave_value(route_values or [], index)
            segment_color = color if index == worst_segment else "#d8fbff"
            if index != worst_segment and local_value is not None and local_value >= 1.8:
                segment_color = RED
            width = 16 if index == worst_segment else 8
            draw.line((*start, *end), fill=segment_color, width=width)
    for x, y in projected:
        draw.ellipse((x - 13, y - 13, x + 13, y + 13), fill=TEXT, outline=BG, width=4)
    label_point(draw, route["origin"]["name"], projected[0], dx=22, dy=-50)
    label_point(draw, route["destination"]["name"], projected[-1], dx=22, dy=20)
    if len(projected) >= 2:
        start, end = list(zip(projected, projected[1:]))[worst_segment]
        mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
        label_point(draw, "exposed section", mid, dx=22, dy=-40)


def exposed_segment_index(snapshot, segment_count):
    hourly = snapshot.get("forecast", {}).get("hourly") or []
    if not hourly:
        return max(0, segment_count // 2)
    return max(0, segment_count // 2)


def worst_segment_from_route_values(route_values, segment_count):
    if segment_count <= 0:
        return 0
    valid = [(index, value) for index, value in enumerate(route_values) if value == value]
    if not valid:
        return max(0, segment_count // 2)
    worst_point_index = max(valid, key=lambda item: item[1])[0]
    return max(0, min(segment_count - 1, worst_point_index))


def segment_wave_value(route_values, segment_index):
    candidates = []
    if 0 <= segment_index < len(route_values):
        candidates.append(route_values[segment_index])
    previous = segment_index - 1
    if 0 <= previous < len(route_values):
        candidates.append(route_values[previous])
    valid = [value for value in candidates if value == value]
    if not valid:
        return None
    return max(valid)


def label_point(draw, label, point, dx=12, dy=12):
    font = load_fonts()["small"]
    x, y = point
    draw.text((x + dx, y + dy), label, font=font, fill=TEXT)


def draw_legend(draw, map_box, fonts):
    left, top, right, bottom = map_box
    legend = (left + 34, top + 86, left + 520, top + 200)
    draw.rounded_rectangle(legend, radius=18, fill="#09202a", outline="#164552", width=2)
    draw.text((legend[0] + 24, legend[1] + 18), "Route segment status", font=fonts["small"], fill=TEXT)
    items = [("workable", GREEN), ("conservative", YELLOW), ("restricted", RED)]
    x = legend[0] + 24
    y = legend[1] + 66
    for label, color in items:
        draw.rounded_rectangle((x, y, x + 34, y + 18), radius=9, fill=color)
        draw.text((x + 44, y - 5), label, font=fonts["micro"], fill=MUTED)
        x += 148


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
