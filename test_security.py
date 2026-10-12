"""Focused security regressions; synthetic fixtures only, no networking or credentials."""
import asyncio
from io import BytesIO
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock

import pymupdf
from fastapi import UploadFile, HTTPException
from fastapi.testclient import TestClient
from docx import Document

import ai_reviewer
import main
import docx_reader
from benchmark import run_real_ai


class SecurityTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect', 'ai_reviewer.Anthropic', 'benchmark.run_real_ai.Anthropic'):
            guard = patch(target, side_effect=AssertionError('No AI or network requests allowed.'))
            guard.start(); self.addCleanup(guard.stop)
        environment = patch.dict(os.environ, {'PUBLIC_DEMO_ONLY': 'true', 'ENABLE_REAL_AI': 'true', 'ANTHROPIC_API_KEY': 'fake-private-marker-for-security-tests'}, clear=True)
        environment.start(); self.addCleanup(environment.stop)
        loader = patch('ai_reviewer.load_dotenv'); loader.start(); self.addCleanup(loader.stop)
        self.client = TestClient(main.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    def test_declared_oversize_rejected_before_any_file_is_spooled(self):
        with patch('starlette.formparsers.SpooledTemporaryFile') as spool:
            response = self.client.post('/analyze', content=b'', headers={'Content-Type': 'multipart/form-data; boundary=unused', 'Content-Length': str(main.MAX_REQUEST_BYTES + 1)})
        self.assertEqual(response.status_code, 413)
        spool.assert_not_called()

    def test_oversized_multipart_stops_before_document_parser(self):
        with patch('main.extract_docx') as extractor:
            response = self.client.post('/analyze', files={'file': ('oversize.docx', b'x' * (main.MAX_REQUEST_BYTES + 1))})
        self.assertEqual(response.status_code, 413)
        extractor.assert_not_called()

    def test_chunked_body_limit_without_content_length(self):
        responses = []
        chunks = iter([{'type': 'http.request', 'body': b'x' * 100, 'more_body': True},
                       {'type': 'http.request', 'body': b'x' * main.MAX_REQUEST_BYTES, 'more_body': False}])
        scope = {'type':'http', 'asgi': {'version':'3.0'}, 'http_version':'1.1', 'method':'POST',
                 'scheme':'http','path':'/ai-review-demo','raw_path':b'/ai-review-demo','query_string':b'',
                 'headers':[(b'content-type', b'application/json')], 'client':('127.0.0.1', 40000), 'server':('testserver',80)}
        async def receive(): return next(chunks)
        async def send(message): responses.append(message)
        asyncio.run(main.app(scope, receive, send))
        self.assertEqual(next(m['status'] for m in responses if m['type']=='http.response.start'), 413)

    def test_underreported_content_length_does_not_bypass_stream_limit(self):
        responses=[]
        chunks=iter([{'type':'http.request','body':b'x' * (main.MAX_REQUEST_BYTES + 1), 'more_body':False}])
        scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
               'path':'/ai-review-demo','raw_path':b'/ai-review-demo','query_string':b'',
               'headers':[(b'content-type', b'application/json'),(b'content-length', b'1')],
               'client':('127.0.0.1',40000),'server':('testserver',80)}
        async def receive(): return next(chunks)
        async def send(message): responses.append(message)
        asyncio.run(main.app(scope,receive,send))
        self.assertEqual(next(m['status'] for m in responses if m['type']=='http.response.start'),413)

    def test_rejected_stream_closes_multipart_temporary_files(self):
        import starlette.formparsers
        from tempfile import SpooledTemporaryFile
        files=[]
        def spool(*args, **kwargs):
            stream=SpooledTemporaryFile(*args, **kwargs);files.append(stream);return stream
        boundary=b'audit-boundary'
        opening=b'--'+boundary+b'\r\nContent-Disposition: form-data; name="file"; filename="x.docx"\r\nContent-Type: application/octet-stream\r\n\r\n'
        responses=[]
        chunks=iter([{'type':'http.request','body':opening+b'x'*2048,'more_body':True},
                     {'type':'http.request','body':b'x' * main.MAX_REQUEST_BYTES,'more_body':False}])
        scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
               'path':'/analyze','raw_path':b'/analyze','query_string':b'',
               'headers':[(b'content-type',b'multipart/form-data; boundary='+boundary)],
               'client':('127.0.0.1',40000),'server':('testserver',80)}
        async def receive(): return next(chunks)
        async def send(message): responses.append(message)
        with patch.object(starlette.formparsers, 'SpooledTemporaryFile', side_effect=spool):
            asyncio.run(main.app(scope,receive,send))
        self.assertTrue(files)
        self.assertTrue(all(f.closed for f in files))
        self.assertEqual(next(m['status'] for m in responses if m['type']=='http.response.start'),413)

    def test_pdf_page_limit_before_any_text_extraction(self):
        document=MagicMock();document.is_pdf=True;document.needs_pass=False;document.page_count=main.MAX_PDF_PAGES+1
        with patch('main.pymupdf.open') as opening:
            opening.return_value.__enter__.return_value=document
            with self.assertRaises(HTTPException) as error:
                main.analyze_document(UploadFile(file=BytesIO(b'fake fixture'),filename='sample.pdf'))
        self.assertEqual(error.exception.status_code,413)
        document.__iter__.assert_not_called()

    def test_extracted_pdf_text_limit_stops_before_detection(self):
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((72,72), 'Too much source text for test budget.')
            content=pdf.tobytes()
        with patch('main.MAX_TEXT_BYTES', 5), patch('main.detect_sections_and_references') as detection:
            response=self.client.post('/analyze',files={'file':('x.pdf',content,'application/pdf')})
        self.assertEqual(response.status_code,413)
        self.assertIn('Nothing was truncated',response.text)
        detection.assert_not_called()

    def test_pdf_utf8_budget_not_character_count(self):
        document=MagicMock();document.is_pdf=True;document.needs_pass=False;document.page_count=1
        page=MagicMock();page.get_text.return_value='ééé';document.__iter__.return_value=iter([page])
        with patch('main.pymupdf.open') as opening, patch('main.MAX_TEXT_BYTES',5):
            opening.return_value.__enter__.return_value=document
            with self.assertRaises(HTTPException) as error:
                main.analyze_document(UploadFile(file=BytesIO(b'fake fixture'),filename='x.pdf'))
        self.assertEqual(error.exception.status_code,413)

    def docx(self, paragraphs):
        document=Document()
        for text in paragraphs: document.add_paragraph(text)
        stream=BytesIO();document.save(stream);return stream.getvalue()

    def test_docx_source_text_budget(self):
        content=self.docx(['ééé'])
        with patch('docx_reader.MAX_TEXT_BYTES',5):
            response=self.client.post('/analyze',files={'file':('x.docx',content)})
        self.assertEqual(response.status_code,400)
        self.assertIn('Nothing was truncated', response.text)

    def test_docx_location_limit_counts_empty_paragraphs(self):
        content=self.docx(['','', 'Readable'])
        with patch('docx_reader.MAX_LOCATIONS',2):
            response=self.client.post('/analyze',files={'file':('x.docx',content)})
        self.assertEqual(response.status_code,400)
        self.assertIn('processing limit', response.text)

    def test_demo_flag_blocks_every_paid_boundary_including_runner(self):
        pages=[{'number':1,'text':'Synthetic source'}]
        for action in (lambda:ai_reviewer.send_text_to_claude('Source'),
                       lambda:ai_reviewer.analyze_contract(pages),
                       lambda:ai_reviewer.review_contract_real(pages,confirmed=True)):
            with self.assertRaises(ai_reviewer.ReviewError): action()
        with self.assertRaises(run_real_ai.RunnerError): run_real_ai.prepare()
        prepared=run_real_ai.Prepared(pages, 'Source', 'fake-secret', 'claude-sonnet-5-5',6,'fake-hash')
        capture=run_real_ai.capture_once(prepared,{})
        self.assertEqual(capture['request_attempts'],0)
        self.assertTrue(capture['errors'])

    def test_host_and_forwarded_headers_cannot_override_demo_flag(self):
        response=self.client.post('/ai-review-real',json={'confirmed':True,'pages':[{'number':1,'text':'Synthetic'}]},
                    headers={'host':'127.0.0.1','origin':'http://127.0.0.1','x-forwarded-for':'127.0.0.1'})
        self.assertEqual(response.status_code,403)
        self.assertNotIn('fake-private-marker',response.text)

    def test_private_source_and_ground_truth_paths_not_served(self):
        for path in ('/.env','/.env.production','/.git/config','/main.py','/README.md','/benchmark/answer_key.json',
                     '/benchmark/contract_source.json','/benchmark/results/rule_based_baseline.json',
                     '/benchmark/results/real_ai_runs/raw.json','/docs/SECURITY_AUDIT.md'):
            with self.subTest(path=path):
                response=self.client.get(path)
                self.assertEqual(response.status_code,404)
                self.assertNotIn('/Users/',response.text)
                self.assertNotIn('Traceback',response.text)

    def test_health_and_public_schema_no_environment_values(self):
        self.assertFalse(main.app.debug)
        self.assertEqual(self.client.get('/health').json(),{'status':'ok'})
        schema=self.client.get('/openapi.json')
        self.assertEqual(schema.status_code,200)
        self.assertNotIn('fake-private-marker',schema.text)
        self.assertNotIn('/Users/',schema.text)
        self.assertNotIn('ANTHROPIC_API_KEY',schema.text)

    def test_no_permissive_cors(self):
        response=self.client.options('/analyze',headers={'origin':'https://untrusted.example','access-control-request-method':'POST'})
        self.assertNotIn('access-control-allow-origin',response.headers)
        self.assertFalse(any(m.cls.__name__=='CORSMiddleware' for m in main.app.user_middleware))

    def test_unexpected_errors_do_not_expose_trace_or_private_message(self):
        with patch('main.extract_docx',side_effect=RuntimeError('fake-private-marker /Users/private secret')):
            response=self.client.post('/analyze',files={'file':('x.docx',b'fake')})
        self.assertEqual(response.status_code,500)
        self.assertNotIn('fake-private-marker',response.text)
        self.assertNotIn('/Users/',response.text)
        self.assertNotIn('RuntimeError',response.text)

    def test_no_html_execution_or_browser_storage_sinks(self):
        root=Path(__file__).resolve().parent
        text=(root/'index.html').read_text()+(root/'review.js').read_text()
        for token in ('innerHTML','outerHTML','insertAdjacentHTML','localStorage','sessionStorage','eval('):
            self.assertNotIn(token,text)
        self.assertIn('textContent',text)
        self.assertIn('Do not upload confidential or personal legal documents',text)

    def test_malformed_files_and_legacy_doc_have_safe_messages(self):
        for filename in ('invalid.pdf','invalid.docx','legacy.doc'):
            response=self.client.post('/analyze',files={'file':(filename,b'fake-private-marker /Users/private <script>')})
            self.assertEqual(response.status_code,400)
            self.assertNotIn('fake-private-marker',response.text)
            self.assertNotIn('/Users/',response.text)

    def test_no_secret_files_tracked(self):
        import subprocess
        root=Path(__file__).resolve().parent
        result=subprocess.run(['git','ls-files','-z'],cwd=root,capture_output=True,check=True)
        files=result.stdout.decode().split('\0')
        self.assertFalse(any(Path(name).name.startswith('.env') and Path(name).name!='.env.example' for name in files if name))
        self.assertFalse(any('/real_ai_runs/' in name for name in files))
