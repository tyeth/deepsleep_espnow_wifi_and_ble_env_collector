"""Fault-injected host tests of the real collector/node ESP-NOW guards.

Run from the repository: python tools/test_espnow_recovery.py
These validate application recovery decisions, not the firmware ring buffer.
"""
import ast
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'collector'))
import envproto


class FakePeer:
    def __init__(self, mac, channel=0):
        self.mac, self.channel = mac, channel


class FakeRadio:
    def __init__(self, error=None):
        self.error = error
        self.peers = []
        self.deinit = Mock()
        self.send = Mock()

    def __bool__(self):
        return True

    def __len__(self):
        return 1 if self.error else 0

    def read(self):
        if self.error:
            raise self.error
        return None


def node_functions(*names, **values):
    source = (ROOT / 'node/nodemain.py').read_text()
    tree = ast.parse(source)
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(selected) == len(names)
    ns = dict(envproto=envproto, **values)
    exec(compile(ast.Module(body=selected, type_ignores=[]), 'node/nodemain.py', 'exec'), ns)
    return ns


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.constructor = Mock(return_value=FakeRadio())
        self.espnow = SimpleNamespace(ESPNow=self.constructor, Peer=FakePeer)
        spec = importlib.util.spec_from_file_location('guard_under_test', ROOT / 'collector/net_espnow.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, espnow=self.espnow):
            spec.loader.exec_module(self.module)

    def test_ap_corruption_requests_reset_without_driver_rebuild(self):
        radio = FakeRadio(ValueError('Invalid buffer'))
        hub = self.module.EspNowHub(existing=radio, ap_active=True)
        self.assertEqual(hub.poll(), [])
        self.assertFalse(hub.enabled)
        self.assertTrue(hub.needs_reset)
        radio.deinit.assert_not_called()
        self.constructor.assert_not_called()
        self.assertEqual(hub.poll(), [])

    def test_non_ap_corruption_rebuilds_and_discards_stale_peers(self):
        radio = FakeRadio(ValueError('Invalid buffer'))
        hub = self.module.EspNowHub(existing=radio)
        hub._peer(b'\x02\x00\x00\x00\x00\x01')
        self.assertEqual(hub.poll(), [])
        radio.deinit.assert_called_once()
        self.constructor.assert_called_once()
        self.assertTrue(hub.enabled)
        self.assertFalse(hub.needs_reset)
        self.assertEqual(hub._peers, {})
        self.assertEqual(hub._peer_order, [])
        self.assertEqual(hub.poll(), [])

    def test_failed_rebuild_requests_reset(self):
        self.constructor.side_effect = OSError('no memory')
        hub = self.module.EspNowHub(existing=FakeRadio(ValueError('Invalid buffer')))
        self.assertEqual(hub.poll(), [])
        self.assertFalse(hub.enabled)
        self.assertTrue(hub.needs_reset)

    def test_existing_ap_never_initializes_missing_driver(self):
        hub = self.module.EspNowHub(ap_active=True)
        self.assertFalse(hub.enabled)
        self.constructor.assert_not_called()

    def test_peer_rotation_stays_below_idf_limit_and_reuses_mac(self):
        radio = FakeRadio()
        hub = self.module.EspNowHub(existing=radio)
        for i in range(32):
            self.assertTrue(hub.send(bytes([2, 0, 0, 0, 0, i]), b'test'))
            self.assertLessEqual(len(radio.peers), 16)
        mac = bytes([2, 0, 0, 0, 0, 31])
        first = hub._peer(mac)
        self.assertIs(hub._peer(mac), first)
        self.assertEqual(len(radio.peers), 16)
        self.assertEqual(len(hub._peer_order), 16)

    def test_node_invalid_buffer_does_not_confirm_delivery(self):
        ns = node_functions('_listen_reply', time=SimpleNamespace(monotonic=lambda: 0))
        self.assertEqual(ns['_listen_reply'](FakeRadio(ValueError('Invalid buffer')), 2, 42, 123), (None, None, False))

    def test_discovery_sends_explicit_broadcast_peer(self):
        peer = FakePeer(envproto.BROADCAST_MAC, 6)
        radio = FakeRadio()
        ns = node_functions('_discover', config={'name': 'test'}, next_msg_id=lambda: 1,
                            _channels=lambda ch: [6], alarm=SimpleNamespace(sleep_memory=bytearray(1)),
                            MEM_CHANNEL=0, _mk_peer=Mock(return_value=peer),
                            _listen_cfg=lambda e, t: ({'k': 'cfg'}, b'\x02\x00\x00\x00\x00\x01'))
        self.assertEqual(ns['_discover'](radio)[1], 6)
        radio.send.assert_called_once()
        self.assertIs(radio.send.call_args.args[1], peer)
        self.assertEqual(peer.mac, envproto.BROADCAST_MAC)

    def test_channel_move_drops_pinned_link_before_ap_switch(self):
        calls = []
        radio = SimpleNamespace(connected=True,
            start_station=lambda: calls.append('start_station'),
            stop_station=lambda: calls.append('stop_station'),
            start_ap=lambda **kw: calls.append(('start_ap', kw['channel'])),
            stop_ap=lambda: calls.append('stop_ap'))
        ns = node_functions('_set_home_channel', wifi=SimpleNamespace(radio=radio),
                            time=SimpleNamespace(sleep=lambda t: None), _home_ch=1, _sta_started=False)
        self.assertTrue(ns['_set_home_channel'](11))
        self.assertEqual(calls, ['start_station', 'stop_station', 'start_station', ('start_ap', 11), 'stop_ap'])
        self.assertEqual(ns['_home_ch'], 11)


if __name__ == '__main__':
    unittest.main()
