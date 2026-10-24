import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'hub'))
from webserver import WebServer, WebSocket, send_file, parse_qs  # noqa: E402


def make_app(page_path):
    app = WebServer()
    got = {}

    @app.route('/')
    async def index(req):
        return send_file(page_path)

    @app.route('/echo')
    async def echo(req):
        return ','.join('%s=%s' % kv for kv in sorted(req.args.items()))

    @app.route('/bad')
    async def bad(req):
        return 'nope', 400

    @app.route('/boom')
    async def boom(req):
        raise ValueError('handler bug')

    @app.route('/ws')
    async def ws_route(req):
        ws = WebSocket(req)
        await ws.handshake()
        await ws.send('hello')
        await ws.send('x' * 300)  # 16-bit length header
        await ws.send_file('{"data": ', page_path, '}')  # streamed from the file
        try:
            while True:
                got.setdefault('msgs', []).append(await ws.receive())
        except OSError:
            got['closed'] = True

    return app, got


async def http(port, request):
    r, w = await asyncio.open_connection('127.0.0.1', port)
    w.write(request)
    await w.drain()
    data = await r.read()
    w.close()
    return data


async def start(app):
    server = await asyncio.start_server(app._handle, '127.0.0.1', 0)
    return server, server.sockets[0].getsockname()[1]


def masked_frame(opcode, payload, mask=b'\x01\x02\x03\x04'):
    body = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return bytes((0x80 | opcode, 0x80 | len(payload))) + mask + body


class TestHttp(unittest.TestCase):
    def setUp(self):
        fd, self.page = tempfile.mkstemp(suffix='.html')
        self.content = b'<html>' + b'A' * 2000 + b'</html>'  # > 512: several chunks
        os.write(fd, self.content)
        os.close(fd)

    def test_routes_args_status_and_file(self):
        async def go():
            app, _ = make_app(self.page)
            server, port = await start(app)
            page = await http(port, b'GET / HTTP/1.1\r\nHost: x\r\n\r\n')
            echo = await http(port, b'GET /echo?mode=Time+Attack&d=a%2Fb&x= HTTP/1.1\r\n\r\n')
            bad = await http(port, b'GET /bad HTTP/1.1\r\n\r\n')
            missing = await http(port, b'GET /nothing HTTP/1.1\r\n\r\n')
            boom = await http(port, b'GET /boom HTTP/1.1\r\n\r\n')
            garbage = await http(port, b'\r\n')
            server.close()
            return page, echo, bad, missing, boom, garbage
        page, echo, bad, missing, boom, garbage = asyncio.run(go())
        head, body = page.split(b'\r\n\r\n', 1)
        self.assertIn(b'200 OK', head)
        self.assertIn(b'text/html', head)
        self.assertIn(b'Content-Length: %d' % len(self.content), head)
        self.assertEqual(body, self.content)
        self.assertTrue(echo.endswith(b'd=a/b,mode=Time Attack,x='))
        self.assertTrue(bad.startswith(b'HTTP/1.0 400') and bad.endswith(b'nope'))
        self.assertTrue(missing.startswith(b'HTTP/1.0 404'))
        self.assertTrue(boom.startswith(b'HTTP/1.0 500'))
        self.assertEqual(garbage, b'')

    def test_parse_qs(self):
        self.assertEqual(parse_qs('a=1&b=%41%42&c=&&d'), {'a': '1', 'b': 'AB', 'c': '', 'd': ''})
        self.assertEqual(parse_qs('bad=%zz'), {'bad': '%zz'})


class TestWebSocket(unittest.TestCase):
    def test_handshake_frames_ping_close(self):
        fd, path = tempfile.mkstemp(suffix='.json')
        os.write(fd, json.dumps([{'score': 5}] * 40).encode())  # > 256 B: several chunks
        os.close(fd)

        async def go():
            app, got = make_app(path)
            server, port = await start(app)
            r, w = await asyncio.open_connection('127.0.0.1', port)
            w.write(b'GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                    b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n')
            await w.drain()
            head = await r.readuntil(b'\r\n\r\n')
            first = await r.readexactly(2 + 5)
            second_hdr = await r.readexactly(4)
            second = await r.readexactly(300)
            third_hdr = await r.readexactly(4)
            third = await r.readexactly(int.from_bytes(third_hdr[2:], 'big'))
            w.write(masked_frame(1, b'from browser'))
            w.write(masked_frame(9, b'pi'))  # ping
            await w.drain()
            pong = await r.readexactly(4)
            w.write(masked_frame(8, b''))  # close
            await w.drain()
            await asyncio.sleep(0.1)
            w.close()
            server.close()
            return head, first, second_hdr, second, third, pong, got
        head, first, second_hdr, second, third, pong, got = asyncio.run(go())
        self.assertIn(b'101 Switching Protocols', head)
        self.assertIn(b'Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=', head)  # RFC 6455 example
        self.assertEqual(first, b'\x81\x05hello')
        self.assertEqual(second_hdr, b'\x81\x7e\x01\x2c')
        self.assertEqual(second, b'x' * 300)
        self.assertEqual(json.loads(third), {'data': [{'score': 5}] * 40})
        self.assertEqual(pong, b'\x8a\x02pi')
        self.assertEqual(got['msgs'], ['from browser'])
        self.assertTrue(got['closed'])

    def test_plain_get_on_ws_route_is_refused(self):
        async def go():
            app, _ = make_app('/nonexistent')
            server, port = await start(app)
            reply = await http(port, b'GET /ws HTTP/1.1\r\n\r\n')
            server.close()
            return reply
        self.assertTrue(asyncio.run(go()).startswith(b'HTTP/1.0 500'))


if __name__ == '__main__':
    unittest.main()
