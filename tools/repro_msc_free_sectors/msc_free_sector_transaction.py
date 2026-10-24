"""Bounded FAT12 free-sector transaction; no filesystem metadata writes."""
import hashlib
import struct


def plan(image):
    def u16(o): return struct.unpack_from('<H', image, o)[0]
    def u32(o): return struct.unpack_from('<I', image, o)[0]
    if len(image) < 1024 or len(image) % 512 or image[510:512] != b'\x55\xaa':
        raise ValueError('invalid disk')
    entries = [image[446+16*i:462+16*i] for i in range(4)]
    used = [e for e in entries if e[4]]
    if len(used) != 1 or used[0][4] not in (1, 4, 6):
        raise ValueError('expected one FAT partition')
    start, sectors = struct.unpack_from('<II', used[0], 8)
    if start != 1 or (start + sectors)*512 != len(image):
        raise ValueError('partition bounds')
    b = start*512
    total = u16(b+19) or u32(b+32)
    spc, reserved, fats, roots, fat_sectors = image[b+13], u16(b+14), image[b+16], u16(b+17), u16(b+22)
    if image[b+510:b+512] != b'\x55\xaa' or u16(b+11) != 512 or spc != 1:
        raise ValueError('unsupported sector/cluster geometry')
    if total != sectors or reserved < 1 or fats not in (1, 2) or not roots or not fat_sectors:
        raise ValueError('invalid BPB')
    data_lba = start + reserved + fats*fat_sectors + (roots*32+511)//512
    count = start+total-data_lba
    if not 8 <= count < 4085:
        raise ValueError('requires FAT12')
    fat_start = b+reserved*512
    fat = image[fat_start:fat_start+fat_sectors*512]
    if ((count+1)*3//2)+2 > len(fat):
        raise ValueError('short FAT')
    for i in range(1, fats):
        if fat != image[fat_start+i*len(fat):fat_start+(i+1)*len(fat)]:
            raise ValueError('FAT copies differ')
    free = set()
    for cluster in range(2, count+2):
        offset = cluster*3//2
        value = int.from_bytes(fat[offset:offset+2], 'little')
        value = value >> 4 if cluster & 1 else value & 0xfff
        if value == 0:
            free.add(data_lba+cluster-2)
    pairs = sorted(lba for lba in free if lba+1 in free)
    crosses = [lba for lba in pairs if lba % 8 == 7 and lba >= pairs[0]+2 and lba+2 <= pairs[-1]] if pairs else []
    if not pairs or not crosses:
        raise ValueError('insufficient free sectors')
    chosen = [pairs[0], crosses[0], pairs[-1]]
    if len(set(sector for lba in chosen for sector in (lba,lba+1))) != 6:
        raise ValueError('test spans overlap')
    return {'fat_type':'FAT12', 'cluster_count':count, 'free_clusters':len(free),
            'data_start_lba':data_lba, 'spans':[{'lba':v,'sectors':2} for v in chosen]}


def transact(image, read_all, write_span, check_cdc):
    geometry = plan(image)
    state = {'geometry':geometry, 'checks':[], 'restore_verified':False,
             'disk_bytes':len(image), 'before_sha256':hashlib.sha256(image).hexdigest()}
    if read_all() != image:
        raise ValueError('stale preimage; no write attempted')
    for index, span in enumerate(geometry['spans']):
        offset, size = span['lba']*512, span['sectors']*512
        original = image[offset:offset+size]
        pattern = bytes((i*73+index*29+101)%256 for i in range(size))
        expected = image[:offset]+pattern+image[offset+size:]
        try:
            # The restoration scope begins BEFORE a potentially partial write.
            write_span(span['lba'], pattern)
            if read_all() != expected:
                raise ValueError('pattern or unrelated-sector mismatch')
            check_cdc(index)
            state['checks'].append({'lba':span['lba'], 'bytes':size, 'pattern_exact':True})
        finally:
            write_span(span['lba'], original)
            if read_all() != image:
                raise ValueError('whole-disk restoration mismatch')
    state['restore_verified'] = True
    state['after_sha256'] = hashlib.sha256(read_all()).hexdigest()
    if state['before_sha256'] != state['after_sha256']:
        raise ValueError('final whole-disk mismatch')
    return state
