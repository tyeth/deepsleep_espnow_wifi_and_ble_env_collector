"""Host-only failure injection; fixture bytes are not real certificates."""
import contextlib, importlib.util, io, json, sys, tempfile
from pathlib import Path
from unittest.mock import patch

repo=Path(sys.argv[1]).resolve()
sys.path.insert(0, str(repo / "collector"))
spec=importlib.util.spec_from_file_location('certstore',repo/'collector/certstore.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
result={'scope':'host filesystem failure injection; mocked certificate expiry; no hardware or real credentials'}
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);cert=root/c.CERT;key=root/c.KEY
    cert.write_text('old-chain');key.write_text('old-key')
    rx=c.Installer(tmp);rx.write('cert','new-chain');rx.write('key','PRIVATE KEY new-key')
    rename=c.os.rename
    def fail_second(src,dst):
        if str(src).endswith(c.KEY+'.new'):
            raise OSError('injected key promotion failure')
        return rename(src,dst)
    with patch.object(c,'not_after',return_value=4102444800),patch.object(c.os,'rename',side_effect=fail_second),contextlib.redirect_stdout(io.StringIO()):
        ok=rx.finish()
    result['second_rename_failure']={'finish':ok,'live_chain':cert.read_text(),'live_key':key.read_text(),'key_new_left':(root/(c.KEY+'.new')).exists()}
    assert not ok and cert.read_text()=='new-chain' and key.read_text()=='old-key'
with tempfile.TemporaryDirectory() as tmp:
    real=c.Installer
    with patch.object(c,'Installer',side_effect=lambda:real(tmp)),patch.object(c,'not_after',return_value=None),contextlib.redirect_stdout(io.StringIO()):
        c.receive('begin');c.receive('c','invalid-chain');c.receive('k','PRIVATE KEY fixture')
        end=c.receive('end');abort=c.receive('abort')
    result['rejected_end_then_abort']={'end_has_error':'err' in end,'abort_ok':abort.get('ok'),
        'receiver_cleared':c._rx[0] is None,'leftover_names':sorted(p.name for p in Path(tmp).iterdir())}
    assert 'err' in end and c._rx[0] is None and len(result['rejected_end_then_abort']['leftover_names'])==2
print(json.dumps(result,indent=2))
