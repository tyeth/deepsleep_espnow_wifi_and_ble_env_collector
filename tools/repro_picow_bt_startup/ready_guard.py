def add_ready_guard(source):
    start=source.index('    ret = cybt_fw_download_prepare(&p_write_buf, &p_hex_buf);')
    end=source.index('    cybt_debug("// cybt_wait_bt_ready\\n");',start)
    block=source[start:end].rstrip('\n')
    return (source[:start]+'    /* Diagnostic retry control: do not overwrite already-ready BT firmware. */\n'
            +'    if (!cybt_ready()) {\n'+''.join('    '+line+'\n' for line in block.splitlines())
            +'    }\n\n'+source[end:])


if __name__ == "__main__":
    import argparse, hashlib
    from pathlib import Path
    parser = argparse.ArgumentParser(description="Apply the exact ready-state comparison to the previously instrumented HAL source")
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    original = args.source.read_bytes()
    if hashlib.sha256(original).hexdigest() != "6dffc1439c797269bda94a0e0e59f85070888415d995c5585001cf20355b03b7":
        raise SystemExit("Refusing source other than the exact original diagnostic HAL")
    changed = add_ready_guard(original.decode()).encode()
    assert hashlib.sha256(changed).hexdigest() == "eecdce1362a042f4f264e70add3711e27367778b0d09f40be23fe34248704702"
    args.source.write_bytes(changed)
