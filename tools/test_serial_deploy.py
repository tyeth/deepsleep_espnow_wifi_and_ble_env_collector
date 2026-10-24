"""Raw REPL framing regressions, without a connected board."""
import unittest
from serial_deploy import Repl


class Stream:
    def __init__(self, reply):
        self.reply = bytearray(reply)
        self.written = b''

    @property
    def in_waiting(self):
        return min(3, len(self.reply))

    def write(self, data):
        self.written += data

    def read(self, count):
        out = bytes(self.reply[:count])
        del self.reply[:count]
        return out


class FramingTests(unittest.TestCase):
    def repl(self, reply):
        repl = Repl.__new__(Repl)
        repl.s = Stream(reply)
        return repl

    def test_fragmented_stdout(self):
        repl = self.repl(b'OKhello\r\n\x04\x04>')
        self.assertEqual(repl.exec('print("hello")'), 'hello\r\n')
        self.assertTrue(repl.s.written.endswith(b'\x04'))

    def test_stderr_separates_end_markers(self):
        repl = self.repl(b'OKbefore\n\x04ValueError: invalid pin\r\n\x04>')
        with self.assertRaisesRegex(RuntimeError, 'ValueError: invalid pin'):
            repl.exec('raise ValueError("invalid pin")')

    def test_empty_response(self):
        self.assertEqual(self.repl(b'OK\x04\x04>').exec('pass'), '')


if __name__ == '__main__':
    unittest.main()
