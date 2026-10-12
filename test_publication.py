"""Offline publication hygiene and compatible browser-header regressions."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from main import app
from ai_reviewer import DEMO_CONTRACT_TEXT

ROOT = Path(__file__).resolve().parent


class PublicationTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect', 'ai_reviewer.Anthropic'):
            guard=patch(target,side_effect=AssertionError('No network or AI calls in publication tests.'))
            guard.start();self.addCleanup(guard.stop)
        env=patch.dict(os.environ,{'PUBLIC_DEMO_ONLY':'true','ENABLE_REAL_AI':'false'},clear=True)
        env.start();self.addCleanup(env.stop)
        loader=patch('ai_reviewer.load_dotenv');loader.start();self.addCleanup(loader.stop)
        self.client=TestClient(app);self.addCleanup(self.client.close)

    def headers(self, response):
        self.assertEqual(response.headers['x-content-type-options'],'nosniff')
        self.assertEqual(response.headers['x-frame-options'],'DENY')
        self.assertEqual(response.headers['referrer-policy'],'no-referrer')
        self.assertEqual(response.headers['permissions-policy'],'camera=(), microphone=(), geolocation=()')
        self.assertNotIn('clipboard',response.headers['permissions-policy'])
        self.assertNotIn('content-security-policy',response.headers)
        self.assertEqual(response.headers['cache-control'],'no-store')

    def test_assets_health_and_demo_download_headers(self):
        for path in ('/','/review.js','/health','/demo-contract.pdf'):
            with self.subTest(path=path):
                response=self.client.get(path);self.assertEqual(response.status_code,200);self.headers(response)
        self.assertIn('text/html',self.client.get('/').headers['content-type'])
        self.assertIn('application/javascript',self.client.get('/review.js').headers['content-type'])
        self.assertEqual(self.client.get('/demo-contract.pdf').headers['content-type'],'application/pdf')

    def test_handled_errors_have_headers(self):
        for response in (self.client.get('/.env'),self.client.get('/ai-review-config'),
                         self.client.post('/analyze',files={'file':('bad.pdf',b'not PDF')})):
            self.assertGreaterEqual(response.status_code,400);self.headers(response)

    def test_request_limit_response_has_headers(self):
        from main import MAX_REQUEST_BYTES
        response=self.client.post('/analyze',content=b'',headers={'content-length':str(MAX_REQUEST_BYTES+1)})
        self.assertEqual(response.status_code,413);self.headers(response)

    def test_demo_still_free_with_headers(self):
        response=self.client.post('/ai-review-demo',json={'pages':[{'number':1,'text':DEMO_CONTRACT_TEXT}]})
        self.assertEqual(response.status_code,200);self.headers(response)
        self.assertEqual(response.json()['mode'],'mock')
        self.assertEqual([f['status'] for f in response.json()['findings']],['verified','verified','verification_failed'])

    def test_ignore_files_exclude_metadata_and_private_exports(self):
        private=['.DS_Store','benchmark/.DS_Store','nested/deeper/.DS_Store',
                 '.env','.env.production','benchmark/results/real_ai_runs/private/raw.json',
                 'benchmark/results/ai_evaluation_private.json','benchmark/results/combined_evaluation_private.md']
        public=['.env.example','benchmark/results/rule_based_baseline.json','benchmark/answer_key.json']
        with tempfile.TemporaryDirectory() as temp:
            subprocess.run(['git','init','--quiet',temp],check=True,capture_output=True)
            for ignore in ('.gitignore','.railwayignore'):
                with self.subTest(ignore=ignore):
                    result=subprocess.run(['git','-c',f'core.excludesFile={ROOT/ignore}','check-ignore','--no-index','--stdin'],
                        cwd=temp,input='\n'.join(private+public)+'\n',text=True,capture_output=True,check=True)
                    self.assertEqual(set(result.stdout.splitlines()),set(private))

    def test_no_finder_files_or_real_captures_tracked(self):
        files=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
        self.assertFalse(any(Path(name).name=='.DS_Store' for name in files if name))
        self.assertFalse(any('/real_ai_runs/' in name for name in files))

    def test_documentation_has_no_personal_absolute_paths_or_credentials(self):
        import re
        for path in [ROOT/'README.md',*(ROOT/'docs').glob('*.md')]:
            text=path.read_text()
            with self.subTest(path=path.name):
                self.assertIsNone(re.search(r'/Users/|/home/|[A-Za-z]:\\Users\\',text))
                self.assertIsNone(re.search(r'sk-ant-[A-Za-z0-9_-]{25,}|gh[pousr]_[A-Za-z0-9]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',text))
                self.assertIsNone(re.search(r'https?://[^\s/:@]+:[^\s/@]+@',text))
