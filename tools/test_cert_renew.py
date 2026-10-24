"""Certificate renewal must retain cross-signs in longer CA chains."""
import importlib.util
from pathlib import Path
import tempfile
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "collector"))
spec = importlib.util.spec_from_file_location('certstore', ROOT/'collector/certstore.py')
certstore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(certstore)


class RenewalChainTest(unittest.TestCase):
    def test_renew_keeps_cross_signed_intermediate(self):
        certificates = [f'-----BEGIN CERTIFICATE-----\n{label}\n-----END CERTIFICATE-----'
                        for label in ('leaf', 'issuing-ca', 'cross-signed-root')]
        combined = '\n'.join(certificates) + '\n'
        key = '-----BEGIN PRIVATE KEY-----\nfixture-only\n-----END PRIVATE KEY-----\n'

        def fetch(pool, url, sink):
            data = (combined if url.endswith('ssl.combined') else key).encode()
            for start in range(0, len(data), 17):
                sink(data[start:start+17])
            return 200

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(certstore, '_https_get', fetch), patch.object(certstore, 'not_after', return_value=time.time()+86400):
                self.assertTrue(certstore.renew(None, directory))
            saved = (Path(directory)/certstore.CERT).read_text()
            self.assertEqual(saved.count('-----BEGIN CERTIFICATE-----'), 3)
            for certificate in certificates:
                self.assertIn(certificate, saved)
            self.assertLess(saved.index('issuing-ca'), saved.index('cross-signed-root'))
            self.assertEqual((Path(directory)/certstore.KEY).read_text(), key)


if __name__ == '__main__':
    unittest.main()
