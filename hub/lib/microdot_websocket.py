import binascii
import hashlib
from microdot_asyncio import Response

class WebSocket:
    CONT = 0
    TEXT = 1
    BINARY = 2
    CLOSE = 8
    PING = 9
    PONG = 10

    def __init__(self, request):
        self.request = request
        self.reader, self.writer = request.sock
        self.closed = False

    async def handshake(self):
        response = self._handshake_response()
        await self.writer.awrite(b'HTTP/1.1 101 Switching Protocols\r\n')
        await self.writer.awrite(b'Upgrade: websocket\r\n')
        await self.writer.awrite(b'Connection: Upgrade\r\n')
        await self.writer.awrite(
            b'Sec-WebSocket-Accept: ' + response + b'\r\n\r\n')

    async def receive(self):
        while True:
            opcode, payload = await self._read_frame()
            send_opcode, data = self._process_websocket_frame(opcode, payload)
            if send_opcode:
                await self.send(send_opcode, data)
            elif data:
                return data

    async def send(self, data, opcode=None):
        if self.closed: return
        frame = self._encode_websocket_frame(
            opcode or (self.TEXT if isinstance(data, str) else self.BINARY),
            data)
        await self.writer.awrite(frame)

    async def close(self):
        if not self.closed:
            self.closed = True
            await self.send(b'', self.CLOSE)
            await self.writer.aclose()

    def _handshake_response(self):
        connection = False
        upgrade = False
        websocket_key = None
        for header, value in self.request.headers.items():
            h = header.lower()
            if h == 'connection':
                connection = True
                if 'upgrade' not in value.lower():
                    return self.request.app.abort(400)
            elif h == 'upgrade':
                upgrade = True
                if not value.lower() == 'websocket':
                    return self.request.app.abort(400)
            elif h == 'sec-websocket-key':
                websocket_key = value
        if not connection or not upgrade or not websocket_key:
            return self.request.app.abort(400)
        d = hashlib.sha1(websocket_key.encode())
        d.update(b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11')
        return binascii.b2a_base64(d.digest())[:-1]

    @classmethod
    def _parse_frame_header(cls, header):
        fin = header[0] & 0x80
        opcode = header[0] & 0x0f
        if fin == 0 or opcode == cls.CONT:
            raise OSError(32, 'Continuation frames not supported')
        has_mask = header[1] & 0x80
        length = header[1] & 0x7f
        if length == 126:
            length = -2
        elif length == 127:
            length = -8
        return fin, opcode, has_mask, length

    def _process_websocket_frame(self, opcode, payload):
        if opcode == self.TEXT:
            payload = payload.decode()
        elif opcode == self.BINARY:
            pass
        elif opcode == self.CLOSE:
            raise OSError(32, 'Websocket connection closed')
        elif opcode == self.PING:
            return self.PONG, payload
        elif opcode == self.PONG:
            return None, None
        return None, payload

    @classmethod
    def _encode_websocket_frame(cls, opcode, payload):
        frame = bytearray()
        frame.append(0x80 | opcode)
        if opcode == cls.TEXT:
            payload = payload.encode()
        if len(payload) < 126:
            frame.append(len(payload))
        elif len(payload) < (1 << 16):
            frame.append(126)
            frame.extend(len(payload).to_bytes(2, 'big'))
        else:
            frame.append(127)
            frame.extend(len(payload).to_bytes(8, 'big'))
        frame.extend(payload)
        return frame

    async def _read_frame(self):
        header = await self.reader.readexactly(2)
        fin, opcode, has_mask, length = self._parse_frame_header(header)
        if length < 0:
            length = await self.reader.readexactly(-length)
            length = int.from_bytes(length, 'big')
        if has_mask:
            mask = await self.reader.readexactly(4)
        payload = await self.reader.readexactly(length)
        if has_mask:
            payload = bytes(x ^ mask[i % 4] for i, x in enumerate(payload))
        return opcode, payload

def with_websocket(f):
    def wrapper(request, *args, **kwargs):
        ws = WebSocket(request)
        # We can't await handshake here easily if wrapper isn't async, 
        # but in microdot_asyncio the handler IS async.
        # So we pass the ws object to the handler, and let the handler invoke handshake?
        # Or we act as an async middleware.
        async def async_inner():
            await ws.handshake()
            try:
                await f(request, ws, *args, **kwargs)
                await ws.close()
            except OSError as exc:
                if exc.errno not in [32, 54, 104]:
                    raise
        return async_inner()
    return wrapper
