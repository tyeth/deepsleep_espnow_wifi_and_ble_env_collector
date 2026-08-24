# minimal 3.52" quad eInk wiring demo (FeatherWing pins D9/D10, no reset/busy)
import time
import board
import displayio
import terminalio
import vectorio
from fourwire import FourWire
import adafruit_jd79667
from adafruit_display_text import label

displayio.release_displays()
spi = board.SPI()
bus = FourWire(spi, command=board.D10, chip_select=board.D9,
               reset=None, baudrate=1000000)
time.sleep(1)
display = adafruit_jd79667.JD79667(
    bus, width=384, height=184, busy_pin=None, rotation=270,
    colstart=0, highlight_color=0xFFFF00, highlight_color2=0xFF0000)
print("demo: display %dx%d ttr=%.1fs" %
      (display.width, display.height, display.time_to_refresh))

def pal(c):
    p = displayio.Palette(1)
    p[0] = c
    return p

W, H = display.width, display.height
g = displayio.Group()
g.append(vectorio.Rectangle(pixel_shader=pal(0xFFFFFF), width=W, height=H, x=0, y=0))
bw = (W - 32) // 3
g.append(vectorio.Rectangle(pixel_shader=pal(0x000000), width=bw, height=48, x=8, y=8))
g.append(vectorio.Rectangle(pixel_shader=pal(0xFF0000), width=bw, height=48, x=16 + bw, y=8))
g.append(vectorio.Rectangle(pixel_shader=pal(0xFFFF00), width=bw, height=48, x=24 + 2 * bw, y=8))
g.append(label.Label(terminalio.FONT, text="ENVHUB quad OK", color=0x000000,
                     x=8, y=80, scale=2))
g.append(label.Label(terminalio.FONT, text="blk/red/yel + corner marks",
                     color=0xFF0000, x=8, y=104))
for (x, y) in ((0, 0), (W - 6, 0), (0, H - 6), (W - 6, H - 6)):
    g.append(vectorio.Rectangle(pixel_shader=pal(0x000000), width=6, height=6, x=x, y=y))
display.root_group = g
for attempt in range(60):
    try:
        display.refresh()
        print("demo: refresh sent (attempt %d) - panel flashes ~20s" % attempt)
        break
    except RuntimeError:
        time.sleep(5)  # "Refresh too soon": eInk min-interval still running
else:
    print("demo: panel never accepted a refresh")
