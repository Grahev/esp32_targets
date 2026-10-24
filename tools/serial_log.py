"""Read a board's serial output from the PC (mpremote repl needs a TTY).

Usage: python3 tools/serial_log.py PORT [SECONDS] [--reset]
  --reset  pulse RTS to hard-reset the board first, then capture its boot log.
  --send=CMD  type CMD + newline on the v2 node console (repeatable; one every
              2 s, starting 3 s in), e.g. --send=info --send=hit
Opening the port never sends Ctrl-C, so a running main.py keeps running.
"""
import sys
import time

import serial


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        print(__doc__)
        sys.exit(2)
    port = args[0]
    seconds = float(args[1]) if len(args) > 1 else 15
    s = serial.Serial()
    s.port = port
    s.baudrate = 115200
    s.timeout = 0.2
    s.dtr = False  # keep the chip out of reset / bootloader
    s.rts = False
    s.open()
    if '--reset' in sys.argv:
        s.reset_input_buffer()
        s.rts = True
        time.sleep(0.1)
        s.rts = False
    sends = [a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--send=')]
    start = time.time()
    end = start + seconds
    while time.time() < end:
        if sends and time.time() - start >= 3 + 2 * (len([a for a in sys.argv if a.startswith('--send=')]) - len(sends)):
            s.write((sends.pop(0) + '\n').encode())
        d = s.read(512)
        if d:
            sys.stdout.write(d.decode('utf-8', 'replace'))
            sys.stdout.flush()
    s.close()


if __name__ == '__main__':
    main()
