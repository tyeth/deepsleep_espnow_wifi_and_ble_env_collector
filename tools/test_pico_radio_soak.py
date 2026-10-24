import unittest
from types import SimpleNamespace
from pico_radio_soak import record_from_output, validate_cycle, select_console


class EvidenceTests(unittest.TestCase):
    def test_select_exact_serial_and_vendor(self):
        selected = SimpleNamespace(serial_number="feather", vid=0x1a86)
        other = SimpleNamespace(serial_number="bridge", vid=0x1a86)
        wrong_vendor = SimpleNamespace(serial_number="feather", vid=0x1209)
        self.assertIs(select_console([other, wrong_vendor, selected], "feather", 0x1a86), selected)

    def test_missing_or_ambiguous_console_is_refused(self):
        selected = SimpleNamespace(serial_number="feather", vid=0x1a86)
        for ports in ([], [selected, selected]):
            with self.assertRaises(RuntimeError):
                select_console(ports, "feather", 0x1a86)

    def test_raw_console_crlf(self):
        self.assertEqual(record_from_output('noise\r\nENVHUB_CYCLE {"wifi":2}\r\n', 'ENVHUB_CYCLE'), {'wifi': 2})

    def test_missing_or_duplicate_record(self):
        for output in ('', 'ENVHUB_CYCLE {}\nENVHUB_CYCLE {}'):
            with self.assertRaises(ValueError):
                record_from_output(output, 'ENVHUB_CYCLE')

    def test_bad_record_type(self):
        with self.assertRaises(ValueError):
            record_from_output('ENVHUB_CYCLE []', 'ENVHUB_CYCLE')

    def test_reject_bad_metrics_and_unbounded_scan(self):
        valid = dict(wifi=1, ble=2, seconds=8.2, gc_allocated=100, gc_free_estimate=65536)
        self.assertEqual(validate_cycle(valid), valid)
        for key, value in [('wifi', True), ('ble', -1), ('seconds', float('nan')), ('seconds', 25), ('gc_allocated', '100')]:
            with self.assertRaises(ValueError):
                validate_cycle(dict(valid, **{key: value}))


if __name__ == '__main__':
    unittest.main()
