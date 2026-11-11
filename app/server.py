#!/usr/bin/env python3
"""Local, standard-library web server and SQLite document index for Offline Field Library."""
from __future__ import annotations
import html
import json
import logging
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / 'content'
INDEX = ROOT / 'index' / 'library.sqlite3'
VENDOR = ROOT / 'app' / 'vendor'
if VENDOR.is_dir():
    sys.path.insert(0, str(VENDOR))
try:
    from pypdf import PdfReader
    logging.getLogger('pypdf').setLevel(logging.ERROR)
except ImportError:
    PdfReader = None
HOST, PORT = '127.0.0.1', 8765
K = [
 ('encyclopedia','Encyclopedia & general knowledge','Open knowledge for quick reference','◎'),
 ('medical','Medical & first aid','First aid references and health resources','✚'),
 ('wilderness','Wilderness survival','Shelter, fire, signaling, and field skills','⌁'),
 ('water','Water procurement & purification','Finding, treating, and storing water','◉'),
 ('food','Food storage & preservation','Safe storage, canning, drying, and rotation','◇'),
 ('agriculture','Agriculture & gardening','Growing food, soil care, and seed keeping','❋'),
 ('automotive','Automotive maintenance','Vehicle systems, service, and repair manuals','⚙'),
 ('electrical','Electrical systems','Residential wiring and electrical references','ϟ'),
 ('plumbing','Plumbing & home repair','Repairs, tools, and household systems','⌂'),
 ('generators','Generators & alternative energy','Backup power, batteries, solar, and generators','☼'),
 ('radio','Amateur radio & emergency communications','Radio basics, procedures, and equipment guides','⌁'),
 ('maps','Navigation & topographic maps','Local maps, atlases, and navigation references','⌖'),
 ('military','Military Field Manuals','Military publications for communications, medical, maintenance, and field skills','▤'),
 ('preparedness','Emergency preparedness & evacuation','Plans, checklists, alerts, and evacuation information','▣'),
 ('other','Other references','Additional locally stored materials','＋'),
]
ALLOWED = {'.pdf','.html','.htm','.txt','.md','.zim','.epub','.jpg','.jpeg','.png','.webp','.mbtiles','.pmtiles','.tif','.tiff','.geojson','.gpx','.kml'}

def db_connect(create_schema=True):
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(INDEX, timeout=30)
    if create_schema:
        con.execute('CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(path UNINDEXED, title, category, body)')
        con.execute('CREATE TABLE IF NOT EXISTS file_state (path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, indexed_at REAL NOT NULL)')
    return con

INDEX_EXTS = {'.pdf', '.html', '.htm', '.txt', '.md', '.zim'}
MILITARY_COLLECTIONS = {'Current Doctrine', 'Recent Archive', 'Lessons Learned', 'Historic'}
MILITARY_BRANCHES = {'Army', 'Navy', 'Air Force', 'Marine Corps', 'Joint'}
INDEX_STATUS_LOCK = threading.Lock()
INDEX_STATUS = {'state': 'starting', 'indexed': 0, 'total': 0, 'pending': 0, 'error': None}

def set_index_status(**values):
    with INDEX_STATUS_LOCK:
        INDEX_STATUS.update(values)

def get_index_status():
    with INDEX_STATUS_LOCK:
        return dict(INDEX_STATUS)

def extract_pdf_text(p: Path) -> str:
    """Extract embedded text from a PDF, with an optional Poppler fallback."""
    # Map PDFs are large vector sheets; filenames and source notes make them
    # searchable without spending startup time parsing complex map graphics.
    if category_of(p) == 'maps':
        return ''

    if PdfReader is not None and p.stat().st_size <= 100 * 1024 * 1024:
        try:
            reader = PdfReader(str(p), strict=False)
            pieces = []
            remaining = 1_000_000
            for page_number, page in enumerate(reader.pages):
                if page_number >= 800:
                    break
                if remaining <= 0:
                    break
                try:
                    page_text = page.extract_text() or ''
                except Exception:
                    continue
                if page_text:
                    piece = page_text[:remaining]
                    pieces.append(piece)
                    remaining -= len(piece)
            text = '\n'.join(pieces)
            if text.strip():
                return text
        except Exception:
            pass

    pdftotext = shutil.which('pdftotext')
    if pdftotext:
        try:
            r = subprocess.run([pdftotext, '-layout', str(p), '-'], capture_output=True,
                               text=True, timeout=40)
            if r.returncode == 0:
                return r.stdout[:1_000_000]
        except (OSError, subprocess.SubprocessError):
            pass
    return ''

def extract_text(p: Path) -> str:
    ext = p.suffix.lower()
    try:
        if ext == '.pdf':
            return extract_pdf_text(p)
        if ext in {'.html','.htm'}:
            raw = p.read_text(errors='ignore')[:2_000_000]
            raw = re.sub(r'(?is)<(script|style).*?>.*?</\1>', ' ', raw)
            return html.unescape(re.sub(r'(?s)<[^>]+>', ' ', raw))
        if ext in {'.txt','.md'}:
            return p.read_text(errors='ignore')[:1_000_000]
    except (OSError, subprocess.SubprocessError):
        pass
    return ''

def category_of(p: Path) -> str:
    try: return p.relative_to(CONTENT).parts[0]
    except (ValueError, IndexError): return 'other'

def build_index():
    """Incrementally reconcile the FTS index without blocking dashboard startup."""
    set_index_status(state='scanning', error=None)
    con = None
    try:
        con = db_connect()
        files = {}
        for p in CONTENT.rglob('*'):
            if not p.is_file() or p.name.startswith('.') or p.suffix.lower() not in INDEX_EXTS:
                continue
            rel = p.relative_to(CONTENT).as_posix()
            stat = p.stat()
            files[rel] = (p, stat.st_size, stat.st_mtime_ns)

        known = {path: (size, mtime_ns) for path, size, mtime_ns in
                 con.execute('SELECT path,size,mtime_ns FROM file_state')}
        # Upgrade an older index in place: retain rows already indexed and seed
        # their fingerprints so the first incremental launch needn't reparse them.
        legacy_paths = {row[0] for row in con.execute('SELECT path FROM docs')}
        for rel in legacy_paths - set(known):
            if rel in files:
                _, size, mtime_ns = files[rel]
                con.execute('INSERT OR IGNORE INTO file_state(path,size,mtime_ns,indexed_at) VALUES(?,?,?,?)',
                            (rel, size, mtime_ns, time.time()))
                known[rel] = (size, mtime_ns)
            else:
                con.execute('DELETE FROM docs WHERE path=?', (rel,))

        removed = set(known) - set(files)
        for rel in removed:
            con.execute('DELETE FROM docs WHERE path=?', (rel,))
            con.execute('DELETE FROM file_state WHERE path=?', (rel,))
        con.commit()

        pending = [(rel, *files[rel]) for rel, fingerprint in files.items()
                   if known.get(rel) != (fingerprint[1], fingerprint[2])]
        indexed_count = con.execute('SELECT count(*) FROM file_state').fetchone()[0]
        set_index_status(state='indexing' if pending else 'ready', indexed=indexed_count,
                         total=indexed_count + len(pending), pending=len(pending), error=None)

        batch = []
        for i, (rel, path, size, mtime_ns) in enumerate(pending, start=1):
            text = 'ZIM archive offline encyclopedia Kiwix' if path.suffix.lower() == '.zim' else extract_text(path)
            batch.append((rel, path, size, mtime_ns, text))
            if i % 10 == 0 or i == len(pending):
                for batch_rel, batch_path, batch_size, batch_mtime, batch_text in batch:
                    con.execute('DELETE FROM docs WHERE path=?', (batch_rel,))
                    con.execute('INSERT INTO docs(path,title,category,body) VALUES(?,?,?,?)',
                                (batch_rel, batch_path.stem, category_of(batch_path), batch_text))
                    con.execute('INSERT OR REPLACE INTO file_state(path,size,mtime_ns,indexed_at) VALUES(?,?,?,?)',
                                (batch_rel, batch_size, batch_mtime, time.time()))
                con.commit()
                set_index_status(state='indexing' if i < len(pending) else 'ready',
                                 indexed=indexed_count + i, total=indexed_count + len(pending),
                                 pending=len(pending) - i, error=None)
                batch.clear()
        con.commit()
        final_count = con.execute('SELECT count(*) FROM file_state').fetchone()[0]
        set_index_status(state='ready', indexed=final_count, total=final_count, pending=0, error=None)
    except Exception as exc:
        logging.exception('Index reconciliation failed')
        set_index_status(state='error', error=str(exc))
    finally:
        if con is not None:
            con.close()

def byte_size(p: Path) -> int:
    try: return p.stat().st_size
    except OSError: return 0

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass
    def send_json(self, data, status=200):
        b=json.dumps(data).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(b))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u=urlparse(self.path)
        if u.path == '/api/status':
            d=shutil.disk_usage(ROOT)
            files=sum(1 for p in CONTENT.rglob('*') if p.is_file() and not p.name.startswith('.'))
            sizes={k[0]:sum(byte_size(p) for p in (CONTENT/k[0]).rglob('*') if p.is_file() and not p.name.startswith('.')) for k in K}
            self.send_json({'volume':str(ROOT.parent),'total':d.total,'used':d.used,'free':d.free,'files':files,'sizes':sizes,'index':get_index_status(),'kiwix': 'http://127.0.0.1:8081' if (shutil.which('kiwix-serve') or (ROOT / 'app' / 'bin' / 'kiwix-serve').is_file()) else None}); return
        if u.path == '/api/index-status':
            self.send_json(get_index_status()); return
        if u.path == '/api/categories':
            result=[]
            for slug,title,desc,icon in K:
                folder=CONTENT/slug; items=[]
                if folder.exists():
                    if slug == 'military':
                        item_count = sum(1 for p in folder.rglob('*.pdf') if p.is_file() and not p.name.startswith('.'))
                    else:
                        for p in sorted(folder.rglob('*')):
                            if p.is_file() and p.suffix.lower() in ALLOWED and not p.name.startswith('.'):
                                items.append({'name':p.name,'path':p.relative_to(CONTENT).as_posix(),'ext':p.suffix.lower(),'size':byte_size(p)})
                        item_count = len(items)
                else:
                    item_count = 0
                result.append({'slug':slug,'title':title,'description':desc,'icon':icon,'items':items,'item_count':item_count})
            self.send_json(result); return
        if u.path == '/api/search':
            params=parse_qs(u.query)
            q=params.get('q',[''])[0].strip()
            if len(q)<2: self.send_json({'results':[]}); return
            try:
                con=sqlite3.connect(INDEX, timeout=30); safe=' '.join('"'+w.replace('"','')+'"' for w in q.split() if w)
                clauses=['docs MATCH ?']; args=[safe]
                category=params.get('category',[''])[0]
                if category in {entry[0] for entry in K}:
                    clauses.append('category=?'); args.append(category)
                elif params.get('include_military',['0'])[0] != '1':
                    clauses.append("category!='military'")
                if category == 'military':
                    collection=params.get('collection',[''])[0]
                    branch=params.get('branch',[''])[0]
                    if collection in MILITARY_COLLECTIONS:
                        prefix='military/'+collection+'/'
                        if branch in MILITARY_BRANCHES:
                            prefix += branch+'/'
                        clauses.append('path LIKE ?'); args.append(prefix+'%')
                    elif branch in MILITARY_BRANCHES:
                        clauses.append('path LIKE ?'); args.append('%/'+branch+'/%')
                sql='SELECT path,title,category,snippet(docs,3,\'<mark>\',\'</mark>\',\'…\',12) FROM docs WHERE '+' AND '.join(clauses)+' ORDER BY rank LIMIT 30'
                rows=con.execute(sql,args).fetchall(); con.close()
                self.send_json({'results':[{'path':r[0],'title':r[1],'category':r[2],'snippet':r[3]} for r in rows]})
            except sqlite3.Error: self.send_json({'results':[],'error':'Search index is not ready. Start the library again to rebuild it.'},503)
            return
        if u.path.startswith('/content/'):
            rel=unquote(u.path[len('/content/'):])
            p=(CONTENT/rel).resolve()
            if not p.is_relative_to(CONTENT.resolve()) or not p.is_file(): self.send_error(404); return
            typ='application/vnd.pmtiles' if p.suffix.lower()=='.pmtiles' else (mimetypes.guess_type(p.name)[0] or 'application/octet-stream')
            try: size=p.stat().st_size; stream=p.open('rb')
            except OSError: self.send_error(404); return
            start,end,status=0,size-1,200
            requested=self.headers.get('Range')
            if requested:
                match=re.fullmatch(r'bytes=(\d*)-(\d*)',requested.strip())
                if not match or size==0:
                    stream.close(); self.send_response(416); self.send_header('Content-Range',f'bytes */{size}'); self.send_header('Content-Length','0'); self.end_headers(); return
                first,last=match.groups()
                if first:
                    start=int(first); end=int(last) if last else size-1
                else:
                    count=int(last or '0'); start=max(0,size-count); end=size-1
                if start>=size or end<start:
                    stream.close(); self.send_response(416); self.send_header('Content-Range',f'bytes */{size}'); self.send_header('Content-Length','0'); self.end_headers(); return
                end=min(end,size-1); status=206
            length=max(0,end-start+1)
            self.send_response(status); self.send_header('Content-Type',typ); self.send_header('Content-Length',str(length)); self.send_header('Accept-Ranges','bytes'); self.send_header('X-Content-Type-Options','nosniff')
            if status==206: self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            with stream:
                stream.seek(start); remaining=length
                while remaining:
                    chunk=stream.read(min(1024*1024,remaining))
                    if not chunk: break
                    self.wfile.write(chunk); remaining-=len(chunk)
            return
        rel=unquote(u.path.lstrip('/'))
        if rel in {'README.html','UPDATE GUIDE.md','PROJECT HANDOFF.md'}: target=ROOT/rel
        elif rel == 'README.md': target=ROOT/'app'/'README.md'
        elif rel.startswith('app/'): target=ROOT/rel
        elif rel == '' or rel == 'index.html': target=ROOT/'app'/'index.html'
        else: target=ROOT/'app'/rel
        try: data=target.read_bytes()
        except OSError: self.send_error(404); return
        typ=mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        self.send_response(200); self.send_header('Content-Type',typ); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)

def main():
    server=ThreadingHTTPServer((HOST,PORT),Handler)
    print(f'Offline Field Library: http://{HOST}:{PORT}')
    threading.Thread(target=build_index, name='library-indexer', daemon=True).start()
    server.serve_forever()
if __name__=='__main__': main()
