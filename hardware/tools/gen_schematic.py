#!/usr/bin/env python3
"""Generate the KiCad schematic and an SVG preview of the current hardware.

Usage: python3 hardware/tools/gen_schematic.py

Writes:
  hardware/kicad/esp32_targets.kicad_pro   project (open this in KiCad 6 or newer)
  hardware/kicad/esp32_targets.kicad_sch   root sheet: overview + the two sheets
  hardware/kicad/node.kicad_sch            target node (D1 Mini + battery shield)
  hardware/kicad/hub.kicad_sch             hub (ESP32 DevKit)
  hardware/schematic_preview.svg           the same drawing, viewable without KiCad

Standard library only. The symbols are embedded in the files, so KiCad needs no
extra libraries. All coordinates below are in grid units of 1.27 mm (50 mil);
symbol graphics use KiCad's library convention (y up), placements use the
schematic convention (y down).

Before writing anything the script checks the wiring: every pin is on exactly
one net or marked no-connect, every net matches EXPECTED_NETS, and no wire end
touches a different net. If you edit the schematic in KiCad, KiCad becomes the
source and this script should not be run again (it would overwrite the edits).
"""
import json
import os
import uuid
from xml.sax.saxutils import escape

G = 1.27
DATE = '2026-10-24'
REV = '2.0.1'
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, '..'))
NS = uuid.UUID('6f1c2e1a-4b7d-4f53-9a43-0d1c5e7b2a10')


def uid(*parts):
    """Stable UUIDs, so regenerating gives the same files (clean diffs)."""
    return str(uuid.uuid5(NS, '/'.join(parts)))


def n(v):
    """Grid units -> mm, formatted like KiCad."""
    s = f'{v * G:.4f}'.rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def q(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


FONT = '(effects (font (size 1.27 1.27)))'
FONT_HIDE = '(effects (font (size 1.27 1.27)) hide)'
STROKE_LIB = '(stroke (width 0.254) (type default) (color 0 0 0 0))'
STROKE_THIN = '(stroke (width 0) (type default) (color 0 0 0 0))'


# ---------------------------------------------------------------- symbols

class Pin:
    def __init__(self, num, name, etype, x, y, angle, length):
        self.num, self.name, self.etype = num, name, etype
        self.x, self.y, self.angle, self.length = x, y, angle, length

    def outward(self):
        """Direction from the pin end away from the body, in schematic axes (y down)."""
        return {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}[self.angle]


class SymDef:
    def __init__(self, lib, name, prefix, pins, graphics, body=None, power=False,
                 hide_names=False, hide_numbers=False, desc=''):
        self.lib, self.name, self.prefix = lib, name, prefix
        self.pins = {p.name if not power else 'PWR': p for p in pins}
        self.pin_list = pins
        self.graphics = graphics  # ('rect', x1, y1, x2, y2) | ('line', [(x, y), ...]) | ('circle', x, y, r) | ('text', x, y, s)
        self.body = body          # (x1, y1, x2, y2) in lib units, for text placement
        self.power, self.hide_names, self.hide_numbers = power, hide_names, hide_numbers
        self.desc = desc

    @property
    def lib_id(self):
        return f'{self.lib}:{self.name}'

    def sexpr(self):
        head = [f'(symbol {q(self.lib_id)}']
        if self.power:
            head.append('(power)')
        if self.hide_numbers:
            head.append('(pin_numbers hide)')
        head.append('(pin_names (offset 0) hide)' if self.hide_names else '(pin_names (offset 1.016))')
        head.append('(in_bom yes) (on_board yes)')
        out = [' '.join(head)]
        ref_hide = FONT_HIDE if self.power else FONT
        out.append(f'  (property "Reference" {q(self.prefix)} (id 0) (at 0 0 0) {ref_hide})')
        out.append(f'  (property "Value" {q(self.name)} (id 1) (at 0 0 0) {FONT})')
        out.append(f'  (property "Footprint" "" (id 2) (at 0 0 0) {FONT_HIDE})')
        out.append(f'  (property "Datasheet" "" (id 3) (at 0 0 0) {FONT_HIDE})')
        if self.desc:
            out.append(f'  (property "ki_description" {q(self.desc)} (id 4) (at 0 0 0) {FONT_HIDE})')
        out.append(f'  (symbol {q(self.name + "_0_1")}')
        for g in self.graphics:
            if g[0] == 'rect':
                _, x1, y1, x2, y2 = g
                out.append(f'    (rectangle (start {n(x1)} {n(y1)}) (end {n(x2)} {n(y2)}) {STROKE_LIB} (fill (type background)))')
            elif g[0] == 'line':
                pts = ' '.join(f'(xy {n(x)} {n(y)})' for x, y in g[1])
                out.append(f'    (polyline (pts {pts}) {STROKE_LIB} (fill (type none)))')
            elif g[0] == 'circle':
                _, x, y, r = g
                out.append(f'    (circle (center {n(x)} {n(y)}) (radius {n(r)}) {STROKE_LIB} (fill (type none)))')
            elif g[0] == 'text':
                _, x, y, s = g
                out.append(f'    (text {q(s)} (at {n(x)} {n(y)} 0) {FONT})')
        out.append('  )')
        out.append(f'  (symbol {q(self.name + "_1_1")}')
        for p in self.pin_list:
            hide = ' hide' if self.power else ''
            out.append(f'    (pin {p.etype} line (at {n(p.x)} {n(p.y)} {p.angle}) (length {n(p.length)}){hide}'
                       f' (name {q(p.name)} {FONT}) (number {q(p.num)} {FONT}))')
        out.append('  )')
        out.append(')')
        return '\n'.join(out)


def side_pins(names, x, top, angle, first_num, etypes):
    """A column of pins 2 grid units apart, from y=top downwards."""
    pins = []
    for i, name in enumerate(names):
        pins.append(Pin(str(first_num + i), name, etypes.get(name, 'bidirectional'), x, top - 2 * i, angle, 2))
    return pins


def module(name, prefix, half_w, half_h, left, right, top=(), bottom=(), etypes=None, numbers=None, desc=''):
    etypes = etypes or {}
    pins = []
    pins += side_pins(left, -half_w - 2, (len(left) - 1), 0, 1, etypes)
    pins += side_pins(right, half_w + 2, (len(right) - 1), 180, len(pins) + 1, etypes)
    for i, nm in enumerate(top):
        x = (i - (len(top) - 1) / 2) * 4
        pins.append(Pin(str(len(pins) + 1), nm, etypes.get(nm, 'passive'), x, half_h + 2, 270, 2))
    for i, nm in enumerate(bottom):
        x = (i - (len(bottom) - 1) / 2) * 4
        pins.append(Pin(str(len(pins) + 1), nm, etypes.get(nm, 'passive'), x, -half_h - 2, 90, 2))
    if numbers:
        for p in pins:
            p.num = numbers[p.name]
    return SymDef('targets', name, prefix, pins, [('rect', -half_w, half_h, half_w, -half_h)],
                  body=(-half_w, half_h, half_w, -half_h), desc=desc)


# Wemos D1 Mini, logical layout: power on top/bottom, header pins on the sides
# (in the same top-to-bottom order as the real headers). Pin numbers follow the
# headers: 1-8 the left header (RST..3V3), 9-16 the right header (TX..5V).
D1_LEFT = ['RST', 'A0', 'D0/GPIO16', 'D5/GPIO14', 'D6/GPIO12', 'D7/GPIO13', 'D8/GPIO15']
D1_RIGHT = ['TX/GPIO1', 'RX/GPIO3', 'D1/GPIO5', 'D2/GPIO4', 'D3/GPIO0', 'D4/GPIO2']
D1_NUM = {nm: str(i + 1) for i, nm in enumerate(D1_LEFT + ['3V3'])}
D1_NUM.update({nm: str(i + 9) for i, nm in enumerate(D1_RIGHT + ['GND', '5V'])})
D1_MINI = module('WeMos_D1_Mini', 'U', 10, 10, D1_LEFT, D1_RIGHT, top=['5V', '3V3'], bottom=['GND'],
                 etypes={'RST': 'input', 'A0': 'input', 'TX/GPIO1': 'output', 'RX/GPIO3': 'input',
                         '5V': 'power_in', '3V3': 'power_out', 'GND': 'power_in'},
                 numbers=D1_NUM, desc='WeMos D1 Mini, ESP8266 module with CH340 USB serial')

# Wemos battery shield v1.3: charges and boosts a 1S Li-ion cell to 5 V on the
# stacked header. Its J2 jumper and 130k resistor are drawn as their own parts.
SHIELD = module('WeMos_Battery_Shield', 'U', 5, 4, ['B+', 'B-'], [], top=['5V'], bottom=['GND'],
                etypes={'5V': 'power_out', 'GND': 'power_out'},
                desc='WeMos D1 Mini battery shield v1.3 (charger + 5 V boost), stacked on the D1 Mini')

SW420 = module('SW-420_Module', 'M', 4, 3, ['DO'], [], top=['VCC'], bottom=['GND'],
               etypes={'DO': 'output', 'VCC': 'power_in', 'GND': 'power_in'},
               desc='SW-420 vibration sensor module (comparator, digital out)')

WS2812 = module('WS2812B', 'D', 5, 4, ['DIN'], ['DOUT'], top=['VDD'], bottom=['VSS'],
                etypes={'DIN': 'input', 'DOUT': 'output', 'VDD': 'power_in', 'VSS': 'power_in'},
                numbers={'VDD': '1', 'DOUT': '2', 'VSS': '3', 'DIN': '4'},
                desc='WS2812B addressable RGB LED')

ESP_LEFT = ['EN', 'GPIO36/VP', 'GPIO39/VN', 'GPIO34', 'GPIO35', 'GPIO32', 'GPIO33', 'GPIO25',
            'GPIO26', 'GPIO27', 'GPIO14', 'GPIO12', 'GPIO13']
ESP_RIGHT = ['GPIO23', 'GPIO22', 'TX0/GPIO1', 'RX0/GPIO3', 'GPIO21', 'GPIO19', 'GPIO18', 'GPIO5',
             'TX2/GPIO17', 'RX2/GPIO16', 'GPIO4', 'GPIO2', 'GPIO15']
# DOIT DevKit V1 (30 pins): left header 1-15 top to bottom (EN..GND, VIN), right header 16-30 (GPIO23..GND, 3V3)
ESP_NUM = {nm: str(i + 1) for i, nm in enumerate(ESP_LEFT + ['GND', 'VIN'])}
ESP_NUM.update({nm: str(i + 16) for i, nm in enumerate(ESP_RIGHT + ['GND_2', '3V3'])})
ESP32 = module('ESP32_DevKit_30pin', 'U', 10, 14, ESP_LEFT, ESP_RIGHT, top=['VIN', '3V3'], bottom=['GND', 'GND_2'],
               etypes={'EN': 'input', 'GPIO36/VP': 'input', 'GPIO39/VN': 'input', 'GPIO34': 'input',
                       'GPIO35': 'input', 'TX0/GPIO1': 'output', 'RX0/GPIO3': 'input',
                       'VIN': 'power_in', '3V3': 'power_out', 'GND': 'power_in', 'GND_2': 'power_in'},
               numbers=ESP_NUM, desc='ESP32 DevKit (ESP32-D0WD-V3, CP2102), 30-pin DOIT layout')
for _p in ESP32.pin_list:
    if _p.name == 'GND_2':
        _p.name = 'GND'  # same name on both GND pins, as on the board
ESP32.pins = {('GND_2' if p.num == ESP_NUM['GND_2'] else p.name): p for p in ESP32.pin_list}


def two_pin_h(name, prefix, graphics, end, desc):
    """Horizontal two-pin part, pins 1 (left) and 2 (right) at x = -3 / +3."""
    pins = [Pin('1', '1', 'passive', -3, 0, 0, 3 - end), Pin('2', '2', 'passive', 3, 0, 180, 3 - end)]
    return SymDef('targets', name, prefix, pins, graphics, hide_names=True, hide_numbers=True, desc=desc)


def two_pin_v(name, prefix, graphics, end, desc):
    """Vertical two-pin part, + (1) on top and - (2) at the bottom, at y = +3 / -3."""
    pins = [Pin('1', '+', 'passive', 0, 3, 270, 3 - end), Pin('2', '-', 'passive', 0, -3, 90, 3 - end)]
    return SymDef('targets', name, prefix, pins, graphics, hide_names=True, hide_numbers=True, desc=desc)


RES = two_pin_h('R', 'R', [('rect', -2, 0.7, 2, -0.7)], 2, 'Resistor')
SWITCH = two_pin_h('SW_SPST', 'SW', [('circle', -1.7, 0, 0.3), ('circle', 1.7, 0, 0.3),
                                     ('line', [(-1.45, 0.2), (1.6, 1.2)])], 2, 'On/off switch')
JUMPER2 = two_pin_h('Jumper_2', 'JP', [('rect', -1.7, 0.8, -0.3, -0.8), ('rect', 0.3, 0.8, 1.7, -0.8)], 1.7,
                    'Two-pad solder jumper')
BATTERY = two_pin_v('Battery_Cell', 'BT', [('line', [(-1.5, 0.5), (1.5, 0.5)]), ('line', [(-0.8, -0.5), (0.8, -0.5)]),
                                           ('text', 1.6, 1.5, '+')], 0.5, 'Single Li-ion cell')
CAP_POL = two_pin_v('C_Polarized', 'C', [('line', [(-1.5, 0.4), (1.5, 0.4)]),
                                         ('line', [(-1.5, -0.8), (0, -0.4), (1.5, -0.8)]),
                                         ('text', -1.6, 1.4, '+')], 0.4, 'Polarized capacitor')
CAP_POL.pins['-'].length = 2.6
JUMPER3 = SymDef('targets', 'Jumper_3', 'JP', [
    Pin('1', 'A', 'passive', -3, 0, 0, 0.5), Pin('2', 'C', 'passive', 0, -3, 90, 2.2),
    Pin('3', 'B', 'passive', 3, 0, 180, 0.5)],
    [('rect', -2.5, 0.8, -0.9, -0.8), ('rect', -0.7, 0.8, 0.7, -0.8), ('rect', 0.9, 0.8, 2.5, -0.8),
     ('text', -1.7, 1.6, 'A'), ('text', 1.7, 1.6, 'B')],
    hide_names=True, hide_numbers=True, desc='Three-pad solder jumper (bridge C to A or to B)')


def power_sym(name, up):
    if up:
        gfx = [('line', [(0, 0), (0, 2)]), ('line', [(-0.6, 1), (0, 2), (0.6, 1)])]
    else:
        gfx = [('line', [(0, 0), (0, -1), (1, -1), (0, -2), (-1, -1), (0, -1)])]
    pin = Pin('1', name, 'power_in', 0, 0, 90 if up else 270, 0)
    s = SymDef('power', name, '#PWR', [pin], gfx, power=True, desc=f'Power symbol, global net {name}')
    s.up = up
    return s


P5V, P3V3, PGND = power_sym('+5V', True), power_sym('+3V3', True), power_sym('GND', False)


# ---------------------------------------------------------------- sheets

class Placed:
    def __init__(self, sheet, sym, ref, value, x, y, in_bom=True, ref_at=None, val_at=None, align=None):
        self.sheet, self.sym, self.ref, self.value = sheet, sym, ref, value
        self.x, self.y, self.in_bom = x, y, in_bom
        self.uuid = uid(sheet.name, 'sym', ref)
        b = sym.body
        if sym.power:
            self.ref_at, self.val_at, self.align = (0, 0), ((0, -3.4) if sym.up else (0, 3.8)), 'center'
        elif b:  # module: reference above the top-left corner, value below the bottom-left corner
            self.ref_at = ref_at or (b[0], -b[1] - 0.6)
            self.val_at = val_at or (b[0], -b[3] + 1.6)
            self.align = align or 'left'
        else:    # small part: reference above, value below, centred
            self.ref_at = ref_at or (0, -2.0)
            self.val_at = val_at or (0, 2.0)
            self.align = align or 'center'

    def pin_xy(self, pin):
        p = self.sym.pins[pin]
        return (self.x + p.x, self.y - p.y)


class Sheet:
    def __init__(self, name, file, title, page):
        self.name, self.file, self.title, self.page = name, file, title, page
        self.parts, self.wires, self.labels, self.ncs, self.texts = [], [], [], [], []
        self.nets = {}        # net -> [(ref, pin)]
        self.points = []      # (x, y, net) connection points, for the overlap check
        self.subsheets = []   # (name, file, x, y, w, h, uuid)

    def place(self, sym, ref, value, x, y, **kw):
        p = Placed(self, sym, ref, value, x, y, **kw)
        self.parts.append(p)
        return p

    def _join(self, net, part, pin):
        self.nets.setdefault(net, []).append((part.ref, pin))
        x, y = part.pin_xy(pin)
        self.points.append((x, y, net))

    def wire(self, pts, net):
        for a, b in zip(pts, pts[1:]):
            self.wires.append((a, b, net))
        for x, y in pts:
            self.points.append((x, y, net))

    def stub(self, part, pin, length=2):
        x, y = part.pin_xy(pin)
        dx, dy = part.sym.pins[pin].outward()
        end = (x + dx * length, y + dy * length)
        return (x, y), end, (dx, dy)

    def label(self, part, pin, net, length=2):
        start, end, d = self.stub(part, pin, length)
        self._join(net, part, pin)
        self.wire([start, end], net)
        self.labels.append((net, end, 180 if d[0] < 0 else 0))

    def power(self, part, pin, psym, length=2):
        start, end, d = self.stub(part, pin, length)
        assert d == ((0, -1) if psym.up else (0, 1)), f'{part.ref}.{pin}: power symbols are drawn upright'
        self._join(psym.name, part, pin)
        self.wire([start, end], psym.name)
        k = sum(1 for s in all_power_parts())
        pp = self.place(psym, f'#PWR0{k + 1:02d}', psym.name, *end)
        pp.power_net = psym.name

    def connect(self, a, pa, b, pb, net, corner='vh', label_at_corner=False):
        """Wire two pins: straight if aligned, else one corner ('vh' = vertical first)."""
        (x1, y1), (x2, y2) = a.pin_xy(pa), b.pin_xy(pb)
        if x1 == x2 or y1 == y2:
            pts = [(x1, y1), (x2, y2)]
        else:
            mid = (x1, y2) if corner == 'vh' else (x2, y1)
            pts = [(x1, y1), mid, (x2, y2)]
            if label_at_corner:
                self.labels.append((net, mid, 0))
        self._join(net, a, pa)
        self._join(net, b, pb)
        self.wire(pts, net)

    def nc(self, part, *pins):
        for pin in pins:
            self.ncs.append((part.ref, pin, part.pin_xy(pin)))

    def text(self, x, y, s, size=1.27):
        self.texts.append((x, y, s, size))


SHEETS = []


def all_power_parts():
    return [p for s in SHEETS for p in s.parts if p.sym.power]


# ---- target node -----------------------------------------------------------
node = Sheet('Node', 'node.kicad_sch', 'Target node (one per target, up to 5)', '2')
SHEETS.append(node)

node.text(12, 12, 'TARGET NODE - one per target, up to 5, all identical (same firmware)', 2)
node.text(12, 15, 'As built: WeMos D1 Mini + battery shield (stacked) + SW-420 + one WS2812B. No wires to the hub: ESP-NOW radio.')

# Power: cell -> optional switch -> battery shield (charger + boost to 5 V)
bt1 = node.place(BATTERY, 'BT1', 'Li-ion 3.7V 1S', 20, 31, ref_at=(-2, -0.4), val_at=(-2, 1.2), align='right')
sw1 = node.place(SWITCH, 'SW1', 'Switch (optional)', 28, 26, ref_at=(0, -3.6), val_at=(0, -2.3))
u2 = node.place(SHIELD, 'U2', 'WeMos Battery Shield v1.3', 48, 30, val_at=(0.8, 5.6))
node.connect(bt1, '+', sw1, '1', 'VBAT_SW', corner='vh')
node.connect(sw1, '2', u2, 'B+', 'VBAT', corner='vh', label_at_corner=True)
node.connect(bt1, '-', u2, 'B-', 'BAT-', corner='hv')
node.power(u2, '5V', P5V)
node.power(u2, 'GND', PGND)

# Battery sense, both parts are on the shield: J2 closed -> BAT+ through 130k to A0
jp2 = node.place(JUMPER2, 'JP2', 'J2 (on shield)', 28, 44, in_bom=False, ref_at=(0, -1.8), val_at=(0, 1.8))
r2 = node.place(RES, 'R2', '130k (on shield)', 44, 44, in_bom=False, ref_at=(0, -1.8), val_at=(0, 1.8))
node.label(jp2, '1', 'VBAT')
node.connect(jp2, '2', r2, '1', 'A0_DIV')
node.label(r2, '2', 'A0')
node.text(12, 50, 'BATTERY\n'
          'Shield J2 closed: BAT+ -> 130k -> A0. The D1 Mini has its own 220k/100k divider on A0,\n'
          'so the ADC sees Vbat x 100/450 (1.0 V full scale = 4.5 V, ~4.4 mV per count).\n'
          'Firmware default batt_scale_uv = 4102 assumes 4.2 V full scale: calibrate each target\n'
          'once in the app (Targets > target > Battery calibration) with a multimeter reading.\n'
          'SW1 (optional): with it off the cell is disconnected, so the shield cannot charge it.')

# MCU
u1 = node.place(D1_MINI, 'U1', 'WeMos D1 Mini (ESP8266)', 120, 70, val_at=(1.2, 11.6))
node.power(u1, '5V', P5V)
node.power(u1, '3V3', P3V3)
node.power(u1, 'GND', PGND)
node.label(u1, 'A0', 'A0')
node.label(u1, 'D1/GPIO5', 'SENSOR')
node.label(u1, 'D2/GPIO4', 'LED_D2')
node.label(u1, 'D3/GPIO0', 'LED_D3')
node.nc(u1, 'RST', 'D0/GPIO16', 'D5/GPIO14', 'D6/GPIO12', 'D7/GPIO13', 'D8/GPIO15', 'TX/GPIO1', 'RX/GPIO3', 'D4/GPIO2')
node.text(96, 90, 'Free pins: D0, D5, D6, D7, D8 (and D2 when JP1 is bridged to A).\n'
          'D4/GPIO2 = on-board LED and boot pin. TX/RX = USB serial console.\n'
          'The 3V3 pin is the D1 Mini regulator output (feeds the SW-420).')

# Hit sensor
m1 = node.place(SW420, 'M1', 'SW-420 module', 170, 30, val_at=(0.8, 4.6))
node.power(m1, 'VCC', P3V3)
node.power(m1, 'GND', PGND)
node.label(m1, 'DO', 'SENSOR')
node.text(150, 44, 'HIT SENSOR\n'
          'Power from 3V3 so DO is 3.3 V logic. Rising edge = hit (interrupt on GPIO5).\n'
          'Coarse sensitivity: the module pot. Fine: lockout and pulses in the app.')

# LED: JP1 picks the GPIO, R1 protects the data line, C1 buffers the 5 V rail
jp1 = node.place(JUMPER3, 'JP1', 'LED pin select', 156, 75, ref_at=(0, -4.5), val_at=(0, -3.2))
r1 = node.place(RES, 'R1', '330R', 164, 82)
d1 = node.place(WS2812, 'D1', 'WS2812B', 176, 82, val_at=(0.8, 5.6))
c1 = node.place(CAP_POL, 'C1', '100uF 10V', 192, 82, ref_at=(1.5, -0.6), val_at=(1.5, 1.0), align='left')
node.label(jp1, 'A', 'LED_D3')
node.label(jp1, 'B', 'LED_D2')
node.connect(jp1, 'C', r1, '1', 'LED_SEL', corner='vh')
node.connect(r1, '2', d1, 'DIN', 'LED_DIN')
node.power(d1, 'VDD', P5V)
node.power(d1, 'VSS', PGND)
node.nc(d1, 'DOUT')
node.power(c1, '+', P5V)
node.power(c1, '-', PGND)
node.text(150, 97, 'LED\n'
          'JP1 A = D3/GPIO0 (current targets). JP1 B = D2/GPIO4 (recommended for new\n'
          'targets; set "LED pin" for that target in the app). GPIO0 is a boot pin: if the\n'
          'LED holds it low at power-up, the board starts in flash mode.\n'
          'WS2812B on 5 V with 3.3 V data is marginal (needs 0.7 x VDD) but works for one\n'
          'LED. If it flickers, power the LED from 3V3 instead.\n'
          'R1 330R and C1 100uF: recommended, not fitted on every target.')

# ---- hub --------------------------------------------------------------------
hub = Sheet('Hub', 'hub.kicad_sch', 'Hub (one per kit)', '3')
SHEETS.append(hub)
hub.text(12, 12, 'HUB - one per kit', 2)
hub.text(12, 15, 'Runs the games, the WiFi AP "Airsoft-Master" (app at http://192.168.4.1) and ESP-NOW to the targets.')
u3 = hub.place(ESP32, 'U3', 'ESP32 DevKit (ESP32-D0WD-V3, CP2102)', 110, 70, val_at=(2.6, 17.6))
hub.nc(u3, *ESP_LEFT, *ESP_RIGHT, 'VIN', '3V3', 'GND', 'GND_2')
hub.text(150, 40, 'POWER\n'
         'Micro-USB: USB power bank or charger (about 0.5 W).\n'
         'Nothing else is wired. No PSRAM, 4 MB flash.')
hub.text(150, 52, 'FREE FOR ADD-ONS\n'
         'GPIO4, 5, 13, 14, 16-19, 21-23, 25-27, 32, 33.\n'
         'GPIO34-39: input only, no pull-ups.\n'
         'Avoid GPIO0, 2, 12, 15 (boot straps) and GPIO1/3 (USB serial).')
hub.text(150, 68, 'BOARD VARIANTS\n'
         'Pin numbers follow the 30-pin DOIT DevKit V1. 38-pin boards have\n'
         'the same GPIOs in a different header order: wire by GPIO name.')

# ---- root -------------------------------------------------------------------
root = Sheet('Root', 'esp32_targets.kicad_sch', 'Airsoft reaction targets - hardware overview', '1')
root.text(20, 20, 'AIRSOFT REACTION TARGETS - hardware v2 (as built)', 2.5)
root.text(20, 25, 'One hub and up to 5 identical targets. The boards are not wired together: the targets talk to the\n'
          'hub over ESP-NOW (WiFi channel 1 by default). Phones join the hub\'s WiFi and open the app.\n'
          'Double-click a sheet to open it.')
root.subsheets.append(('Target node', 'node.kicad_sch', 30, 45, 55, 28, uid('root', 'sheet', 'node')))
root.subsheets.append(('Hub', 'hub.kicad_sch', 120, 45, 55, 28, uid('root', 'sheet', 'hub')))
root.text(32, 50, 'D1 Mini + battery shield\nSW-420 hit sensor\nWS2812B LED\n\nx 1..5')
root.text(122, 50, 'ESP32 DevKit\nWiFi AP + web app\nESP-NOW to the targets\n\nx 1')
root.text(87, 60, '<- ESP-NOW ->', 1.8)

# ---------------------------------------------------------------- checks

EXPECTED_NETS = {
    'Node': {
        '+5V': {('U2', '5V'), ('U1', '5V'), ('D1', 'VDD'), ('C1', '+')},
        '+3V3': {('U1', '3V3'), ('M1', 'VCC')},
        'GND': {('U2', 'GND'), ('U1', 'GND'), ('M1', 'GND'), ('D1', 'VSS'), ('C1', '-')},
        'VBAT_SW': {('BT1', '+'), ('SW1', '1')},
        'VBAT': {('SW1', '2'), ('U2', 'B+'), ('JP2', '1')},
        'BAT-': {('BT1', '-'), ('U2', 'B-')},
        'A0_DIV': {('JP2', '2'), ('R2', '1')},
        'A0': {('R2', '2'), ('U1', 'A0')},
        'SENSOR': {('U1', 'D1/GPIO5'), ('M1', 'DO')},
        'LED_D3': {('U1', 'D3/GPIO0'), ('JP1', 'A')},
        'LED_D2': {('U1', 'D2/GPIO4'), ('JP1', 'B')},
        'LED_SEL': {('JP1', 'C'), ('R1', '1')},
        'LED_DIN': {('R1', '2'), ('D1', 'DIN')},
    },
    'Hub': {},
    'Root': {},
}


def on_segment(p, a, b):
    (x, y), (x1, y1), (x2, y2) = p, a, b
    if x1 == x2 == x:
        return min(y1, y2) <= y <= max(y1, y2)
    if y1 == y2 == y:
        return min(x1, x2) <= x <= max(x1, x2)
    return False


def check(sheet):
    errors = []
    got = {net: set(m) for net, m in sheet.nets.items()}
    if got != EXPECTED_NETS[sheet.name]:
        for net in sorted(set(got) | set(EXPECTED_NETS[sheet.name])):
            a, b = got.get(net, set()), EXPECTED_NETS[sheet.name].get(net, set())
            if a != b:
                errors.append(f'net {net}: extra {sorted(a - b)}, missing {sorted(b - a)}')
    used = {}
    for net, members in sheet.nets.items():
        for m in members:
            used.setdefault(m, []).append(net)
    for ref, pin, _ in sheet.ncs:
        used.setdefault((ref, pin), []).append('NC')
    for p in sheet.parts:
        if p.sym.power:
            continue
        for key in p.sym.pins:
            got_pin = used.get((p.ref, key), [])
            if len(got_pin) != 1:
                errors.append(f'{p.ref}.{key}: on {got_pin or "nothing"} (needs exactly one net or NC)')
    pts = sheet.points + [(x, y, 'NC:' + r + '.' + pn) for r, pn, (x, y) in sheet.ncs]
    pin_ends = {}
    for p in sheet.parts:
        if not p.sym.power:
            for key in p.sym.pins:
                pin_ends[p.pin_xy(key)] = (p.ref, key)
    for a, b, net in sheet.wires:
        for x, y, other in pts:
            if other != net and on_segment((x, y), a, b):
                errors.append(f'wire {a}-{b} ({net}) touches {other} at {(x, y)}')
        for xy, who in pin_ends.items():
            if on_segment(xy, a, b) and who not in sheet.nets.get(net, []):
                errors.append(f'wire {a}-{b} ({net}) touches pin {who}')
    refs = [p.ref for s in SHEETS for p in s.parts]
    dup = {r for r in refs if refs.count(r) > 1}
    if dup:
        errors.append(f'duplicate references {sorted(dup)}')
    return errors


# ---------------------------------------------------------------- KiCad output

def title_block(sheet):
    return (f'  (title_block\n    (title {q(sheet.title)})\n    (date {q(DATE)})\n    (rev {q(REV)})\n'
            f'    (company "esp32_targets")\n    (comment 1 "Generated by hardware/tools/gen_schematic.py")\n  )')


def prop(name, value, pid, x, y, hide=False, align='left'):
    j = {'left': ' (justify left)', 'right': ' (justify right)', 'center': ''}[align]
    eff = '(effects (font (size 1.27 1.27))' + j + (' hide' if hide else '') + ')'
    return f'    (property {q(name)} {q(value)} (id {pid}) (at {n(x)} {n(y)} 0) {eff})'


def sch(sheet, root_instances=None):
    out = ['(kicad_sch (version 20211123) (generator eeschema)', '',
           f'  (uuid {uid(sheet.name, "sheet")})', '', '  (paper "A4")', '', title_block(sheet), '',
           '  (lib_symbols']
    seen = []
    for p in sheet.parts:
        if p.sym not in seen:
            seen.append(p.sym)
    for s in seen:
        out.append('\n'.join('    ' + line for line in s.sexpr().split('\n')))
    out.append('  )\n')
    for ref, pin, (x, y) in sheet.ncs:
        out.append(f'  (no_connect (at {n(x)} {n(y)}) (uuid {uid(sheet.name, "nc", ref, pin)}))')
    for i, (a, b, net) in enumerate(sheet.wires):
        out.append(f'  (wire (pts (xy {n(a[0])} {n(a[1])}) (xy {n(b[0])} {n(b[1])})) {STROKE_THIN}'
                   f' (uuid {uid(sheet.name, "wire", str(i))}))')
    for i, (net, (x, y), ang) in enumerate(sheet.labels):
        j = 'right bottom' if ang == 180 else 'left bottom'
        out.append(f'  (label {q(net)} (at {n(x)} {n(y)} {ang}) (effects (font (size 1.27 1.27)) (justify {j}))'
                   f' (uuid {uid(sheet.name, "label", str(i))}))')
    for i, (x, y, s, size) in enumerate(sheet.texts):
        sz = f'{size:g} {size:g}'
        bold = ' bold' if size > 1.5 else ''
        out.append(f'  (text {q(s)} (at {n(x)} {n(y)} 0) (effects (font (size {sz}){bold}) (justify left top))'
                   f' (uuid {uid(sheet.name, "text", str(i))}))')
    for name, file, x, y, w, h, su in sheet.subsheets:
        out.append(f'  (sheet (at {n(x)} {n(y)}) (size {n(w)} {n(h)})\n'
                   f'    (stroke (width 0.1524) (type solid) (color 0 0 0 0))\n'
                   f'    (fill (color 0 0 0 0.0000))\n    (uuid {su})\n'
                   f'    (property "Sheet name" {q(name)} (id 0) (at {n(x)} {n(y - 0.6)} 0)'
                   f' (effects (font (size 1.27 1.27)) (justify left bottom)))\n'
                   f'    (property "Sheet file" {q(file)} (id 1) (at {n(x)} {n(y + h + 0.5)} 0)'
                   f' (effects (font (size 1.27 1.27)) (justify left top)))\n  )')
    for p in sheet.parts:
        bom = 'yes' if p.in_bom else 'no'
        out.append(f'  (symbol (lib_id {q(p.sym.lib_id)}) (at {n(p.x)} {n(p.y)} 0) (unit 1)\n'
                   f'    (in_bom {bom}) (on_board yes)\n    (uuid {p.uuid})')
        rx, ry = p.ref_at
        vx, vy = p.val_at
        out.append(prop('Reference', p.ref, 0, p.x + rx, p.y + ry, hide=p.sym.power, align=p.align))
        out.append(prop('Value', p.value, 1, p.x + vx, p.y + vy, align=p.align))
        out.append(prop('Footprint', '', 2, p.x, p.y, hide=True))
        out.append(prop('Datasheet', '', 3, p.x, p.y, hide=True))
        for pin in p.sym.pin_list:
            out.append(f'    (pin {q(pin.num)} (uuid {uid(sheet.name, p.ref, "pin", pin.num)}))')
        out.append('  )')
    if root_instances is not None:
        pages, syms = root_instances
        out.append('\n  (sheet_instances')
        for path, page in pages:
            out.append(f'    (path {q(path)} (page {q(page)}))')
        out.append('  )\n\n  (symbol_instances')
        for path, p in syms:
            out.append(f'    (path {q(path)}\n      (reference {q(p.ref)}) (unit 1) (value {q(p.value)}) (footprint "")\n    )')
        out.append('  )')
    out.append(')\n')
    return '\n'.join(out)


def project():
    return json.dumps({
        'meta': {'filename': 'esp32_targets.kicad_pro', 'version': 1},
        'sheets': [[uid('Root', 'sheet'), ''],
                   [uid('root', 'sheet', 'node'), 'Target node'],
                   [uid('root', 'sheet', 'hub'), 'Hub']],
        'text_variables': {},
    }, indent=2) + '\n'


# ---------------------------------------------------------------- SVG preview
# Text is drawn at KiCad's size (monospace, about the width of KiCad's font), so
# the preview shows the same overlaps KiCad would.

S = 6.0  # px per mm
PAGE_W, PAGE_H = 297, 210
PITCH = 1.62  # KiCad line pitch, x font size


def fs(size_mm):
    return size_mm * 1.45 * S


def svg_sheet(sheet, oy):
    o = [f'<g transform="translate(0,{oy})">',
         f'<rect x="{10 * S}" y="{10 * S}" width="{(PAGE_W - 20) * S}" height="{(PAGE_H - 20) * S}" fill="#fffef8" stroke="#842" stroke-width="1.5"/>',
         f'<text x="{(PAGE_W - 12) * S}" y="{(PAGE_H - 12) * S}" text-anchor="end" fill="#842" font-size="{fs(1.6):.1f}">'
         f'{escape(sheet.title)} - sheet {sheet.page}/3 - rev {REV} - {DATE}</text>']

    def P(x, y):
        return x * G * S, y * G * S

    def txt(x, y, s, anchor='start', color='#800', size=1.27, bold=False, valign='bottom'):
        X, Y = P(x, y)
        if valign == 'top':
            Y += fs(size) * 0.75
        elif valign == 'middle':
            Y += fs(size) * 0.35
        b = ' font-weight="bold"' if bold else ''
        return (f'<text x="{X:.1f}" y="{Y:.1f}" text-anchor="{anchor}" fill="{color}" '
                f'font-size="{fs(size):.1f}"{b}>{escape(s)}</text>')

    for name, file, x, y, w, h, _ in sheet.subsheets:
        X, Y = P(x, y)
        o.append(f'<rect x="{X:.1f}" y="{Y:.1f}" width="{w * G * S:.1f}" height="{h * G * S:.1f}" fill="#fff4e8" stroke="#842" stroke-width="2"/>')
        o.append(txt(x, y - 0.6, name, color='#842', bold=True))
        o.append(txt(x, y + h + 0.5, file, color='#842', valign='top'))
    for x, y, s, size in sheet.texts:
        for i, line in enumerate(s.split('\n')):
            o.append(txt(x, y + i * size * PITCH / G, line, color='#224', size=size, bold=size > 1.5, valign='top'))
    for a, b, _ in sheet.wires:
        (x1, y1), (x2, y2) = P(*a), P(*b)
        o.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#080" stroke-width="2"/>')
    for x, y in junction_points(sheet):
        X, Y = P(x, y)
        o.append(f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="3" fill="#080"/>')
    for net, (x, y), ang in sheet.labels:
        o.append(txt(x + (-0.2 if ang == 180 else 0.2), y - 0.2, net, 'end' if ang == 180 else 'start', '#000'))
    for _, _, (x, y) in sheet.ncs:
        X, Y = P(x, y)
        d = 0.5 * G * S
        o.append(f'<path d="M{X - d:.1f},{Y - d:.1f}L{X + d:.1f},{Y + d:.1f}M{X - d:.1f},{Y + d:.1f}L{X + d:.1f},{Y - d:.1f}" stroke="#00a" stroke-width="1.6"/>')
    for p in sheet.parts:
        o.append(svg_part(p, P, txt))
    o.append('</g>')
    return '\n'.join(o)


def junction_points(sheet):
    return []  # wires only meet at pin ends and corners, so there are no T-junctions


def svg_part(p, P, txt):
    o = []

    def L(x, y):  # library coords -> px
        return P(p.x + x, p.y - y)

    for g in p.sym.graphics:
        if g[0] == 'rect':
            (x1, y1), (x2, y2) = L(g[1], g[2]), L(g[3], g[4])
            o.append(f'<rect x="{min(x1, x2):.1f}" y="{min(y1, y2):.1f}" width="{abs(x2 - x1):.1f}" '
                     f'height="{abs(y2 - y1):.1f}" fill="#fff8c8" stroke="#800" stroke-width="2"/>')
        elif g[0] == 'line':
            pts = ' '.join('%.1f,%.1f' % L(x, y) for x, y in g[1])
            o.append(f'<polyline points="{pts}" fill="none" stroke="#800" stroke-width="2"/>')
        elif g[0] == 'circle':
            X, Y = L(g[1], g[2])
            o.append(f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="{g[3] * G * S:.1f}" fill="none" stroke="#800" stroke-width="2"/>')
        elif g[0] == 'text':
            o.append(txt(p.x + g[1], p.y - g[2], g[3], 'middle', valign='middle'))
    if not p.sym.power:
        for pin in p.sym.pin_list:
            dx, dy = pin.outward()
            x0, y0 = p.x + pin.x, p.y - pin.y
            x1, y1 = x0 - dx * pin.length, y0 - dy * pin.length
            (X0, Y0), (X1, Y1) = P(x0, y0), P(x1, y1)
            o.append(f'<line x1="{X0:.1f}" y1="{Y0:.1f}" x2="{X1:.1f}" y2="{Y1:.1f}" stroke="#800" stroke-width="1.6"/>')
            if not p.sym.hide_names:
                if dx:
                    o.append(txt(x1 - dx * 0.8, y1, pin.name, 'start' if dx < 0 else 'end', '#046', valign='middle'))
                else:
                    o.append(txt(x1, y1 - dy * 1.4, pin.name, 'middle', '#046', valign='middle'))
    anchor = {'left': 'start', 'right': 'end', 'center': 'middle'}[p.align]
    if not p.sym.power:
        o.append(txt(p.x + p.ref_at[0], p.y + p.ref_at[1], p.ref, anchor, '#066', bold=True, valign='middle'))
    o.append(txt(p.x + p.val_at[0], p.y + p.val_at[1], p.value, anchor, '#066', valign='middle'))
    return '\n'.join(o)


def svg(sheets):
    h = PAGE_H * S * len(sheets) + 20 * (len(sheets) - 1)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{PAGE_W * S:.0f}" height="{h:.0f}" '
         f'viewBox="0 0 {PAGE_W * S:.0f} {h:.0f}" font-family="DejaVu Sans Mono, Menlo, Consolas, monospace">',
         '<rect width="100%" height="100%" fill="#ddd"/>']
    for i, s in enumerate(sheets):
        o.append(svg_sheet(s, i * (PAGE_H * S + 20)))
    o.append('</svg>\n')
    return '\n'.join(o)


# ---------------------------------------------------------------- main

def main():
    SHEETS.append(root)
    errors = [f'{s.name}: {e}' for s in SHEETS for e in check(s)]
    if errors:
        raise SystemExit('Schematic check failed:\n  ' + '\n  '.join(errors))

    pages = [('/', '1')]
    syms = []
    for s, key in ((node, 'node'), (hub, 'hub')):
        su = uid('root', 'sheet', key)
        pages.append((f'/{su}', s.page))
        syms += [(f'/{su}/{p.uuid}', p) for p in s.parts]
    syms.sort(key=lambda t: t[1].ref)

    kicad = os.path.join(OUT, 'kicad')
    os.makedirs(kicad, exist_ok=True)
    files = {
        os.path.join(kicad, 'esp32_targets.kicad_sch'): sch(root, (pages, syms)),
        os.path.join(kicad, 'node.kicad_sch'): sch(node),
        os.path.join(kicad, 'hub.kicad_sch'): sch(hub),
        os.path.join(kicad, 'esp32_targets.kicad_pro'): project(),
        os.path.join(OUT, 'schematic_preview.svg'): svg([root, node, hub]),
    }
    for path, text in files.items():
        with open(path, 'w') as f:
            f.write(text)
        print('wrote', os.path.relpath(path, os.getcwd()))
    for s in (node, hub):
        nets = len(s.nets)
        print(f'{s.name}: {len([p for p in s.parts if not p.sym.power])} parts, {nets} nets, '
              f'{len(s.ncs)} no-connects: checks passed')


if __name__ == '__main__':
    main()
