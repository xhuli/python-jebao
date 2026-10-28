"""ECP-150M wave pump status decoding (read-only).

The layout was worked out from status reads (message 0x93 with action 0x02,
answered by 0x94 with action 0x03) on two pumps, see
https://github.com/jrigling/python-jebao/issues/5. This module only decodes
status bytes; it sends nothing to the pump.

Status (401 bytes after the 0x94 header, sn and action):
- bytes 0-7: header
- from byte 8: 8-byte program segments, then 0xEE filler up to byte 391
- bytes 392-400: tail, not decoded
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

from .exceptions import JebaoCommandError

STATUS_SIZE = 401
HEADER_SIZE = 8
SEGMENT_SIZE = 8
TAIL_SIZE = 9
FILLER = 0xEE

# Header byte 0
LINKAGE_NONE = 0x00  # Manual or Program, not linked
LINKAGE_MASTER = 0x04
LINKAGE_SLAVE = frozenset({0x01, 0x07})

# Header byte 1
FLAG_ON = 0x01  # Inferred, matches the MDP-20000 state byte
FLAG_FEED = 0x04  # Inferred, matches the MDP-20000 state byte
FLAG_PROGRAM = 0x08  # Program mode on a standalone pump; set on a master while a slave is linked


class Wave(IntEnum):
    """Wave in header byte 1, bits 5-6."""

    SINE = 1
    RANDOM = 2
    CONSTANT = 3


@dataclass(frozen=True)
class ECP150MSegment:
    """One stored program segment."""

    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    wave: int  # 0x02 is Sine; not the same encoding as the header's wave bits
    values: tuple[int, int]  # Meaning unknown
    flag: int  # Meaning unknown


@dataclass(frozen=True)
class ECP150MStatus:
    """Decoded ECP-150M status."""

    linkage: int
    flags: int
    flow: int
    frequency: int
    feed_duration: int
    segments: tuple[ECP150MSegment, ...]
    raw: bytes

    @classmethod
    def from_bytes(cls, status: bytes) -> "ECP150MStatus":
        """Decode the status bytes that follow the 0x94 header, sn and action.

        Args:
            status: Status bytes (401)

        Returns:
            Decoded status

        Raises:
            JebaoCommandError: Status has the wrong length
        """
        if len(status) != STATUS_SIZE:
            raise JebaoCommandError(
                f"ECP-150M status is {len(status)} bytes, expected {STATUS_SIZE}"
            )

        segments = []
        for offset in range(HEADER_SIZE, STATUS_SIZE - TAIL_SIZE, SEGMENT_SIZE):
            record = status[offset : offset + SEGMENT_SIZE]
            if record[0] == FILLER:
                break
            segments.append(
                ECP150MSegment(
                    start_hour=record[0],
                    start_minute=record[1],
                    end_hour=record[2],
                    end_minute=record[3],
                    wave=record[4],
                    values=(record[5], record[6]),
                    flag=record[7],
                )
            )

        return cls(
            linkage=status[0],
            flags=status[1],
            flow=status[2],
            frequency=status[3],
            feed_duration=status[4],
            segments=tuple(segments),
            raw=bytes(status),
        )

    @property
    def is_linkage_master(self) -> bool:
        """Check if pump is the Linkage master."""
        return self.linkage == LINKAGE_MASTER

    @property
    def is_linkage_slave(self) -> bool:
        """Check if pump is a Linkage slave."""
        return self.linkage in LINKAGE_SLAVE

    @property
    def wave(self) -> Optional[Wave]:
        """Get current wave, or None for a value not seen so far."""
        value = (self.flags >> 5) & 0x03
        return Wave(value) if value else None

    @property
    def is_program_mode(self) -> bool:
        """Check if a standalone pump is in Program mode.

        On a Linkage master the same bit appears to track a linked slave
        instead, so this is only reported for pumps that are not linked.
        """
        return self.linkage == LINKAGE_NONE and bool(self.flags & FLAG_PROGRAM)

    @property
    def is_feed_active(self) -> bool:
        """Check if feed mode is active (inferred)."""
        return bool(self.flags & FLAG_FEED)

    @property
    def is_on(self) -> bool:
        """Check if pump is on (inferred)."""
        return bool(self.flags & FLAG_ON)
