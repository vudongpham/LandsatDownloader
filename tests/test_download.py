import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lsdownloader import download as dl
from lsdownloader._http import make_session

PID_OK = 'LC08_L1TP_192023_20200101_20200113_02_T1'
PID_RESUME = 'LC08_L1TP_192024_20200101_20200113_02_T1'
PID_404 = 'LC08_L1TP_192025_20200101_20200113_02_T1'
PID_FLAKY = 'LC08_L1TP_192026_20200101_20200113_02_T1'
CONTENT = bytes(range(256)) * 4000


class Handler(BaseHTTPRequestHandler):
    flaky_hits = 0

    def log_message(self, *args):
        pass

    def do_GET(self):
        if PID_404 in self.path:
            self.send_response(404)
            self.end_headers()
            return
        if PID_FLAKY in self.path and Handler.flaky_hits == 0:
            Handler.flaky_hits += 1
            # announce the full length but send only half of it
            self.send_response(200)
            self.send_header('Content-Length', str(len(CONTENT)))
            self.end_headers()
            self.wfile.write(CONTENT[:len(CONTENT) // 2])
            self.close_connection = True
            return
        start = 0
        rng = self.headers.get('Range')
        if rng:
            start = int(rng.split('=')[1].split('-')[0])
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start}-{len(CONTENT) - 1}/{len(CONTENT)}')
        else:
            self.send_response(200)
        pid = self.path.split('landsat_product_id=')[1].split('&')[0]
        self.send_header('Content-Disposition', f'attachment; filename="{pid}.tar"')
        self.send_header('Content-Type', 'application/x-tar')
        self.send_header('Content-Length', str(len(CONTENT) - start))
        self.end_headers()
        self.wfile.write(CONTENT[start:])


@pytest.fixture(scope='module')
def server():
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f'http://127.0.0.1:{httpd.server_address[1]}/gen-bundle?landsat_product_id='
    httpd.shutdown()


def test_download_resume_queue_and_failures(server, tmp_path, monkeypatch):
    monkeypatch.setattr(dl, 'download_with_retries',
                        lambda *a, **k: _orig(*a, backoff=0, **k))
    (tmp_path / f'{PID_RESUME}.tar.part').write_bytes(CONTENT[:1000])
    queue = tmp_path / 'queue.txt'
    urls = [server + p for p in (PID_OK, PID_RESUME, PID_404, PID_FLAKY)]

    done, failed = dl.download(urls, str(tmp_path), n_tasks=3, force_queue_fp=str(queue), retries=2,
                               session=make_session(retries=0))

    assert failed == [server + PID_404]
    for pid in (PID_OK, PID_RESUME, PID_FLAKY):
        assert (tmp_path / f'{pid}.tar').read_bytes() == CONTENT
        assert not (tmp_path / f'{pid}.tar.part').exists()
    lines = sorted(queue.read_text().splitlines())
    assert len(lines) == 3 and all(line.endswith(' QUEUED') for line in lines)

    # second run: everything already there is skipped
    assert dl.check_for_downloaded_scenes(urls, str(tmp_path)) == [server + PID_404]


_orig = dl.download_with_retries


def test_load_links(tmp_path):
    f = tmp_path / 'urls.txt'
    f.write_text('# comment\nhttps://a\n\nhttps://a\nhttps://b\n')
    assert dl.load_links(str(f)) == ['https://a', 'https://b']
    with pytest.raises(SystemExit):
        dl.check_for_broken_links(['not a link'])
