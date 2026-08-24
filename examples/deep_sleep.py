# SPDX-FileCopyrightText: 2026 Deep Sleep Example for PMSA003I
# SPDX-License-Identifier: MIT

"""
Deep Sleep CircuitPython example for PMSA003I particulate matter sensor.

Hardware setup:
- I2C on GP20 (SDA) and GP21 (SCL)
- PMSA003I SET pin connected to GP0
- GP1 connected from GP0 via a resistor with two LEDs reversed in parallel
  (allows visual indication of pin state in either direction)

The PMSA003I SET pin:
- HIGH = sensor active (normal operation)
- LOW  = sensor in standby/sleep mode (low power)

This example demonstrates:
1. Checking boot/wake reason
2. Performing I2C scan immediately after boot
3. Restoring GPIO state from sleep memory
4. Using PinAlarm to maintain SET pin state during deep sleep
"""

import time
import board
import busio
import digitalio
import alarm

# =============================================================================
# Configuration
# =============================================================================
I2C_SDA = board.GP20
I2C_SCL = board.GP21

SET_PIN = board.GP0      # PMSA003I SET pin (controls sensor active/standby)
LED_PIN = board.GP1      # LED indicator pin (connected via resistor from GP0)

PMSA003I_I2C_ADDR = 0x12  # Default I2C address for PMSA003I

# Sleep memory layout (persists across deep sleep)
# Byte 0: GPIO0 (SET pin) state before sleep (0 or 1)
# Byte 1: GPIO1 (LED pin) state before sleep (0 or 1)
# Byte 2: Boot count
SLEEP_MEM_GPIO0 = 0
SLEEP_MEM_GPIO1 = 1
SLEEP_MEM_BOOT_COUNT = 2

# How long to stay awake before going back to sleep (seconds)
AWAKE_TIME = 10
# How long to deep sleep (seconds)
SLEEP_TIME = 30

# =============================================================================
# Helper functions
# =============================================================================

def get_boot_reason() -> str:
    """Determine and return a string describing the boot/wake reason."""
    wake = alarm.wake_alarm
    if wake is None:
        return "POWER_ON or RESET (no alarm)"
    elif isinstance(wake, alarm.time.TimeAlarm):
        return "TimeAlarm (scheduled wake)"
    elif isinstance(wake, alarm.pin.PinAlarm):
        return f"PinAlarm on {wake.pin}"
    else:
        return f"Unknown alarm type: {type(wake)}"


def scan_i2c(i2c: busio.I2C) -> list:
    """Scan I2C bus and return list of found addresses."""
    while not i2c.try_lock():
        pass
    try:
        devices = i2c.scan()
        return devices
    finally:
        i2c.unlock()


def format_i2c_devices(devices: list) -> str:
    """Format I2C device list as hex addresses."""
    if not devices:
        return "No devices found"
    return ", ".join(f"0x{addr:02X}" for addr in devices)


# =============================================================================
# Main program
# =============================================================================

print("\n" + "=" * 60)
print("PMSA003I Deep Sleep Test")
print("=" * 60)

# -----------------------------------------------------------------------------
# 1. Check boot/wake reason FIRST (before any other operations)
# -----------------------------------------------------------------------------
boot_reason = get_boot_reason()
print(f"\nBoot reason: {boot_reason}")

# Track boot count in sleep memory
if alarm.wake_alarm is None:
    # First boot (power on or reset) - initialize sleep memory
    alarm.sleep_memory[SLEEP_MEM_BOOT_COUNT] = 0
    alarm.sleep_memory[SLEEP_MEM_GPIO0] = 1  # Default SET pin HIGH (sensor active)
    alarm.sleep_memory[SLEEP_MEM_GPIO1] = 1  # Default LED pin HIGH
    print("First boot - initialized sleep memory")
else:
    # Woke from sleep - increment boot count
    alarm.sleep_memory[SLEEP_MEM_BOOT_COUNT] = (
        alarm.sleep_memory[SLEEP_MEM_BOOT_COUNT] + 1
    ) % 256

boot_count = alarm.sleep_memory[SLEEP_MEM_BOOT_COUNT]
print(f"Boot count: {boot_count}")

# -----------------------------------------------------------------------------
# 2. I2C scan IMMEDIATELY after boot (before GPIO initialization)
#    This lets us see if the sensor is visible based on pre-sleep pin state
# -----------------------------------------------------------------------------
print("\n--- I2C Scan (before GPIO init) ---")
try:
    i2c = busio.I2C(I2C_SCL, I2C_SDA)
    devices = scan_i2c(i2c)
    print(f"I2C devices found: {format_i2c_devices(devices)}")
    
    if PMSA003I_I2C_ADDR in devices:
        print(f"✓ PMSA003I detected at 0x{PMSA003I_I2C_ADDR:02X}")
    else:
        print(f"✗ PMSA003I NOT detected (expected 0x{PMSA003I_I2C_ADDR:02X})")
        print("  (Sensor may be in standby if SET pin was LOW)")
except Exception as e:
    print(f"I2C error: {e}")
    i2c = None

# -----------------------------------------------------------------------------
# 3. Initialize GPIO and restore state from sleep memory
# -----------------------------------------------------------------------------
print("\n--- GPIO Initialization ---")

# Read saved states from sleep memory
saved_gpio0_state = bool(alarm.sleep_memory[SLEEP_MEM_GPIO0])
saved_gpio1_state = bool(alarm.sleep_memory[SLEEP_MEM_GPIO1])
print(f"Saved GPIO0 (SET) state: {saved_gpio0_state}")
print(f"Saved GPIO1 (LED) state: {saved_gpio1_state}")

# Initialize SET pin (GP0) - controls PMSA003I active/standby
set_pin = digitalio.DigitalInOut(SET_PIN)
set_pin.direction = digitalio.Direction.OUTPUT
set_pin.value = saved_gpio0_state  # Restore saved state
print(f"SET pin (GP0) initialized to: {set_pin.value}")

# Initialize LED pin (GP1) - visual indicator
led_pin = digitalio.DigitalInOut(LED_PIN)
led_pin.direction = digitalio.Direction.OUTPUT
led_pin.value = saved_gpio1_state  # Restore saved state
print(f"LED pin (GP1) initialized to: {led_pin.value}")

# -----------------------------------------------------------------------------
# 4. Do some work while awake
# -----------------------------------------------------------------------------
print(f"\n--- Awake for {AWAKE_TIME} seconds ---")

# If sensor is now active, try reading it
if set_pin.value and i2c is not None:
    print("SET pin is HIGH - sensor should be active")
    # Give sensor time to wake up if it was just enabled
    time.sleep(1)
    
    # Re-scan to confirm sensor is now visible
    devices = scan_i2c(i2c)
    print(f"I2C devices (after SET=HIGH): {format_i2c_devices(devices)}")

# Blink LED to show we're awake
print("Blinking LED to indicate awake state...")
for i in range(5):
    led_pin.value = True
    time.sleep(0.2)
    led_pin.value = False
    time.sleep(0.2)

# Restore LED to saved state after blinking
led_pin.value = saved_gpio1_state

# Wait remaining awake time
remaining = AWAKE_TIME - 3  # Account for blink time
if remaining > 0:
    print(f"Waiting {remaining} more seconds...")
    time.sleep(remaining)

# -----------------------------------------------------------------------------
# 5. Prepare for deep sleep
# -----------------------------------------------------------------------------
print("\n--- Preparing for Deep Sleep ---")

# Decide what state to leave pins in during sleep
# For power saving: SET=LOW puts PMSA003I in standby
# For quick wake: SET=HIGH keeps sensor active (but uses more power)
#
# For this demo, we'll alternate: even boot counts = standby, odd = active
sleep_set_state = bool(boot_count % 2)  # Alternates each boot
sleep_led_state = sleep_set_state       # LED follows SET pin

print(f"Boot count {boot_count} -> SET pin will be {'HIGH (active)' if sleep_set_state else 'LOW (standby)'}")

# Save the states we want to wake up with
alarm.sleep_memory[SLEEP_MEM_GPIO0] = int(sleep_set_state)
alarm.sleep_memory[SLEEP_MEM_GPIO1] = int(sleep_led_state)

# Set the pin values BEFORE creating the alarm
# This ensures the pins are in the correct state when we enter deep sleep
set_pin.value = sleep_set_state
led_pin.value = sleep_led_state
print(f"SET pin set to: {set_pin.value}")
print(f"LED pin set to: {led_pin.value}")

# -----------------------------------------------------------------------------
# 6. Create alarms and enter deep sleep
# -----------------------------------------------------------------------------

# TimeAlarm - wake up after SLEEP_TIME seconds
time_alarm = alarm.time.TimeAlarm(monotonic_time=time.monotonic() + SLEEP_TIME)

# PinAlarm on GP0 (SET pin)
# This configures the pin during deep sleep:
# - value: the pin level that will trigger wake (we set opposite of sleep state
#          so any external toggle will wake us)
# - pull: True enables internal resistor to hold pin at opposite of 'value'
#         Since we want to maintain sleep_set_state, we need to be careful:
#         - If value=False and pull=True -> pull-up enabled (pin held HIGH)
#         - If value=True and pull=True -> pull-down enabled (pin held LOW)
#
# We want to HOLD the pin at sleep_set_state, so:
# - If sleep_set_state=True (HIGH), set value=False, pull=True -> pull-up holds HIGH
# - If sleep_set_state=False (LOW), set value=True, pull=True -> pull-down holds LOW

pin_alarm = alarm.pin.PinAlarm(
    pin=SET_PIN,
    value=not sleep_set_state,  # Wake on opposite of our desired hold state
    pull=True                   # Enable pull resistor (direction auto-set opposite of value)
)

print(f"\nPinAlarm configured:")
print(f"  - value={not sleep_set_state} (wake on {'LOW' if sleep_set_state else 'HIGH'})")
print(f"  - pull=True ({'pull-up' if not sleep_set_state else 'pull-down'} to hold {'HIGH' if sleep_set_state else 'LOW'})")

print(f"\nEntering deep sleep for {SLEEP_TIME} seconds...")
print("(Will also wake on SET pin state change)")
print("=" * 60 + "\n")

# Deinit I2C before sleep (good practice)
if i2c is not None:
    i2c.deinit()

# Enter deep sleep - does not return!
# The pin states set by digitalio will be maintained, and the PinAlarm
# will configure the internal pull resistor to reinforce the SET pin state.
alarm.exit_and_deep_sleep_until_alarms(time_alarm, pin_alarm)

# This line is never reached
print("This should never print!")
