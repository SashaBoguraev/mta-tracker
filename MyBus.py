import json
import requests
import logging
from datetime import datetime, timezone
import pytz
from multiprocessing import Queue
import os
import pygame
import time
import io

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics
    _HAS_RGBMATRIX = True
except ImportError:
    RGBMatrix = None
    RGBMatrixOptions = None
    graphics = None
    _HAS_RGBMATRIX = False

# Display configuration
DISPLAY_BACKEND_ENV_VAR = "MYBUS_DISPLAY_BACKEND"
FONT_PATH_ENV_VAR = "MATRIX_FONT_PATH"
DEFAULT_DISPLAY_BACKEND = 'matrix' if _HAS_RGBMATRIX else 'pygame'

try:
    import cairosvg
    _HAS_CAIROSVG = True
except Exception:
    cairosvg = None
    _HAS_CAIROSVG = False

# Initialize Pygame
pygame.init()

# Constants for display
SCREEN_WIDTH = 720
# Make height half the width so height:width == 1:2
SCREEN_HEIGHT = SCREEN_WIDTH // 2
BACKGROUND_COLOR = (0, 0, 0)  # Black
TEXT_COLOR = (255, 255, 0)  # Yellow
HEADER_COLOR = (255, 255, 255)  # White
ARRIVAL_COLOR = (0, 255, 0)  # Green
WARNING_COLOR = (255, 165, 0)  # Orange
URGENT_COLOR = (255, 0, 0)  # Red

# Fonts
header_font = pygame.font.Font(None, 46)
route_font = pygame.font.Font(None, 38)
time_font = pygame.font.Font(None, 32)
small_font = pygame.font.Font(None, 28)
STOP_TEXT_LEFT_OFFSET = 0
MATRIX_CENTER_MARGIN = 8


def _extract_after_nassau_av(stop_name):
    """Return the substring after 'Nassau Av/' (case-insensitive)."""
    if not stop_name:
        return None
    marker = 'nassau av/'
    lower_name = stop_name.lower()
    idx = lower_name.find(marker)
    if idx == -1:
        return None
    tail = stop_name[idx + len(marker):].strip()
    return tail or None


def _is_subway_or_rail_route(route_type):
    """Detect whether a route type string refers to heavy rail/subway."""
    if not route_type:
        return False
    lowered = str(route_type).lower()
    return any(token in lowered for token in ('subway', 'rail', 'heavy'))


def get_arrival_center_label(arrival):
    """Determine the friendly center label for an arrival row."""
    if not isinstance(arrival, dict):
        return 'Transit'

    if _is_subway_or_rail_route(arrival.get('route_type')):
        destination = arrival.get('destination') or arrival.get('route_long_name')
        if destination:
            return destination

    cross_street = _extract_after_nassau_av(arrival.get('stop_name'))
    if cross_street:
        return cross_street

    return (
        arrival.get('stop_name')
        or arrival.get('route_long_name')
        or arrival.get('route_short_name')
        or 'Transit'
    )


class BusArrivalDisplay:
    def __init__(self):
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("Live Bus Arrivals")
        self.clock = pygame.time.Clock()
        self.running = True
        # view_mode controls which arrivals are shown: 'combined', 'subway', or 'bus'
        self.view_mode = 'combined'
        # Try to load a logo from the `logo` directory (optional)
        self.logo = None
        # Cache for per-route logos (pygame.Surface)
        self.route_logos = {}
        try:
            logo_path = os.path.join(os.path.dirname(__file__), 'logo', 'MTA-Metropolitan-Transportation-Authority-Logo.png')
            if os.path.exists(logo_path):
                img = pygame.image.load(logo_path).convert_alpha()
                # Scale logo to fit footer height (target ~40px tall)
                target_h = min(40, SCREEN_HEIGHT // 6)
                w = int(img.get_width() * (target_h / img.get_height()))
                self.logo = pygame.transform.smoothscale(img, (w, target_h))
        except Exception as e:
            logging.warning(f"Could not load logo image: {e}")

    def _route_logo_path(self, route_short_name):
        """Return the expected path for a route logo file (prefer svg then png)."""
        if not route_short_name:
            return None
        base = os.path.join(os.path.dirname(__file__), 'logo', 'routes')

        # Candidate name variants to try, in order
        raw = str(route_short_name).strip()
        candidates = []
        candidates.append(raw)
        # alphanumeric only (strip punctuation/whitespace)
        import re
        alnum = re.sub(r'[^A-Za-z0-9]', '', raw)
        if alnum and alnum not in candidates:
            candidates.append(alnum)
        # first character (common for multi-letter IDs like 'NQRW')
        if alnum:
            first = alnum[0]
            if first and first not in candidates:
                candidates.append(first)

        # Try each candidate for png first (prefer pre-generated PNGs), then svg
        for name in candidates:
            name_l = name.lower()
            png_path = os.path.join(base, f"{name_l}.png")
            svg_path = os.path.join(base, f"{name_l}.svg")
            if os.path.exists(png_path):
                return png_path
            if os.path.exists(svg_path):
                return svg_path

        return None

    def load_route_logo(self, route_short_name, target_h=48):
        """Load and cache a route logo as a pygame.Surface.

        Supports SVG -> PNG conversion at runtime if cairosvg is available; otherwise
        attempts to load PNG directly. Returns None on failure.
        """
        if not route_short_name:
            return None

        key = str(route_short_name).upper()
        if key in self.route_logos:
            return self.route_logos[key]

        path = self._route_logo_path(route_short_name)
        if not path:
            self.route_logos[key] = None
            return None

        try:
            if path.lower().endswith('.svg'):
                if not _HAS_CAIROSVG:
                    logging.warning("cairosvg not available; cannot load SVG logos. Install cairosvg to enable route logos.")
                    self.route_logos[key] = None
                    return None

                # Convert SVG bytes to PNG bytes
                with open(path, 'rb') as f:
                    svg_bytes = f.read()
                png_bytes = cairosvg.svg2png(bytestring=svg_bytes)
                surf = pygame.image.load(io.BytesIO(png_bytes), 'png')
            else:
                surf = pygame.image.load(path).convert_alpha()

            # Scale to height target_h while preserving aspect
            w = int(surf.get_width() * (target_h / surf.get_height()))
            surf = pygame.transform.smoothscale(surf, (w, target_h))
            self.route_logos[key] = surf
            return surf
        except Exception as e:
            logging.warning(f"Failed to load route logo for {route_short_name}: {e}")
            self.route_logos[key] = None
            return None

    def get_arrival_color(self, minutes_to_arrival):
        """Get color based on arrival time"""
        if minutes_to_arrival is None:
            return TEXT_COLOR
        elif minutes_to_arrival == 0:
            return URGENT_COLOR
        elif minutes_to_arrival <= 5:
            return WARNING_COLOR
        else:
            return ARRIVAL_COLOR

    def get_route_color(self, route_short_name):
        """Return a color for the route badge using simple MTA-like heuristics.

        Default is white. Currently maps borough prefixes (e.g., 'B' for Brooklyn)
        to a blue badge similar to the example image. This is intentionally
        simple and can be replaced with a fuller mapping if you provide one.
        """
        if not route_short_name:
            return HEADER_COLOR

        r = str(route_short_name).upper()

        # Basic heuristic mapping; tweak these RGB tuples to taste
        if r.startswith('B'):
            # Brooklyn buses — blue like the attached example
            return (30, 115, 190)
        if r.startswith('M'):
            # Manhattan — use a darker red
            return (200, 16, 46)
        if r.startswith('Q'):
            # Queens — teal
            return (0, 128, 128)
        if r.startswith('S'):
            # Staten Island / Special — orange
            return (255, 140, 0)

        # Fallback: white
        return HEADER_COLOR


    def draw_header(self, stop_name):
        """Draw the header section"""
        # Main title
        title_text = header_font.render("Live Bus Arrivals", True, HEADER_COLOR)
        title_rect = title_text.get_rect(center=(SCREEN_WIDTH // 2, 30))
        self.screen.blit(title_text, title_rect)

        # Stop name
        stop_text = route_font.render(f"{stop_name}", True, TEXT_COLOR)
        stop_rect = stop_text.get_rect(center=(SCREEN_WIDTH // 2, 65))
        self.screen.blit(stop_text, stop_rect)

        # Current time
        current_time = datetime.now().strftime('%I:%M:%S %p')
        time_text = time_font.render(f"Updated: {current_time}", True, TEXT_COLOR)
        time_rect = time_text.get_rect(center=(SCREEN_WIDTH // 2, 90))
        self.screen.blit(time_text, time_rect)

        # Separator line
        pygame.draw.line(self.screen, TEXT_COLOR, (50, 110), (SCREEN_WIDTH - 50, 110), 2)

    def draw_column_headers(self):
        """Draw column headers"""
        # Intentionally left blank for subway-style stop list
        return

    def draw_footer(self):
        """Draw a small last-updated footer at the bottom of the screen"""
        current_time = datetime.now().strftime('%I:%M:%S %p')
        # Center timestamp
        footer_text = small_font.render(f"Last Updated: {current_time}", True, HEADER_COLOR)
        footer_rect = footer_text.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 24))
        self.screen.blit(footer_text, footer_rect)
        # Show current view mode on the bottom-right
        try:
            mode_label = self.view_mode.capitalize()
        except Exception:
            mode_label = 'Combined'
        mode_text = small_font.render(f"View: {mode_label}", True, HEADER_COLOR)
        mode_rect = mode_text.get_rect(midright=(SCREEN_WIDTH - 12, SCREEN_HEIGHT - 24))
        self.screen.blit(mode_text, mode_rect)
        # If a logo was loaded, draw it to the bottom-left above the footer
        if getattr(self, 'logo', None):
            logo_x = 10
            logo_y = SCREEN_HEIGHT - self.logo.get_height() - 8
            self.screen.blit(self.logo, (logo_x, logo_y))

    def set_view(self, mode):
        """Set the current view mode. Expected values: 'combined', 'subway', 'bus'."""
        if mode not in ('combined', 'subway', 'bus'):
            return
        self.view_mode = mode

    def draw_arrivals(self, arrivals):
        """Render a simple list where each row shows:
        left: route short name (e.g., B48)
        center: stop name
        right: minutes until arrival
        """

        if not arrivals:
            return

        line_height = 64
        # Place the first row flush to the top: center the text vertically on the
        # first row by using half the line height as the starting y coordinate.
        start_y = line_height // 2
        max_visible = (SCREEN_HEIGHT - start_y) // line_height
        visible = arrivals[:max_visible]

        left_x = 80
        right_x = SCREEN_WIDTH - 80

        for i, item in enumerate(visible):
            y_pos = start_y + i * line_height

            # Extract display pieces with sensible fallbacks
            route = item.get('route_short_name') or item.get('route_long_name') or item.get('route_short') or '—'
            stop = item.get('stop_name') or item.get('route_long_name') or 'Unknown'
            minutes = item.get('minutes_to_arrival')

            # Format minutes text
            if minutes is None:
                minutes_text = '—'
            elif minutes == 0:
                minutes_text = 'Now'
            else:
                minutes_text = f"{minutes} min"

            # Colors
            minutes_color = self.get_arrival_color(minutes)

            # Render left: use a route logo only for non-bus routes (subway/trains).
            # Buses should remain as text per user request.
            route_type_val = str(item.get('route_type') or '').lower()
            is_bus = 'bus' in route_type_val
            logo_surf = None
            if not is_bus:
                logo_surf = self.load_route_logo(route, target_h=48)
            if logo_surf:
                # Align logo vertically centered on the row
                logo_rect = logo_surf.get_rect(midleft=(left_x - 24, y_pos))
                self.screen.blit(logo_surf, logo_rect)
            else:
                route_color = self.get_route_color(route)
                left_surf = route_font.render(str(route), True, route_color)
                left_rect = left_surf.get_rect(midleft=(left_x, y_pos))
                self.screen.blit(left_surf, left_rect)

            center_text_value = get_arrival_center_label(item)

            # All non-badge text should be white on the LED background; anchor stop text near the left column
            center_surf = route_font.render(str(center_text_value), True, HEADER_COLOR)
            center_start_x = left_x + STOP_TEXT_LEFT_OFFSET
            center_rect = center_surf.get_rect(midleft=(center_start_x, y_pos))
            self.screen.blit(center_surf, center_rect)

            # Minutes text in white (user requested white text except for the line badge)
            right_surf = time_font.render(str(minutes_text), True, HEADER_COLOR)
            right_rect = right_surf.get_rect(midright=(right_x, y_pos))
            self.screen.blit(right_surf, right_rect)

            # Separator between rows
            if i < len(visible) - 1:
                sep_y = y_pos + line_height // 2 - 6
                pygame.draw.line(self.screen, (64, 64, 64), (50, sep_y), (SCREEN_WIDTH - 50, sep_y), 1)

    def draw_no_arrivals(self):
        """Draw message when no arrivals available"""
        no_data_text = route_font.render("🔭 No arrival information available", True, WARNING_COLOR)
        no_data_rect = no_data_text.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2))
        self.screen.blit(no_data_text, no_data_rect)
        # Footer will display last-updated time; keep the main message centered

    def display_arrivals(self, arrivals):
        """Main display function - replaces the console print version"""
        # Handle pygame events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                    return False

        # Clear screen
        self.screen.fill(BACKGROUND_COLOR)

        if arrivals:
            # Draw arrivals list and footer (header removed per user request)
            self.draw_arrivals(arrivals)
            self.draw_footer()
        else:
            self.draw_no_arrivals()
            self.draw_footer()

        # Update display
        pygame.display.flip()
        self.clock.tick(60)
        return True

    def cleanup(self):
        """Clean up pygame resources"""
        pygame.quit()


if _HAS_RGBMATRIX:
    class MatrixBusArrivalDisplay:
        """Simple display for 32x64 RGB matrices"""

        def __init__(self, matrix_config=None):
            matrix_config = matrix_config or {}
            options = RGBMatrixOptions()
            options.rows = matrix_config.get('rows', 32)
            options.cols = matrix_config.get('cols', 64)
            options.chain_length = matrix_config.get('chain_length', 1)
            options.parallel = matrix_config.get('parallel', 1)
            options.hardware_mapping = matrix_config.get('hardware_mapping', 'adafruit-hat')
            options.gpio_slowdown = matrix_config.get('gpio_slowdown', 2)
            options.pwm_bits = matrix_config.get('pwm_bits', 11)
            options.brightness = matrix_config.get('brightness', 60)
            self.matrix = RGBMatrix(options=options)
            self.canvas = self.matrix.CreateFrameCanvas()
            self.rows = options.rows
            self.cols = options.cols
            self.font = graphics.Font()

            font_path = matrix_config.get('font_path') or os.environ.get(FONT_PATH_ENV_VAR)
            if not font_path:
                font_path = os.path.join(os.path.dirname(__file__), 'fonts', '7x13.bdf')
            if not os.path.exists(font_path):
                raise FileNotFoundError(
                    f"Matrix font not found at {font_path}. "
                    f"Set {FONT_PATH_ENV_VAR} or copy the font from hzeller/rpi-rgb-led-matrix/fonts."
                )
            self.font.LoadFont(font_path)

            self.compact_mode = matrix_config.get('compact_mode', True)
            preferred_lines = matrix_config.get('max_lines', 4)
            preferred_lines = max(1, preferred_lines)

            if 'line_height' in matrix_config:
                self.line_height = max(1, matrix_config['line_height'])
            else:
                self.line_height = max(6, (self.rows - 1) // preferred_lines)
                if self.compact_mode:
                    self.line_height = max(6, min(self.line_height, self.font.height))

            self.row_spacing = max(0, matrix_config.get('row_spacing', 0))
            self.top_padding = max(0, matrix_config.get('top_padding', 0))

            self.row_height = max(self.line_height, self.font.height)
            self.row_stride = max(1, self.row_height + self.row_spacing)

            available_rows = max(0, self.rows - self.top_padding)
            computed_lines = max(1, available_rows // self.row_stride)
            self.max_lines = min(preferred_lines, computed_lines)
            if self.max_lines < 1:
                self.max_lines = 1

            self.max_chars = matrix_config.get('max_chars', max(4, self.cols // 6))
            arrivals_capacity = max(1, self.max_lines)
            requested_arrivals = matrix_config.get('max_arrivals')
            if requested_arrivals is None:
                requested_arrivals = arrivals_capacity
            self.max_arrivals = max(1, min(arrivals_capacity, requested_arrivals))

            self.text_color = graphics.Color(*matrix_config.get('text_color', (255, 255, 0)))
            self.header_color = graphics.Color(*matrix_config.get('header_color', (0, 255, 0)))
            self.warning_color = graphics.Color(255, 165, 0)
            self.urgent_color = graphics.Color(255, 0, 0)
            self.route_color_overrides = {
                'G': graphics.Color(0, 255, 0),
                'B': graphics.Color(30, 115, 190),
            }
            self.view_mode = 'combined'

        def set_view(self, mode):
            self.view_mode = mode

        def _truncate_text(self, text, max_chars=None):
            if not text:
                return ''
            limit = self.max_chars if max_chars is None else max(1, max_chars)
            return text[:limit]

        def _text_width(self, text):
            if not text:
                return 0
            char_width_func = getattr(self.font, 'CharacterWidth', None)
            if callable(char_width_func):
                total = 0
                for ch in text:
                    try:
                        total += char_width_func(ord(ch))
                    except Exception:
                        total += max(1, getattr(self.font, 'height', 8) // 2)
                return total
            return len(text) * max(1, getattr(self.font, 'height', 8) // 2)

        def _get_route_color(self, route_name):
            if not route_name:
                return self.text_color
            key = route_name.strip().upper()
            for prefix, color in self.route_color_overrides.items():
                if key.startswith(prefix):
                    return color
            return self.text_color

        def _format_center_text(self, arrival):
            center_label = get_arrival_center_label(arrival)
            return self._truncate_text(center_label)

        def _format_minutes_text(self, minutes):
            if minutes is None:
                return '--', self.text_color
            if minutes == 0:
                return 'Now', self.urgent_color
            text = f"{minutes}m"
            color = self.warning_color if minutes <= 5 else self.text_color
            return text, color

        def _build_rows(self, arrivals):
            rows = []
            if not arrivals:
                rows.append({'type': 'message', 'text': self._truncate_text('No arrivals')})
                return rows

            for arrival in arrivals[: self.max_arrivals]:
                route_name = arrival.get('route_short_name') or arrival.get('route_long_name') or 'Route'
                route_label = self._truncate_text(route_name, max_chars=4)
                center_text = self._format_center_text(arrival)
                minutes_text, minutes_color = self._format_minutes_text(arrival.get('minutes_to_arrival'))
                rows.append({
                    'type': 'arrival',
                    'route_label': route_label,
                    'route_color': self._get_route_color(route_name),
                    'center_text': center_text,
                    'minutes_text': minutes_text,
                    'minutes_color': minutes_color,
                })

            return rows[: self.max_lines]

        def _draw_arrival_row(self, row, y):
            route_x = 1
            route_text = row['route_label']
            graphics.DrawText(self.canvas, self.font, route_x, y, row['route_color'], route_text)
            route_width = self._text_width(route_text)

            center_text = row['center_text']
            center_width = self._text_width(center_text)
            center_margin = MATRIX_CENTER_MARGIN
            center_left = route_x + route_width + center_margin
            max_allowed = max(1, self.cols - center_width - 1)
            center_x = min(center_left, max_allowed)
            graphics.DrawText(self.canvas, self.font, center_x, y, self.header_color, center_text)

            minutes_text = row['minutes_text']
            minutes_width = self._text_width(minutes_text)
            minutes_x = self.cols - minutes_width - 1
            min_overlap = center_x + center_width + 6
            if minutes_x < min_overlap:
                minutes_x = min_overlap
            minutes_x = min(minutes_x, max(1, self.cols - minutes_width - 1))
            graphics.DrawText(self.canvas, self.font, minutes_x, y, row['minutes_color'], minutes_text)

        def display_arrivals(self, arrivals):
            self.canvas.Clear()
            rows = self._build_rows(arrivals)
            for idx, row in enumerate(rows):
                row_top = self.top_padding + idx * self.row_stride
                y = row_top + self.row_height
                if row['type'] == 'message':
                    msg_text = row['text']
                    msg_width = self._text_width(msg_text)
                    msg_x = max(1, (self.cols - msg_width) // 2)
                    graphics.DrawText(self.canvas, self.font, msg_x, y, self.warning_color, msg_text)
                else:
                    self._draw_arrival_row(row, y)
            self.canvas = self.matrix.SwapOnVSync(self.canvas)
            return True

        def cleanup(self):
            self.matrix.Clear()

else:
    MatrixBusArrivalDisplay = None


# Global display instance
if MatrixBusArrivalDisplay:
    DISPLAY_BACKENDS = {
        'pygame': BusArrivalDisplay,
        'matrix': MatrixBusArrivalDisplay,
    }
else:
    DISPLAY_BACKENDS = {'pygame': BusArrivalDisplay}


def _determine_display_backend():
    config = load_config() or {}
    display_config = config.get('display', {}) or {}
    backend = os.environ.get(DISPLAY_BACKEND_ENV_VAR) or display_config.get('backend')
    if not backend:
        backend = DEFAULT_DISPLAY_BACKEND
    if backend not in DISPLAY_BACKENDS:
        logging.warning(f"Display backend '{backend}' is not supported. Falling back to pygame.")
        backend = 'pygame'
    return backend, display_config


bus_display = None


def input_thread(a_list):
    raw_input()  # use input() in Python3
    a_list.append(True)


def safe_get_nested_value(data, *keys, default=None):
    """Safely get nested dictionary values"""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key, default)
        else:
            return default
    return data


def load_config(config_path="ProviderConfig.json"):
    """Load configuration with error handling"""
    try:
        with open(config_path, 'r') as file:
            config = json.load(file)
        return config
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.error(f"Failed to load config: {e}")
        return None


def make_api_request(url, headers=None, timeout=30):
    """Make API request with proper error handling"""
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()  # Raises an HTTPError for bad responses
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"API request failed: {e}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"Failed to parse JSON response: {e}")
        return None


def calculate_time_to_arrival(arrival_time_str):
    """Calculate time to arrival in minutes"""
    if not arrival_time_str:
        return None

    try:
        # Parse the arrival time (ISO format)
        arrival_time = datetime.fromisoformat(arrival_time_str.replace('Z', '+00:00'))

        # Get current time in the same timezone
        current_time = datetime.now(timezone.utc)

        # Calculate difference in minutes
        time_diff = arrival_time - current_time
        minutes_to_arrival = int(time_diff.total_seconds() / 60)

        return minutes_to_arrival if minutes_to_arrival > 0 else 0
    except (ValueError, TypeError) as e:
        logging.warning(f"Could not parse arrival time {arrival_time_str}: {e}")
        return None


def format_arrival_time(arrival_time_str):
    """Format arrival time for display"""
    if not arrival_time_str:
        return "Unknown"

    try:
        # Parse the arrival time and convert to local time
        arrival_time = datetime.fromisoformat(arrival_time_str.replace('Z', '+00:00'))

        # Convert to Eastern Time (MBTA is in Boston)
        eastern = pytz.timezone('US/Eastern')
        local_time = arrival_time.astimezone(eastern)

        return local_time.strftime('%I:%M %p')
    except (ValueError, TypeError):
        return arrival_time_str


def calculate_time_to_arrival_from_epoch(epoch_seconds):
    """Calculate minutes to arrival when provided an epoch seconds string/number."""
    if not epoch_seconds:
        return None

    try:
        ts = int(str(epoch_seconds))
        arrival_time = datetime.fromtimestamp(ts, timezone.utc)
        current_time = datetime.now(timezone.utc)
        time_diff = arrival_time - current_time
        minutes_to_arrival = int(time_diff.total_seconds() / 60)
        return minutes_to_arrival if minutes_to_arrival > 0 else 0
    except (ValueError, TypeError) as e:
        logging.warning(f"Could not parse epoch arrival time {epoch_seconds}: {e}")
        return None


def extract_route_info(included_data, route_id):
    """Extract route information from included data"""
    if not included_data or not route_id:
        return {"short_name": "Unknown", "long_name": "Unknown Route"}

    for item in included_data:
        if item.get('type') == 'route' and item.get('id') == route_id:
            attributes = item.get('attributes', {})
            return {
                "short_name": attributes.get('short_name', 'Unknown'),
                "long_name": attributes.get('long_name', 'Unknown Route'),
                "route_type": attributes.get('type', 0)
            }

    return {"short_name": "Unknown", "long_name": "Unknown Route", "route_type": 0}


def get_route_type_name(route_type):
    """Convert route type number to readable name"""
    route_types = {
        0: "Light Rail",
        1: "Heavy Rail",
        2: "Commuter Rail",
        3: "Bus",
        4: "Ferry"
    }
    return route_types.get(route_type, "Transit")



def get_bus_arrivals():
    """Get bus arrivals with comprehensive error handling"""
    # Load configuration
    config = load_config()
    if config is None:
        logging.error("Configuration not available")
        return []

    # Extract configuration values safely
    provider_config = config.get('transport_provider', {})
    bus_stop = config.get('bus_stop', {})
    request_settings = config.get('request_settings', {})

    base_url = provider_config.get('base_url')
    endpoint_template = safe_get_nested_value(provider_config, 'endpoints', 'arrivals')
    api_key = provider_config.get('api_key')
    headers = provider_config.get('headers', {})
    # Support multiple stops: prefer 'bus_stops' (list), fall back to single 'bus_stop'
    stops_config = config.get('bus_stops') or [bus_stop]
    timeout = request_settings.get('timeout', 30)
    max_arrivals = request_settings.get('max_arrivals', 10)

    # Validate required parameters
    if not all([base_url, endpoint_template]):
        logging.error("Missing required configuration parameters")
        return []

    # The config places the '##KEY##' placeholder in base_url. Replace it there
    if api_key and base_url:
        base_url = base_url.replace("##KEY##", api_key)

    # Prefer the JSON endpoint so make_api_request can parse JSON responses
    if base_url and ".xml" in base_url:
        base_url = base_url.replace('.xml', '.json', 1)

    # Helper to parse a single response payload for a given stop name
    def parse_arrivals_from_response(data, stop_name_local, limit):
        parsed = []
        if not data:
            return parsed

        # SIRI response
        if isinstance(data, dict) and 'Siri' in data:
            deliveries = data.get('Siri', {}).get('ServiceDelivery', {}).get('StopMonitoringDelivery', [])
            for delivery in deliveries:
                visits = delivery.get('MonitoredStopVisit', [])
                for visit in visits:
                    mvj = visit.get('MonitoredVehicleJourney', {})
                    route_short = mvj.get('PublishedLineName') or mvj.get('LineRef') or 'Unknown'
                    route_long = route_short
                    direction = mvj.get('DirectionRef')
                    monitored_call = mvj.get('MonitoredCall', {})
                    arrival_time = monitored_call.get('ExpectedArrivalTime') or monitored_call.get('AimedArrivalTime') or monitored_call.get('ExpectedDepartureTime')

                    if not arrival_time:
                        arrival_time = mvj.get('ExpectedArrivalTime') or mvj.get('AimedArrivalTime')

                    if arrival_time:
                        minutes_to_arrival = calculate_time_to_arrival(arrival_time)
                        formatted_time = format_arrival_time(arrival_time)
                        parsed.append({
                            'route_short_name': route_short,
                            'route_long_name': route_long,
                            'route_type': get_route_type_name(3),
                            'arrival_time': arrival_time,
                            'formatted_time': formatted_time,
                            'minutes_to_arrival': minutes_to_arrival,
                            'direction_id': direction,
                            'status': mvj.get('ProgressStatus') or mvj.get('Monitored'),
                            'stop_name': stop_name_local
                        })

        else:
            # Fallback: assume JSON:API style
            predictions = data.get('data', [])
            included_data = data.get('included', [])
            for prediction in predictions:
                attributes = prediction.get('attributes', {})
                relationships = prediction.get('relationships', {})
                arrival_time = attributes.get('arrival_time')
                departure_time = attributes.get('departure_time')
                predicted_time = arrival_time or departure_time
                if predicted_time:
                    route_relationship = relationships.get('route', {})
                    route_data = route_relationship.get('data', {})
                    route_id = route_data.get('id') if route_data else None
                    route_info = extract_route_info(included_data, route_id)
                    minutes_to_arrival = calculate_time_to_arrival(predicted_time)
                    formatted_time = format_arrival_time(predicted_time)
                    parsed.append({
                        'route_short_name': route_info['short_name'],
                        'route_long_name': route_info['long_name'],
                        'route_type': get_route_type_name(route_info.get('route_type', 3)),
                        'arrival_time': predicted_time,
                        'formatted_time': formatted_time,
                        'minutes_to_arrival': minutes_to_arrival,
                        'direction_id': attributes.get('direction_id'),
                        'status': attributes.get('status'),
                        'stop_name': stop_name_local
                    })

        parsed.sort(key=lambda x: x['arrival_time'] if x['arrival_time'] else '')
        return parsed[:limit]

    # Iterate over configured stops and aggregate arrivals
    all_arrivals = []
    for s in stops_config:
        stop_id = s.get('id')
        stop_name = s.get('name', f"Stop {stop_id}")
        if not stop_id:
            continue

        endpoint = endpoint_template.replace("STOP_ID", stop_id)
        url = f"{base_url}{endpoint}&MaximumStopVisits={max_arrivals}"

        # Copy headers and attach api key header if present
        req_headers = headers.copy() if headers else {}
        if api_key:
            req_headers['X-API-Key'] = api_key

        # Fetch and parse
        data = make_api_request(url, req_headers, timeout)
        parsed_for_stop = parse_arrivals_from_response(data, stop_name, max_arrivals)
        all_arrivals.extend(parsed_for_stop)

    # Final sort across all stops and limit total results
    all_arrivals.sort(key=lambda x: x['arrival_time'] if x['arrival_time'] else '')
    return all_arrivals[:max_arrivals]


def get_subway_arrivals():
    """Fetch subway arrivals from a Transiter instance (realtimerail.nyc style).

    Expects `subway_provider` and `subway_stops` in ProviderConfig.json. The
    Transiter stop endpoint returns `stopTimes` with `arrival.time` as epoch
    seconds which we convert and normalize to the same arrival dict format.
    """
    config = load_config()
    if config is None:
        logging.error("Configuration not available for subway provider")
        return []

    provider = config.get('subway_provider')
    stops_config = config.get('subway_stops', [])
    request_settings = config.get('request_settings', {})
    timeout = request_settings.get('timeout', 30)
    max_arrivals = request_settings.get('max_arrivals', 10)

    if not provider or not provider.get('base_url') or not provider.get('endpoints', {}).get('stop'):
        # Nothing configured
        return []

    base_url = provider.get('base_url')
    endpoint_template = provider.get('endpoints', {}).get('stop')
    headers = provider.get('headers', {})

    all_arrivals = []
    for s in stops_config:
        stop_id = s.get('id')
        stop_name = s.get('name', f"Stop {stop_id}")
        if not stop_id:
            continue

        endpoint = endpoint_template.replace('STOP_ID', stop_id)
        # Ensure proper concatenation; base_url typically ends with '/'
        url = f"{base_url}{endpoint}"

        data = make_api_request(url, headers, timeout)
        if not data:
            continue

        # Transiter may return either a single stop object (for /stops/{id})
        # or an envelope with `stops` (for /stops?ids=...). Handle both.
        if isinstance(data, dict) and 'stops' in data:
            stops_list = data.get('stops', [])
        else:
            # Assume `data` is itself a stop object
            stops_list = [data]

        for stop_obj in stops_list:
            stop_times = stop_obj.get('stopTimes', [])
            for st in stop_times:
                arrival_epoch = safe_get_nested_value(st, 'arrival', 'time') or safe_get_nested_value(st, 'departure', 'time')
                if not arrival_epoch:
                    continue

                # Compute minutes and ISO arrival time
                try:
                    ts = int(str(arrival_epoch))
                    arrival_dt = datetime.fromtimestamp(ts, timezone.utc)
                    arrival_iso = arrival_dt.isoformat()
                except Exception:
                    arrival_iso = None

                minutes_to_arrival = calculate_time_to_arrival_from_epoch(arrival_epoch)
                formatted_time = format_arrival_time(arrival_iso) if arrival_iso else "Unknown"

                # Route/trip info
                trip = st.get('trip', {})
                route = safe_get_nested_value(trip, 'route', 'id') or safe_get_nested_value(trip, 'route', 'name')
                destination = safe_get_nested_value(trip, 'destination', 'name') or safe_get_nested_value(st, 'destination', 'name')

                all_arrivals.append({
                    'route_short_name': route or '—',
                    'route_long_name': destination or route or 'Subway',
                    'route_type': get_route_type_name(1),  # Heavy rail / subway
                    'arrival_time': arrival_iso,
                    'formatted_time': formatted_time,
                    'minutes_to_arrival': minutes_to_arrival,
                    'direction_id': st.get('directionId'),
                    'status': st.get('future', True),
                    'stop_name': stop_name,
                    'track': st.get('track')
                })

    # Sort by arrival_time (ISO) if available, otherwise leave order
    def _sort_key(x):
        try:
            return x['arrival_time'] or ''
        except Exception:
            return ''

    all_arrivals.sort(key=_sort_key)
    return all_arrivals[:max_arrivals]


def display_arrivals(arrivals):
    """Display arrival information using pygame"""
    global bus_display

    if bus_display is None:
        backend, display_config = _determine_display_backend()
        if backend == 'matrix':
            matrix_conf = display_config.get('matrix', {})
            try:
                bus_display = MatrixBusArrivalDisplay(matrix_conf)
            except Exception as exc:
                logging.warning(f"Matrix display failed to initialize ({exc}); falling back to pygame.")
                bus_display = BusArrivalDisplay()
        else:
            bus_display = BusArrivalDisplay()

    # Use the pygame display instead of console prints
    return bus_display.display_arrivals(arrivals)


def run_monitoring():
    global bus_display

    q = Queue()
    print("🚀 Starting transit arrival monitoring...")
    print("❸️  Press ESC in the display window to stop")
    print()

    try:
        # Mode cycling: 'combined' -> 'subway' -> 'bus'
        modes = ['combined', 'subway', 'bus']
        mode_index = 0
        switch_interval = 20  # seconds
        last_switch = time.time()

        while True:
            # Fetch bus and subway lists separately so we can choose which to show
            bus_list = []
            subway_list = []

            try:
                bus_list = get_bus_arrivals() or []
            except Exception as e:
                logging.warning(f"Error fetching bus arrivals: {e}")

            try:
                subway_list = get_subway_arrivals() or []
            except Exception as e:
                logging.warning(f"Error fetching subway arrivals: {e}")

            # Determine current mode and switch if interval passed
            now = time.time()
            if now - last_switch >= switch_interval:
                mode_index = (mode_index + 1) % len(modes)
                last_switch = now
                # Update display label if already created
                if bus_display is not None:
                    bus_display.set_view(modes[mode_index])

            current_mode = modes[mode_index]

            # Choose arrivals according to current mode
            if current_mode == 'combined':
                # In combined mode, show at most 4 items from each provider
                per_type_max = 4
                arrivals = []
                arrivals.extend(bus_list[:per_type_max])
                arrivals.extend(subway_list[:per_type_max])
            elif current_mode == 'subway':
                arrivals = list(subway_list)
            else:  # 'bus'
                arrivals = list(bus_list)

            # Interleave providers (or single provider) by soonest arrival.
            # If minutes_to_arrival is missing, treat it as very far in the future.
            try:
                cfg = load_config() or {}
                req_settings = cfg.get('request_settings', {})
                overall_limit = req_settings.get('max_arrivals', 10)

                def sort_key(item):
                    m = item.get('minutes_to_arrival')
                    # None -> large value so it sorts to the end
                    if m is None:
                        return (1, float('inf'), item.get('arrival_time') or '')
                    return (0, int(m), item.get('arrival_time') or '')

                arrivals.sort(key=sort_key)
                # Trim to overall limit across providers
                arrivals = arrivals[:overall_limit]
            except Exception as e:
                logging.warning(f"Error sorting/limiting arrivals: {e}")

            # Display using pygame - returns False if user wants to quit
            if not display_arrivals(arrivals):
                break

            # Small delay to prevent excessive CPU usage
            time.sleep(1)

    except KeyboardInterrupt:
        print("Monitoring stopped by user")
    finally:
        if bus_display:
            bus_display.cleanup()


def main():
    """Main function with error handling"""
    try:
        run_monitoring()
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        print("❌ An error occurred while running the monitoring system")
    finally:
        # Ensure pygame is properly cleaned up
        if 'bus_display' in globals() and bus_display:
            bus_display.cleanup()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING,  # Changed to WARNING to reduce console noise
                        format='%(asctime)s - %(levelname)s - %(message)s')
    main()
