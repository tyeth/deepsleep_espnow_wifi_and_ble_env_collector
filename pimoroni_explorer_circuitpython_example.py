# SPDX-FileCopyrightText: 2026 Pimoroni Explorer 2350 Demo
# SPDX-License-Identifier: MIT

"""
Pimoroni Explorer 2350 Feature Demo

This demo showcases all the features of the Explorer board:
- 2.8" IPS LCD display (320x240, ST7789V)
- 6 tactile buttons (A, B, C, X, Y, Z) + User button
- Piezo speaker with amplifier
- 4 servo outputs
- 6 ADC inputs (A0-A5)
- Status LED
- I2C via Qw/ST connectors

Multi-Sensor Stick sensors (if connected):
- BME280: Temperature, humidity, pressure
- LTR-559: Light and proximity
- ICM20948: 9-DOF IMU (accelerometer, gyroscope, magnetometer)

Controls:
- Button A: Toggle LED
- Button B: Play tone
- Button X: Cycle display pages
- Button Y: Move servo
- Button Z: Reset servo
- Button C: Toggle auto-refresh
- User Button: I2C scan
"""

import time
import board
import digitalio
import pwmio
import analogio
import displayio
import terminalio
from adafruit_display_text import label
from adafruit_display_shapes.rect import Rect
from adafruit_display_shapes.circle import Circle

# =============================================================================
# Hardware Configuration
# =============================================================================

# Buttons (directly on board - directly read, active LOW, directly pull-up)
BUTTON_PINS = {
    "A": board.SW_A,
    "B": board.SW_B,
    "C": board.SW_C,
    "X": board.SW_X,
    "Y": board.SW_Y,
    "Z": board.SW_Z,
    "USER": board.SW_USER,
}

# Servo pins
SERVO_PINS = [board.SERVO1, board.SERVO2, board.SERVO3, board.SERVO4]

# ADC pins
ADC_PINS = [board.A0, board.A1, board.A2, board.A3, board.A4, board.A5]

# Audio
AUDIO_PIN = board.AUDIO
AMP_EN_PIN = board.AMP_EN

# LED
LED_PIN = board.LED

# I2C addresses for Multi-Sensor Stick
BME280_ADDR = 0x76  # or 0x77
LTR559_ADDR = 0x23
ICM20948_ADDR = 0x6a  # or 0x69 (0x68 when AD0 is LOW)

# =============================================================================
# Setup Hardware
# =============================================================================

# Get the built-in display
display = board.DISPLAY

# Setup LED (active-high - standard LED, True=ON, False=OFF)
led = digitalio.DigitalInOut(LED_PIN)
led.direction = digitalio.Direction.OUTPUT
led.value = False  # Start with LED off

# Setup buttons with pull-up (active low)
# Note: USER button has external pull-up on board, don't configure pull
buttons = {}
for name, pin in BUTTON_PINS.items():
    btn = digitalio.DigitalInOut(pin)
    btn.direction = digitalio.Direction.INPUT
    if name != "USER":
        btn.pull = digitalio.Pull.UP
    # USER button has external pull, leave it as-is
    buttons[name] = btn

# Setup amplifier enable
amp_en = digitalio.DigitalInOut(AMP_EN_PIN)
amp_en.direction = digitalio.Direction.OUTPUT
amp_en.value = False  # Start with amp off

# Setup audio PWM (for simple tones)
audio_pwm = None  # Will be created when needed

# Setup servo PWM on first servo pin (for demo)
servo_pwm = pwmio.PWMOut(SERVO_PINS[0], frequency=50, duty_cycle=0)

# Setup ADC inputs
adcs = []
for pin in ADC_PINS:
    try:
        adc = analogio.AnalogIn(pin)
        adcs.append(adc)
    except Exception:
        adcs.append(None)

# Setup I2C
i2c = board.I2C()

# =============================================================================
# Sensor Classes (simplified drivers)
# =============================================================================

class SimpleBME280:
    """Simple BME280 temperature/humidity/pressure sensor driver."""
    
    def __init__(self, i2c, address=0x76):
        self.i2c = i2c
        self.address = address
        self._available = False
        self._check_availability()
    
    def _check_availability(self):
        while not self.i2c.try_lock():
            pass
        try:
            # Use scan to check if device is present (more reliable than empty write)
            devices = self.i2c.scan()
            self._available = self.address in devices
        except OSError:
            self._available = False
        finally:
            self.i2c.unlock()
    
    @property
    def available(self):
        return self._available
    
    def read(self):
        """Returns (temperature_C, humidity_%, pressure_hPa) or None if unavailable."""
        if not self._available:
            return None
        try:
            # For a real implementation, use adafruit_bme280 library
            # This is a placeholder that returns simulated data
            return (22.5, 45.0, 1013.25)
        except Exception:
            return None


class SimpleLTR559:
    """Simple LTR-559 light and proximity sensor driver."""
    
    def __init__(self, i2c, address=0x23):
        self.i2c = i2c
        self.address = address
        self._available = False
        self._check_availability()
    
    def _check_availability(self):
        while not self.i2c.try_lock():
            pass
        try:
            # Use scan to check if device is present (more reliable than empty write)
            devices = self.i2c.scan()
            self._available = self.address in devices
        except OSError:
            self._available = False
        finally:
            self.i2c.unlock()
    
    @property
    def available(self):
        return self._available
    
    def read(self):
        """Returns (light_lux, proximity) or None if unavailable."""
        if not self._available:
            return None
        try:
            # For a real implementation, use adafruit_ltr559 or pimoroni_ltr559 library
            return (100.0, 0)
        except Exception:
            return None


class SimpleICM20948:
    """Simple ICM-20948 9-DOF IMU driver."""
    
    def __init__(self, i2c, address=0x68):
        self.i2c = i2c
        self.address = address
        self._available = False
        self._check_availability()
    
    def _check_availability(self):
        while not self.i2c.try_lock():
            pass
        try:
            # Use scan to check if device is present (more reliable than empty write)
            devices = self.i2c.scan()
            self._available = self.address in devices
        except OSError:
            self._available = False
        finally:
            self.i2c.unlock()
    
    @property
    def available(self):
        return self._available
    
    def read_accel(self):
        """Returns (x, y, z) acceleration in m/s² or None."""
        if not self._available:
            return None
        try:
            # For a real implementation, use adafruit_icm20x library
            return (0.0, 0.0, 9.8)
        except Exception:
            return None


# =============================================================================
# Display UI
# =============================================================================

# Color palette
BLACK = 0x000000
WHITE = 0xFFFFFF
RED = 0xFF0000
GREEN = 0x00FF00
BLUE = 0x0000FF
YELLOW = 0xFFFF00
CYAN = 0x00FFFF
MAGENTA = 0xFF00FF
ORANGE = 0xFF8800
GRAY = 0x888888
DARK_GRAY = 0x444444

# Display pages
PAGE_MAIN = 0
PAGE_SENSORS = 1
PAGE_ADC = 2
PAGE_BUTTONS = 3
NUM_PAGES = 4
PAGE_NAMES = ["Main", "Sensors", "ADC", "Buttons"]

current_page = PAGE_MAIN

def create_main_page():
    """Create the main status page."""
    group = displayio.Group()
    
    # Background
    bg = Rect(0, 0, 320, 240, fill=DARK_GRAY)
    group.append(bg)
    
    # Title
    title = label.Label(
        terminalio.FONT,
        text="Pimoroni Explorer 2350",
        color=CYAN,
        x=60,
        y=15,
        scale=2
    )
    group.append(title)
    
    # Subtitle
    subtitle = label.Label(
        terminalio.FONT,
        text="CircuitPython Demo",
        color=WHITE,
        x=95,
        y=40
    )
    group.append(subtitle)
    
    # Status area
    status_label = label.Label(
        terminalio.FONT,
        text="LED: OFF",
        color=GREEN,
        x=10,
        y=70
    )
    group.append(status_label)
    
    servo_label = label.Label(
        terminalio.FONT,
        text="Servo: 90°",
        color=YELLOW,
        x=10,
        y=90
    )
    group.append(servo_label)
    
    # Instructions
    instructions = [
        "A: Toggle LED    B: Play tone",
        "X: Next page     Y: Move servo",
        "Z: Reset servo   C: Auto-refresh",
        "USER: I2C scan",
    ]
    for i, text in enumerate(instructions):
        lbl = label.Label(
            terminalio.FONT,
            text=text,
            color=WHITE,
            x=10,
            y=130 + i * 20
        )
        group.append(lbl)
    
    # Page indicator
    page_label = label.Label(
        terminalio.FONT,
        text=f"Page 1/{NUM_PAGES}: Main",
        color=ORANGE,
        x=10,
        y=225
    )
    group.append(page_label)
    
    return group, {
        "status": status_label,
        "servo": servo_label,
        "page": page_label,
    }


def create_sensors_page():
    """Create the sensors page for Multi-Sensor Stick."""
    group = displayio.Group()
    
    # Background
    bg = Rect(0, 0, 320, 240, fill=DARK_GRAY)
    group.append(bg)
    
    # Title
    title = label.Label(
        terminalio.FONT,
        text="Multi-Sensor Stick",
        color=CYAN,
        x=70,
        y=15,
        scale=2
    )
    group.append(title)
    
    # BME280 section
    bme_title = label.Label(terminalio.FONT, text="BME280:", color=GREEN, x=10, y=50)
    group.append(bme_title)
    
    temp_label = label.Label(terminalio.FONT, text="Temp: --.-°C", color=WHITE, x=20, y=70)
    group.append(temp_label)
    
    humid_label = label.Label(terminalio.FONT, text="Humid: --.-%", color=WHITE, x=20, y=85)
    group.append(humid_label)
    
    press_label = label.Label(terminalio.FONT, text="Press: ----.-- hPa", color=WHITE, x=20, y=100)
    group.append(press_label)
    
    # LTR559 section
    ltr_title = label.Label(terminalio.FONT, text="LTR-559:", color=GREEN, x=170, y=50)
    group.append(ltr_title)
    
    light_label = label.Label(terminalio.FONT, text="Light: ---- lux", color=WHITE, x=180, y=70)
    group.append(light_label)
    
    prox_label = label.Label(terminalio.FONT, text="Prox: ----", color=WHITE, x=180, y=85)
    group.append(prox_label)
    
    # ICM20948 section
    imu_title = label.Label(terminalio.FONT, text="ICM-20948 Accel:", color=GREEN, x=10, y=130)
    group.append(imu_title)
    
    accel_x = label.Label(terminalio.FONT, text="X: --.-- m/s²", color=WHITE, x=20, y=150)
    group.append(accel_x)
    
    accel_y = label.Label(terminalio.FONT, text="Y: --.-- m/s²", color=WHITE, x=20, y=165)
    group.append(accel_y)
    
    accel_z = label.Label(terminalio.FONT, text="Z: --.-- m/s²", color=WHITE, x=20, y=180)
    group.append(accel_z)
    
    # I2C status
    i2c_status = label.Label(terminalio.FONT, text="I2C: Scanning...", color=YELLOW, x=10, y=205)
    group.append(i2c_status)
    
    # Page indicator
    page_label = label.Label(
        terminalio.FONT,
        text=f"Page 2/{NUM_PAGES}: Sensors",
        color=ORANGE,
        x=10,
        y=225
    )
    group.append(page_label)
    
    return group, {
        "temp": temp_label,
        "humid": humid_label,
        "press": press_label,
        "light": light_label,
        "prox": prox_label,
        "accel_x": accel_x,
        "accel_y": accel_y,
        "accel_z": accel_z,
        "i2c_status": i2c_status,
        "page": page_label,
    }


def create_adc_page():
    """Create the ADC readings page."""
    group = displayio.Group()
    
    # Background
    bg = Rect(0, 0, 320, 240, fill=DARK_GRAY)
    group.append(bg)
    
    # Title
    title = label.Label(
        terminalio.FONT,
        text="ADC Inputs",
        color=CYAN,
        x=100,
        y=15,
        scale=2
    )
    group.append(title)
    
    # ADC labels and bars
    adc_labels = []
    adc_bars = []
    colors = [RED, ORANGE, YELLOW, GREEN, CYAN, BLUE]
    
    for i in range(6):
        y_pos = 50 + i * 28
        
        # Label
        lbl = label.Label(
            terminalio.FONT,
            text=f"A{i}: 0.00V",
            color=WHITE,
            x=10,
            y=y_pos
        )
        group.append(lbl)
        adc_labels.append(lbl)
        
        # Bar background
        bar_bg = Rect(100, y_pos - 6, 200, 12, fill=BLACK)
        group.append(bar_bg)
        
        # Bar foreground (value indicator)
        bar = Rect(100, y_pos - 6, 1, 12, fill=colors[i])
        group.append(bar)
        adc_bars.append(bar)
    
    # Page indicator
    page_label = label.Label(
        terminalio.FONT,
        text=f"Page 3/{NUM_PAGES}: ADC",
        color=ORANGE,
        x=10,
        y=225
    )
    group.append(page_label)
    
    return group, {
        "adc_labels": adc_labels,
        "adc_bars": adc_bars,
        "page": page_label,
    }


def create_buttons_page():
    """Create the button status page."""
    group = displayio.Group()
    
    # Background
    bg = Rect(0, 0, 320, 240, fill=DARK_GRAY)
    group.append(bg)
    
    # Title
    title = label.Label(
        terminalio.FONT,
        text="Button Status",
        color=CYAN,
        x=85,
        y=15,
        scale=2
    )
    group.append(title)
    
    # Button indicators
    button_circles = {}
    button_labels = {}
    
    # Layout: A B C on top row, X Y Z on bottom row, USER in center
    positions = {
        "A": (50, 80),
        "B": (160, 80),
        "C": (270, 80),
        "X": (50, 140),
        "Y": (160, 140),
        "Z": (270, 140),
        "USER": (160, 200),
    }
    
    for name, (x, y) in positions.items():
        # Circle indicator
        circle = Circle(x, y, 20, fill=GRAY, outline=WHITE)
        group.append(circle)
        button_circles[name] = circle
        
        # Label
        lbl = label.Label(
            terminalio.FONT,
            text=name,
            color=WHITE,
            x=x - 8 if len(name) == 1 else x - 16,
            y=y + 30
        )
        group.append(lbl)
        button_labels[name] = lbl
    
    # Page indicator
    page_label = label.Label(
        terminalio.FONT,
        text=f"Page 4/{NUM_PAGES}: Buttons",
        color=ORANGE,
        x=10,
        y=225
    )
    group.append(page_label)
    
    return group, {
        "circles": button_circles,
        "labels": button_labels,
        "page": page_label,
    }


# =============================================================================
# Audio Functions
# =============================================================================

def play_tone(frequency, duration=0.1):
    """Play a tone through the piezo speaker."""
    global audio_pwm
    
    # Enable amplifier
    amp_en.value = True
    
    # Create PWM for audio if needed
    if audio_pwm is None:
        audio_pwm = pwmio.PWMOut(AUDIO_PIN, frequency=frequency, duty_cycle=0, variable_frequency=True)
    else:
        audio_pwm.frequency = frequency
    
    # Play tone (50% duty cycle)
    audio_pwm.duty_cycle = 32768
    time.sleep(duration)
    audio_pwm.duty_cycle = 0
    
    # Disable amplifier
    amp_en.value = False


def play_melody():
    """Play a simple melody."""
    # Simple scale
    notes = [262, 294, 330, 349, 392, 440, 494, 523]  # C4 to C5
    for note in notes:
        play_tone(note, 0.1)
        time.sleep(0.05)


# =============================================================================
# Servo Functions
# =============================================================================

servo_angle = 90

def set_servo_angle(angle):
    """Set servo to a specific angle (0-180 degrees)."""
    global servo_angle
    servo_angle = max(0, min(180, angle))
    
    # Convert angle to duty cycle
    # Typical servo: 1ms (0°) to 2ms (180°) pulse at 50Hz
    # Duty cycle range: ~3276 (2.5%) to ~8192 (6.25%) at 16-bit
    min_duty = 1638   # ~2.5% = 0.5ms
    max_duty = 8192   # ~12.5% = 2.5ms
    duty_range = max_duty - min_duty
    
    duty = int(min_duty + (duty_range * servo_angle / 180))
    servo_pwm.duty_cycle = duty


# =============================================================================
# I2C Functions
# =============================================================================

def scan_i2c():
    """Scan I2C bus and return list of found addresses."""
    while not i2c.try_lock():
        pass
    try:
        devices = i2c.scan()
        return devices
    finally:
        i2c.unlock()


# =============================================================================
# Main Application
# =============================================================================

def main():
    global current_page
    
    print("Pimoroni Explorer 2350 Demo")
    print("=" * 40)
    
    # Initialize sensors
    bme280 = SimpleBME280(i2c, BME280_ADDR)
    ltr559 = SimpleLTR559(i2c, LTR559_ADDR)
    icm20948 = SimpleICM20948(i2c, ICM20948_ADDR)
    
    # Initial I2C scan
    print("Scanning I2C bus...")
    devices = scan_i2c()
    print(f"Found {len(devices)} devices: {[hex(d) for d in devices]}")
    
    # Create display pages
    pages = [
        create_main_page(),
        create_sensors_page(),
        create_adc_page(),
        create_buttons_page(),
    ]
    
    # Set initial page
    display.root_group = pages[current_page][0]
    
    # Initialize servo to center
    set_servo_angle(90)
    
    # Button debounce tracking
    button_states = {name: True for name in buttons}  # True = not pressed (pull-up)
    last_press_time = {name: 0 for name in buttons}
    DEBOUNCE_TIME = 0.2
    
    # Auto-refresh toggle
    auto_refresh = True
    last_refresh = time.monotonic()
    REFRESH_INTERVAL = 0.5
    
    print("Starting main loop...")
    print("Press buttons to interact!")
    
    while True:
        current_time = time.monotonic()
        
        # Read all buttons
        for name, btn in buttons.items():
            current_state = btn.value  # True = not pressed
            prev_state = button_states[name]
            
            # Debug: print USER button state changes
            if name == "USER" and current_state != prev_state:
                print(f"USER button: prev={prev_state}, curr={current_state}")
            
            # Detect button press (transition from not pressed to pressed)
            if prev_state and not current_state:  # Button just pressed
                if current_time - last_press_time[name] > DEBOUNCE_TIME:
                    last_press_time[name] = current_time
                    
                    # Handle button press
                    if name == "A":
                        led.value = not led.value
                        print(f"LED: {'ON' if led.value else 'OFF'}")
                        play_tone(440, 0.05)
                    
                    elif name == "B":
                        print("Playing melody...")
                        play_melody()
                    
                    elif name == "C":
                        auto_refresh = not auto_refresh
                        print(f"Auto-refresh: {'ON' if auto_refresh else 'OFF'}")
                        play_tone(880 if auto_refresh else 220, 0.05)
                    
                    elif name == "X":
                        current_page = (current_page + 1) % NUM_PAGES
                        display.root_group = pages[current_page][0]
                        print(f"Page: {PAGE_NAMES[current_page]}")
                        play_tone(660, 0.05)
                    
                    elif name == "Y":
                        new_angle = servo_angle + 30
                        if new_angle > 180:
                            new_angle = 0
                        set_servo_angle(new_angle)
                        print(f"Servo: {servo_angle}°")
                        play_tone(550, 0.05)
                    
                    elif name == "Z":
                        set_servo_angle(90)
                        print("Servo reset to 90°")
                        play_tone(330, 0.05)
                    
                    elif name == "USER":
                        print("Scanning I2C...")
                        devices = scan_i2c()
                        print(f"Found: {[hex(d) for d in devices]}")
                        # Update sensors page I2C status if available
                        if current_page == PAGE_SENSORS:
                            pages[PAGE_SENSORS][1]["i2c_status"].text = f"I2C: {len(devices)} @ {[hex(d) for d in devices][:3]}"
                        play_tone(770, 0.1)
            
            button_states[name] = current_state
        
        # Always update button page when on it (regardless of auto_refresh)
        if current_page == PAGE_BUTTONS:
            for name, btn in buttons.items():
                pressed = not btn.value
                pages[PAGE_BUTTONS][1]["circles"][name].fill = GREEN if pressed else GRAY
        
        # Update display if auto-refresh is on
        if auto_refresh and (current_time - last_refresh > REFRESH_INTERVAL):
            last_refresh = current_time
            labels = pages[current_page][1]
            
            if current_page == PAGE_MAIN:
                labels["status"].text = f"LED: {'ON' if led.value else 'OFF'}"
                labels["servo"].text = f"Servo: {servo_angle}°"
                labels["page"].text = f"Page {current_page + 1}/{NUM_PAGES}: {PAGE_NAMES[current_page]}"
            
            elif current_page == PAGE_SENSORS:
                # Update BME280
                if bme280.available:
                    data = bme280.read()
                    if data:
                        labels["temp"].text = f"Temp: {data[0]:.1f}°C"
                        labels["humid"].text = f"Humid: {data[1]:.1f}%"
                        labels["press"].text = f"Press: {data[2]:.2f} hPa"
                else:
                    labels["temp"].text = "Temp: N/A"
                    labels["humid"].text = "Humid: N/A"
                    labels["press"].text = "Press: N/A"
                
                # Update LTR559
                if ltr559.available:
                    data = ltr559.read()
                    if data:
                        labels["light"].text = f"Light: {data[0]:.0f} lux"
                        labels["prox"].text = f"Prox: {data[1]}"
                else:
                    labels["light"].text = "Light: N/A"
                    labels["prox"].text = "Prox: N/A"
                
                # Update ICM20948
                if icm20948.available:
                    accel = icm20948.read_accel()
                    if accel:
                        labels["accel_x"].text = f"X: {accel[0]:+.2f} m/s²"
                        labels["accel_y"].text = f"Y: {accel[1]:+.2f} m/s²"
                        labels["accel_z"].text = f"Z: {accel[2]:+.2f} m/s²"
                else:
                    labels["accel_x"].text = "X: N/A"
                    labels["accel_y"].text = "Y: N/A"
                    labels["accel_z"].text = "Z: N/A"
                
                # I2C status
                devices = scan_i2c()
                labels["i2c_status"].text = f"I2C: {len(devices)} devices"
            
            elif current_page == PAGE_ADC:
                for i, adc in enumerate(adcs):
                    if adc is not None:
                        try:
                            raw = adc.value
                            voltage = raw * 3.3 / 65535
                            labels["adc_labels"][i].text = f"A{i}: {voltage:.2f}V"
                            # Update bar width (0-200 pixels for 0-3.3V)
                            bar_width = max(1, int(voltage / 3.3 * 200))
                            labels["adc_bars"][i].width = bar_width
                        except Exception:
                            labels["adc_labels"][i].text = f"A{i}: Error"
                    else:
                        labels["adc_labels"][i].text = f"A{i}: N/A"
            
            elif current_page == PAGE_BUTTONS:
                for name, btn in buttons.items():
                    pressed = not btn.value
                    labels["circles"][name].fill = GREEN if pressed else GRAY
        
        # Small delay to prevent CPU hogging
        time.sleep(0.01)


# Run the main application
if __name__ == "__main__":
    main()

