import struct
import unittest
from msc_free_sector_transaction import plan, transact


def fixture():
    data = bytearray(1017*512)
    data[510:512] = data[1022:1024] = b'\x55\xaa'
    data[450] = 6
    struct.pack_into('<II', data, 454, 1, 1016)
    struct.pack_into('<H', data, 523, 512)
    data[525] = 1
    struct.pack_into('<H', data, 526, 1)
    data[528] = 1
    struct.pack_into('<H', data, 529, 512)
    struct.pack_into('<H', data, 531, 1016)
    struct.pack_into('<H', data, 534, 3)
    data[1024:1027] = b'\xf8\xff\xff'
    return bytes(data)


class Tests(unittest.TestCase):
    def run_tx(self, mode=None):
        original = fixture(); current = bytearray(original); calls = []
        def read(): return bytes(current)
        def write(lba, data):
            calls.append(lba)
            if mode == 'partial' and len(calls) == 1:
                current[lba*512:lba*512+512] = data[:512]
                raise IOError('partial write')
            if mode == 'restore' and len(calls) == 2:
                raise IOError('restore failed')
            current[lba*512:lba*512+len(data)] = data
        def cdc(i):
            if mode == 'cdc': raise TimeoutError('CDC failed')
        try:
            result = transact(original, read, write, cdc)
            self.assertEqual(len(result['checks']), 3)
            self.assertTrue(result['restore_verified'])
        finally:
            if mode != 'restore': self.assertEqual(current, original)
        return calls

    def test_success(self): self.assertEqual(len(self.run_tx()), 6)
    def test_partial_write_restored(self):
        with self.assertRaisesRegex(IOError, 'partial'): self.run_tx('partial')
    def test_cdc_failure_restored(self):
        with self.assertRaisesRegex(TimeoutError, 'CDC'): self.run_tx('cdc')
    def test_restore_failure_visible(self):
        with self.assertRaisesRegex(IOError, 'restore'): self.run_tx('restore')
    def test_stale_no_writes(self):
        writes=[]
        with self.assertRaisesRegex(ValueError, 'stale'):
            transact(fixture(), lambda:b'changed', lambda *a:writes.append(a), lambda _:None)
        self.assertFalse(writes)
    def test_partition_bounds(self):
        data=bytearray(fixture());struct.pack_into('<I',data,458,999999)
        with self.assertRaisesRegex(ValueError,'bounds'): plan(data)
    def test_occupied_sectors_not_selected(self):
        data=bytearray(fixture())
        # Mark clusters 2 and 3 allocated in the packed FAT12 pair.
        data[1027:1030]=b'\xff\xff\xff'
        chosen=plan(bytes(data))
        self.assertGreaterEqual(chosen['spans'][0]['lba'],39)
    def test_full_disk_refused(self):
        data=bytearray(fixture());data[1024:2560]=b'\xff'*1536
        with self.assertRaisesRegex(ValueError,'free'): plan(bytes(data))
    def test_bad_sector_geometry(self):
        data=bytearray(fixture());data[525]=2
        with self.assertRaisesRegex(ValueError,'geometry'): plan(bytes(data))


if __name__ == '__main__': unittest.main()
