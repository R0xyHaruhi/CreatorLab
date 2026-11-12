import hashlib
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from creatorlab.bridge import handler_factory


def test_bridge_health_and_token_verification(tmp_path):
    token='local-test-token'
    server=ThreadingHTTPServer(('127.0.0.1',0),handler_factory(tmp_path/'test.db',token))
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base+'/health') as r:
            health=json.load(r)
        assert health['version']=='0.9.1'
        assert health['bridge_id']==hashlib.sha256(token.encode()).hexdigest()[:12]
        req=Request(base+'/verify',data=b'',method='POST',headers={'X-CreatorLab-Token':token})
        with urlopen(req) as r:
            assert json.load(r)['ok']
        req=Request(base+'/verify',data=b'',method='POST',headers={'X-CreatorLab-Token':'wrong'})
        try:
            urlopen(req)
            assert False, 'Expected authorization error'
        except HTTPError as e:
            assert e.code==401
    finally:
        server.shutdown()
        server.server_close()
