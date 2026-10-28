"""Tests for ECP-150M status decoding and discovery."""

import pytest

from jebao.const import MODEL_ECP150M, MODEL_MDP20000
from jebao.discovery import JebaoDiscovery
from jebao.ecp150m import ECP150MSegment, ECP150MStatus, Wave
from jebao.exceptions import JebaoCommandError

# Header and segments as read from the two pumps; the reads are 401 bytes, with
# 0xEE filler up to byte 391 and a 9-byte tail that never changed between reads.
# Pump 1: Linkage master, Sine, 30 %, frequency 100, feed 10 min
MASTER = (
    bytes.fromhex("04391e640a1e64000a0a0a00021e64010a000a0a021e6400")
    + b"\xee" * 368
    + bytes.fromhex("141805130004173400")
)
# Pump 2: Manual, Constant, 57 %, frequency 50, feed 20 min (feed likely running)
MANUAL = (
    bytes.fromhex("00653932140064000900160003646400")
    + b"\xee" * 376
    + bytes.fromhex("1418051300041c2300")
)


def with_header(byte0: int, byte1: int) -> bytes:
    return bytes([byte0, byte1]) + MANUAL[2:]


def test_linkage_master():
    status = ECP150MStatus.from_bytes(MASTER)
    assert status.is_linkage_master
    assert not status.is_linkage_slave
    assert status.wave is Wave.SINE
    assert (status.flow, status.frequency, status.feed_duration) == (30, 100, 10)
    # 0x08 is set on the master, but it tracks the linked slave there
    assert not status.is_program_mode
    assert status.segments == (
        ECP150MSegment(10, 10, 10, 0, 0x02, (30, 100), 1),
        ECP150MSegment(10, 0, 10, 10, 0x02, (30, 100), 0),
    )


def test_manual():
    status = ECP150MStatus.from_bytes(MANUAL)
    assert not status.is_linkage_master
    assert not status.is_linkage_slave
    assert status.wave is Wave.CONSTANT
    assert (status.flow, status.frequency, status.feed_duration) == (57, 50, 20)
    assert not status.is_program_mode
    assert status.is_feed_active
    assert status.is_on
    assert status.segments == (ECP150MSegment(9, 0, 22, 0, 0x03, (100, 100), 0),)
    assert status.raw == MANUAL


@pytest.mark.parametrize("byte0", [0x01, 0x07])
def test_linkage_slave(byte0):
    status = ECP150MStatus.from_bytes(with_header(byte0, 0x21))
    assert status.is_linkage_slave
    assert not status.is_linkage_master


@pytest.mark.parametrize(
    "byte1,wave", [(0x21, Wave.SINE), (0x41, Wave.RANDOM), (0x61, Wave.CONSTANT), (0x01, None)]
)
def test_wave_bits(byte1, wave):
    assert ECP150MStatus.from_bytes(with_header(0x00, byte1)).wave is wave


def test_program_mode_when_standalone():
    # Pump 2 read 0x29 after it was switched to Program
    status = ECP150MStatus.from_bytes(with_header(0x00, 0x29))
    assert status.is_program_mode
    assert status.wave is Wave.SINE


def test_segments_stop_before_tail():
    status = bytes(8) + bytes([6, 0, 7, 0, 2, 50, 50, 0]) * 48 + MANUAL[392:]
    assert len(ECP150MStatus.from_bytes(status).segments) == 48


def test_rejects_wrong_length():
    with pytest.raises(JebaoCommandError):
        ECP150MStatus.from_bytes(MANUAL[:-1])


def discovery_response(module: bytes, product_key: bytes) -> bytes:
    def field(value: bytes) -> bytes:
        return len(value).to_bytes(2, "big") + value

    body = (
        bytes.fromhex("000004")
        + field(b"A" * 22)
        + field(bytes.fromhex("020000000001"))
        + field(module)
        + field(product_key)
        + bytes(8)
        + b"euapi.gizwits.com:80\x004.1.2\x0003030000\x00"
    )
    return bytes.fromhex("00000003") + bytes([len(body)]) + body


def test_discovery_recognizes_ecp150m():
    response = discovery_response(b"04020B28", b"1d8c63eaccac4205b92c84d77d5a08fb")
    device = JebaoDiscovery._parse_discovery_response(response, "192.0.2.10")
    assert device is not None
    assert device.model == MODEL_ECP150M
    assert device.is_ecp150m
    assert not device.is_mdp20000
    assert device.mac_address == "02:00:00:00:00:01"


def test_discovery_keeps_mdp20000():
    # Same third field as the ECP-150M, different product key
    response = discovery_response(b"04020B28", b"0" * 32)
    device = JebaoDiscovery._parse_discovery_response(response, "192.0.2.10")
    assert device is not None
    assert device.model == MODEL_MDP20000
    assert not device.is_ecp150m
