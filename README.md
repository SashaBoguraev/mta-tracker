# MyBus

## TO-DO
- [ ] Get the direction for the subway
- [ ] Get rid of the white in the SVG

A simple Python application for the Raspberry Pi that provides real-time transit arrival information for bus stops, trains, and other public transportation. The application continuously monitors and displays live arrival times with an intuitive console interface.

## Features

🚌 **Real-time Arrivals**: Live arrival predictions for buses, trains, and other transit vehicles
🔄 **Auto-refresh**: Automatically updates every 60 seconds
🕒 **Smart Time Display**: Shows both absolute arrival times and countdown minutes
🚦 **Multiple Transit Types**: Supports buses, light rail, heavy rail, commuter rail, and ferries
⚡ **Visual Indicators**: Special highlighting for imminent arrivals (≤5 minutes)

## Requirements

- Python 3.7+
- Virtual environment (required)
- Internet connection for API access
- Required packages (see Installation)

## Installation

**Important**: This application must be run in a virtual environment to avoid conflicts with system packages and ensure proper dependency management.

### 1. Clone this Git

```
git pull https://github.com/richardtheb/mybus
cd mybus
```

### 2. Create and Activate The Virtual Environment
```
python3 -m venv myvenv
source myvenv-env/bin/activate
```
### 3. Install Dependencies
```
pip install -r requirements.txt
```


### 4. Verify Installation

Ensure your virtual environment is active (you should see `(mybus-env)` in your terminal prompt) before running the application.

## Configuration

1. Edit `ProviderConfig.json` and customize it for your transit provider and stop:

```json
{
  "transport_provider": {
    "name": "MBTA",
    "base_url": "https://api-v3.mbta.com",
    "endpoints": {
      "arrivals": "/predictions?filter[stop]={stop_id}&sort=arrival_time"
    },
    "api_key": "YOUR_API_KEY_HERE",
    "headers": {
      "Content-Type": "application/json",
      "Accept": "application/vnd.api+json"
    }
  },
  "bus_stop": {
    "id": "YOUR_STOP_ID",
    "name": "Your Stop Name"
  },
  "request_settings": {
    "timeout": 30,
    "max_arrivals": 10
  }
}
```
Update the configuration with your specific details:
   - **API Key**: Obtain from your transit provider (if required)
   - **Stop ID**: The unique identifier for your transit stop
   - **Base URL**: API endpoint for your transit provider
   - **Stop Name**: Human-readable name for display

## Usage

**⚠️ Important**: Always ensure your virtual environment is activated before running the application.

```
python MyBus.py
```

### Raspberry Pi One-time Setup

If you `git clone` this repo onto a Pi, run:

```bash
./scripts/setup_pi.sh
```

That script installs system packages, builds the `hzeller/rpi-rgb-led-matrix` bindings,
copies the `7x13.bdf` font into `fonts/`, and bootstraps `mybus-env` with all Python
requirements.

Once the helper finishes, activate the environment and start the monitor with the LED matrix backend:

```bash
source mybus-env/bin/activate
MYBUS_DISPLAY_BACKEND=matrix python MyBus.py
```

If you prefer the pygame window instead of the matrix, omit the `MYBUS_DISPLAY_BACKEND` environment variable or use `MYBUS_DISPLAY_BACKEND=pygame`.


The application will:
1. Start monitoring and display "🚀 Starting transit arrival monitoring..."
2. Show live arrivals with route numbers, arrival times, and countdown minutes
3. Refresh automatically every 60 seconds
4. Continue until you press Ctrl-C to stop

### Sample Output

```
Live Arrivals for Massachusetts Ave @ Sidney St
Updated: 2:30:15 PM

Route 1 : 2:35 PM ( 5 minutes)
Route Red : 2:38 PM (8 minutes)
Route 47 : 2:42 PM (12 minutes)
```


## 32x64 RGB LED Matrix Support

If you're driving a 32x64 RGB LED matrix directly off a Raspberry Pi, the
`MyBus` monitor can render a simplified readout using the
[hzeller/rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix)
bindings instead of pygame.

### 1. Install the matrix library on the Pi

1. Clone and build the project (run these as `pi` or another user with
  hardware access):

  ```bash
  git clone https://github.com/hzeller/rpi-rgb-led-matrix ~/rpi-rgb-led-matrix
  cd ~/rpi-rgb-led-matrix
  make build-python PYTHON=$(which python3)
  sudo make install-python PYTHON=$(which python3)
  ```

2. Copy the bundled font files into this repository (or update
  `MATRIX_FONT_PATH` to point to them):

  ```bash
  cp ~/rpi-rgb-led-matrix/fonts/7x13.bdf fonts/
  ```

3. (Optional) Install any extra dependencies mentioned in the matrix README
  such as `libfreetype6-dev` or `libopenjp2-7` before building.

### 2. Configure `MyBus` for the matrix

You can drive the matrix by either setting the environment variable
`MYBUS_DISPLAY_BACKEND=matrix` or adding the optional display section to
`ProviderConfig.json`:

```json
"display": {
  "backend": "matrix",
  "matrix": {
   "rows": 32,
   "cols": 64,
   "chain_length": 1,
   "parallel": 1,
   "hardware_mapping": "adafruit-hat",
   "gpio_slowdown": 2,
   "brightness": 60,
   "font_path": "/home/pi/rpi-rgb-led-matrix/fonts/7x13.bdf",
   "text_color": [255, 255, 0],
   "header_color": [0, 255, 0],
   "max_arrivals": 2
  }
}
```

You only need the `matrix` dictionary when using the LED display. All
values are optional; the defaults assume a single adafruit hat, 60% brightness,
and the bundled 7x13 font.

If you copy the font to a different location, export the override before
starting the script:

```bash
export MATRIX_FONT_PATH=/path/to/7x13.bdf
```

### 3. Run the monitor on the matrix

Make sure the Pi is configured to drive the display (GPIO pins wired,
`rpi-rgb-led-matrix` installed, etc.), then start `MyBus`:

```bash
MYBUS_DISPLAY_BACKEND=matrix python MyBus.py
```

The matrix backend renders the stop name on the top row and two arrival
lines beneath it, along with the current view mode. If the matrix cannot be
initialized (missing font, library, or permissions), the application falls back
to the pygame display automatically.


### Deactivating the Environment
When you're done using the application:
```
deactivate
```


### Reactivating for Future Use
To run the application again later:


```shell script
source myenv/bin/activate
python MyBus.py
```


### Removing the Environment
If you want to completely remove the virtual environment:
```shell script
# Make sure it's deactivated first
deactivate
# Then remove the directory
rm -rf myenv  

```

## Supported Transit Providers

The application is designed to work with any transit API that follows RESTful patterns. It has been tested with:

- **MBTA** (Massachusetts Bay Transportation Authority)
- **MTA** (New York Transit Authority)
- Other GTFS-RT compatible APIs

To add support for other providers, update the `ProviderConfig.json` with the appropriate API endpoints and parameters.

## Key Components

- **API Integration**: Robust HTTP request handling with error recovery
- **Time Calculations**: Accurate arrival time processing with timezone support
- **Display Engine**: Clean console output
- **Configuration System**: Flexible JSON-based setup

## Error Handling

The application includes comprehensive error handling for:
- Network connectivity issues
- API timeouts and errors
- Invalid configuration files
- Missing or malformed data
- Platform-specific keyboard input variations

## Troubleshooting

**Virtual environment issues**:
- Ensure you've activated the virtual environment before running
- Verify the virtual environment was created successfully
- Check that `pip` is installing packages in the correct location

**No arrivals showing**: 
- Verify your stop ID is correct
- Check that your API key is valid (if required)
- Ensure internet connectivity

**Application won't stop**:
- Try Ctrl+C as a fallback
- Check that your terminal supports keyboard input detection

**Configuration errors**:
- Validate your JSON syntax
- Ensure all required fields are present
- Check API endpoint URLs

## Contributing

Feel free to submit issues, feature requests, or pull requests. The code is structured to make it easy to add support for additional transit providers.

When contributing, please ensure you're working within a virtual environment and include any new dependencies in `package_requirements.txt`.

## Author
Richard Baguley & PyCharm AI

## License

This project is open source. Please check with your transit provider regarding their API usage terms and conditions.

