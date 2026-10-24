"""Extract unmodified policy blocks; generate public, disposable test credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--circuitpython", type=Path, required=True)
parser.add_argument("--baseline", default="11.0.0-alpha.2")
parser.add_argument("--fixed", default="HEAD")
args = parser.parse_args()
root = Path(__file__).resolve().parent
source_path = "shared-module/ssl/SSLSocket.c"
records = {}
functions = []
for label, ref in (("baseline", args.baseline), ("fixed", args.fixed)):
    def git(*a):
        return subprocess.check_output(["git", "-C", str(args.circuitpython), *a])
    source = git("show", f"{ref}:{source_path}").decode()
    start = source.index("    int ret = mbedtls_ssl_config_defaults(&o->conf,")
    end = source.index("    #ifdef MBEDTLS_DEBUG_C", start)
    block = source[start:end]
    assert block.count("mbedtls_ssl_conf_authmode") >= 3
    functions.append(f"static int policy_{label}(policy_context *self, endpoint *o, bool server_side) {{\n" + block + "\ncleanup:\n    return ret;\n}\n")
    records[label] = {"commit": git("rev-parse", ref).decode().strip(),
                      "source_blob": git("rev-parse", f"{ref}:{source_path}").decode().strip(),
                      "policy_sha256": hashlib.sha256(block.encode()).hexdigest()}
(root / "src/policy.h").write_text("// Generated from actual CircuitPython source, without rewriting the policy.\n" + "\n".join(functions))
with tempfile.TemporaryDirectory() as td:
    temp = Path(td)
    arrays = []
    for name in ("trusted", "untrusted"):
        cert, key = temp / f"{name}.pem", temp / f"{name}.key"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "3650", "-subj", "/CN=envhub-test.invalid", "-addext", "subjectAltName=DNS:envhub-test.invalid", "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,digitalSignature,keyCertSign", "-addext", "extendedKeyUsage=serverAuth,clientAuth"], check=True, capture_output=True)
        for kind, file in (("cert", cert), ("key", key)):
            data = file.read_text()
            arrays.append(f"static const unsigned char {name}_{kind}[] =\n" + "\n".join(json.dumps(line + "\n") for line in data.splitlines()) + ";\n")
    (root / "src/credentials.h").write_text("// PUBLIC TEST CREDENTIALS ONLY. Never use outside this isolated test.\n" + "\n".join(arrays))
(root / "source-manifest.json").write_text(json.dumps(records, indent=2) + "\n")
print(json.dumps(records, indent=2))
