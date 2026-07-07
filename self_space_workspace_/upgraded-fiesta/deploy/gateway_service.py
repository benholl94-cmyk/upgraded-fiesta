from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os

class Handler(BaseHTTPRequestHandler):
    def _json(self, status, payload):
        body = json.dumps(payload, sort_keys=True).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ('/', '/health', '/ready'):
            self._json(200, {'ok': True, 'service': 'upgraded-fiesta-gateway', 'status': 'ready'})
            return
        if self.path == '/version':
            self._json(200, {'service': 'upgraded-fiesta-gateway', 'version': '0.1.0'})
            return
        self._json(404, {'ok': False, 'error': 'not_found'})

    def do_POST(self):
        if self.path == '/chat':
            self._json(200, {'ok': True, 'service': 'upgraded-fiesta-gateway', 'message': 'gateway online'})
            return
        self._json(404, {'ok': False, 'error': 'not_found'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8080'))
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    print(f'upgraded-fiesta-gateway listening on 0.0.0.0:{port}', flush=True)
    server.serve_forever()
