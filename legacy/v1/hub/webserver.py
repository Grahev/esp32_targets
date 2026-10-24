"""Minimal HTTP + WebSocket server for the hub (replaces Microdot).

Only what the dashboard needs: GET routes on exact paths, query args,
streaming a static file, and text WebSockets. Microdot used ~23 KB of RAM;
keeping the hub inside MicroPython's first 56 KB heap leaves ~56 KB more
for WiFi (see REVIEW #36). Runs on MicroPython and CPython (tests).
"""
import asyncio
import binascii
import hashlib
import os

MAX_HEADERS = 32
MAX_WS_PAYLOAD = 1024  # the browser only ever sends us small messages
_WS_GUID = b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
_REASONS = {200: 'OK', 400: 'Bad Request', 404: 'Not Found', 409: 'Conflict', 500: 'Internal Server Error'}
_TYPES = {'html': 'text/html; charset=utf-8', 'js': 'application/javascript', 'css': 'text/css',
          'json': 'application/json'}


def _unquote(s):
    s = s.replace('+', ' ')
    if '%' not in s:
        return s
    out = bytearray()
    parts = s.split('%')
    out.extend(parts[0].encode())
    for p in parts[1:]:
        try:
            out.append(int(p[:2], 16))
            out.extend(p[2:].encode())
        except ValueError:
            out.extend(('%' + p).encode())
    return out.decode()


def parse_qs(qs):
    args = {}
    for pair in qs.split('&'):
        if pair:
            k, _, v = pair.partition('=')
            args[_unquote(k)] = _unquote(v)
    return args


async def close_stream(writer):
    try:
        if hasattr(writer, 'aclose'):  # MicroPython
            await writer.aclose()
        else:  # CPython
            writer.close()
            await writer.wait_closed()
    except Exception:
        pass


class Request:
    def __init__(self, method, path, args, headers, reader, writer):
        self.method = method
        self.path = path
        self.args = args
        self.headers = headers
        self.reader = reader
        self.writer = writer


class FileResponse:
    def __init__(self, path):
        self.path = path


def send_file(path):
    return FileResponse(path)


class WebServer:
    def __init__(self):
        self.routes = {}

    def route(self, path):
        def register(f):
            self.routes[path] = f
            return f
        return register

    async def start_server(self, host='0.0.0.0', port=80, debug=False):
        print(f"Starting server on {host}:{port}...")
        server = await asyncio.start_server(self._handle, host, port)
        await server.wait_closed()

    async def _handle(self, reader, writer):
        try:
            req = await self._read_request(reader, writer)
            if req is None:
                return
            f = self.routes.get(req.path)
            if f is None:
                await self._respond(writer, 404, 'Not found')
                return
            try:
                res = await f(req)
            except Exception as ex:
                print(f"Handler error {req.path}: {ex}")
                await self._respond(writer, 500, 'Internal server error')
                return
            if res is None:
                return  # handler wrote its own reply (WebSocket)
            if isinstance(res, FileResponse):
                await self._send_file(writer, res.path)
            elif isinstance(res, tuple):
                await self._respond(writer, res[1], res[0])
            else:
                await self._respond(writer, 200, res)
        except Exception as ex:
            print(f"HTTP error: {ex}")
        finally:
            await close_stream(writer)

    async def _read_request(self, reader, writer):
        line = await reader.readline()
        try:
            method, target, _ = line.decode().split(' ', 2)
        except ValueError:
            return None
        headers = {}
        for _ in range(MAX_HEADERS):
            h = await reader.readline()
            if h in (b'\r\n', b'\n', b''):
                break
            k, _, v = h.decode().partition(':')
            headers[k.strip().lower()] = v.strip()
        path, _, qs = target.partition('?')
        return Request(method, path, parse_qs(qs), headers, reader, writer)

    async def _respond(self, writer, status, body, ctype='text/plain; charset=utf-8'):
        body = body.encode() if isinstance(body, str) else body
        writer.write(('HTTP/1.0 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n'
                      'Connection: close\r\n\r\n' % (status, _REASONS.get(status, 'OK'), ctype, len(body))).encode())
        writer.write(body)
        await writer.drain()

    async def _send_file(self, writer, path):
        try:
            size = os.stat(path)[6]
        except OSError:
            await self._respond(writer, 404, 'Not found')
            return
        ctype = _TYPES.get(path.rsplit('.', 1)[-1], 'application/octet-stream')
        writer.write(('HTTP/1.0 200 OK\r\nContent-Type: %s\r\nContent-Length: %d\r\n'
                      'Connection: close\r\n\r\n' % (ctype, size)).encode())
        buf = bytearray(512)  # stream in small pieces: never hold the whole page in RAM
        with open(path, 'rb') as f:
            while True:
                n = f.readinto(buf)
                if not n:
                    break
                writer.write(buf if n == len(buf) else buf[:n])
                await writer.drain()


class WebSocket:
    TEXT = 1
    CLOSE = 8
    PING = 9
    PONG = 10

    def __init__(self, request):
        self.request = request
        self.reader = request.reader
        self.writer = request.writer
        self.closed = False

    async def handshake(self):
        key = self.request.headers.get('sec-websocket-key')
        if not key or 'websocket' not in self.request.headers.get('upgrade', '').lower():
            raise ValueError('not a WebSocket request')
        accept = binascii.b2a_base64(hashlib.sha1(key.encode() + _WS_GUID).digest())[:-1]
        self.writer.write(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n'
                          b'Connection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
        await self.writer.drain()

    def _header(self, n, opcode):
        if n < 126:
            return bytes((0x80 | opcode, n))
        if n < 65536:
            return bytes((0x80 | opcode, 126)) + n.to_bytes(2, 'big')
        return bytes((0x80 | opcode, 127)) + n.to_bytes(8, 'big')

    async def send(self, data, opcode=TEXT):
        if self.closed:
            return
        if isinstance(data, str):
            data = data.encode()
        self.writer.write(self._header(len(data), opcode))
        self.writer.write(data)
        await self.writer.drain()

    async def send_file(self, prefix, path, suffix):
        """Send prefix + file contents + suffix as one text message, streaming
        the file in small pieces instead of building one big string."""
        if self.closed:
            return
        prefix, suffix = prefix.encode(), suffix.encode()
        size = os.stat(path)[6]
        self.writer.write(self._header(len(prefix) + size + len(suffix), self.TEXT))
        self.writer.write(prefix)
        buf = bytearray(256)
        with open(path, 'rb') as f:
            while True:
                n = f.readinto(buf)
                if not n:
                    break
                self.writer.write(buf if n == len(buf) else buf[:n])
                await self.writer.drain()
        self.writer.write(suffix)
        await self.writer.drain()

    async def receive(self):
        """Return the next text (str) or binary (bytes) message. Raises OSError when closed."""
        while True:
            hdr = await self.reader.readexactly(2)
            opcode = hdr[0] & 0x0F
            n = hdr[1] & 0x7F
            if n == 126:
                n = int.from_bytes(await self.reader.readexactly(2), 'big')
            elif n == 127:
                n = int.from_bytes(await self.reader.readexactly(8), 'big')
            if n > MAX_WS_PAYLOAD or not hdr[0] & 0x80:
                raise OSError(32, 'WebSocket frame too large or fragmented')
            mask = await self.reader.readexactly(4) if hdr[1] & 0x80 else None
            payload = bytearray(await self.reader.readexactly(n))
            if mask:
                for i in range(n):
                    payload[i] ^= mask[i & 3]
            if opcode == self.CLOSE:
                self.closed = True
                raise OSError(32, 'WebSocket closed')
            if opcode == self.PING:
                await self.send(payload, self.PONG)
            elif opcode == self.TEXT:
                return payload.decode()
            elif opcode == 2:
                return bytes(payload)
