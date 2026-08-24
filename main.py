# SPDX-FileCopyrightText: 2021 ladyada for Adafruit Industries
# SPDX-License-Identifier: MIT

"""
This test will initialize the display using displayio and draw a solid green
background, a smaller purple rectangle, and some yellow text.
"""

import board
import digitalio
import displayio
import terminalio
from adafruit_display_text import label

# Prefer the board-defined display so the correct pins, offsets, and backlight
# wiring are used automatically for this hardware.
display = board.DISPLAY

try:
    display.brightness = 0.8
except AttributeError:
    pass

# -----------------------------------------------------------------------------
# Pimoroni Pico Explorer (PIM720) pin mapping (from Pimoroni MicroPython lib)
# These map 1:1 to CircuitPython's board.GPxx names on RP2040.
# -----------------------------------------------------------------------------
SWITCH_A = board.GP16
SWITCH_B = board.GP15
SWITCH_C = board.GP14
SWITCH_X = board.GP17
SWITCH_Y = board.GP18
SWITCH_Z = board.GP19
SWITCH_USER = board.GP22

I2C_SDA = board.GP20
I2C_SCL = board.GP21

PWM_AUDIO = board.GP12
AMP_EN = board.GP13

# Optional: buttons (pulled-up, active-low)
button_a = digitalio.DigitalInOut(SWITCH_A)
button_a.switch_to_input(pull=digitalio.Pull.UP)

# Make the display context
splash = displayio.Group()
display.root_group = splash

width = display.width
height = display.height

color_bitmap = displayio.Bitmap(width, height, 1)
color_palette = displayio.Palette(1)
color_palette[0] = 0x00FF00  # Bright Green

bg_sprite = displayio.TileGrid(color_bitmap, pixel_shader=color_palette, x=0, y=0)
splash.append(bg_sprite)

# Draw a smaller inner rectangle
inner_bitmap = displayio.Bitmap(width - 40, height - 40, 1)
inner_palette = displayio.Palette(1)
inner_palette[0] = 0xAA0088  # Purple
inner_sprite = displayio.TileGrid(inner_bitmap, pixel_shader=inner_palette, x=20, y=20)
splash.append(inner_sprite)

# Draw a label
text = "Hello World!"
text_group = displayio.Group(scale=2)
text_area = label.Label(terminalio.FONT, text=text, color=0xFFFF00)
text_area.anchor_point = (0.5, 0.5)
text_area.anchored_position = (width // 4, height // 4)
text_group.append(text_area)
splash.append(text_group)

while True:
    pass
