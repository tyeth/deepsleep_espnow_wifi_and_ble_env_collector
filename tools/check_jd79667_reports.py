"""Execute a pinned driver constructor with host substitutes, not a display test."""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import types
from unittest.mock import patch


def run(source):
    class Display:
        def __init__(self, bus, start, stop, **kwargs):
            self.start = bytes(start)
            self.stop = bytes(stop)
            self.kwargs = kwargs

    class Bus:
        def __init__(self, reset_pin=True):
            self.reset_pin = reset_pin

        def reset(self):
            if not self.reset_pin:
                raise RuntimeError('No reset pin')

    modules = {'epaperdisplay': types.ModuleType('epaperdisplay'),
               'fourwire': types.ModuleType('fourwire')}
    modules['epaperdisplay'].EPaperDisplay = Display
    modules['fourwire'].FourWire = Bus
    rows = []
    with patch.dict(sys.modules, modules):
        namespace = {}
        exec(compile(source, '<pinned-driver>', 'exec'), namespace)
        for reset in (True, False):
            for overrides in (False, True):
                output = io.StringIO()
                options = dict(width=384, height=184, rotation=270)
                if overrides:
                    options.update(refresh_time=20, seconds_per_frame=20)
                with contextlib.redirect_stdout(output):
                    display = namespace['JD79667'](Bus(reset), **options)
                assert bool(display.stop) == reset
                assert display.start[display.start.index(b'\x61\x04')+2:][:4] == b'\x00\xb8\x01\x80'
                timings = {k:display.kwargs[k] for k in ('refresh_time','seconds_per_frame') if k in display.kwargs}
                assert timings == ({'refresh_time':20,'seconds_per_frame':20} if overrides else {})
                rows.append(dict(reset_pin=reset, explicit_timings=overrides,
                                 forwarded_timings=timings, start_sequence=display.start.hex(' '), stdout=output.getvalue()))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    assert digest == 'bdab0a5a3f5a8651177632d683863d085bef87a0dbfc10d40e26c852d69ffe0c'
    before = run(source.decode())
    for case in before:
        assert case['stdout'] == case['start_sequence']+'\n'
        assert 'AttributeError' not in case['stdout']
    line = '        print(start_sequence.hex(" "))\n'
    assert source.decode().count(line) == 1
    after = run(source.decode().replace(line,''))
    assert all(case['stdout']=='' for case in after)
    result = dict(upstream_revision='4a5ce53302152058cac151cef6d5c528304d3437',
                  source_sha256=digest, evidence='actual driver executed with host EPaperDisplay/FourWire substitutes',
                  hardware_test=False, upstream_cases=before, removed_print_control=after,
                  attribute_error_reproduced=False, panel_timing_measured=False,
                  conclusion='Unconditional hex diagnostic reproduced. Removing only that print silences all four controls. Timing kwargs pass through; defaults are inherited.')
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('source_sha256','hardware_test','attribute_error_reproduced','panel_timing_measured','conclusion')}))


if __name__ == '__main__':
    main()
