from __future__ import annotations

import socket
import struct
import time

_NTP_EPOCH_DELTA = 2_208_988_800


def compute_offset(t1: float, t2: float, t3: float, t4: float) -> float:
    return ((t2 - t1) + (t3 - t4)) / 2


def sntp_offset(host: str, timeout: float = 3.0) -> float:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        packet = bytearray(48)
        packet[0] = 0x23
        t1 = time.time()
        s.sendto(bytes(packet), (host, 123))
        data, _ = s.recvfrom(1024)
        t4 = time.time()
    if len(data) < 48:
        raise ValueError("SNTP reply too short")
    server_time = parse_server_time(data)
    return compute_offset(t1, server_time, server_time, t4)


def parse_server_time(data: bytes) -> float:
    secs = struct.unpack("!I", data[40:44])[0] - _NTP_EPOCH_DELTA
    frac = struct.unpack("!I", data[44:48])[0] / 2 ** 32
    return secs + frac


class Clock:
    def __init__(self, offset: float = 0.0):
        self.offset = offset

    def time(self) -> float:
        return time.time() + self.offset


def wait_until(clock: Clock, target_epoch: float, stop_check=None) -> None:
    while True:
        remaining = target_epoch - clock.time()
        if remaining <= 0:
            return
        if stop_check and stop_check():
            return
        if remaining > 0.25:
            time.sleep(min(remaining - 0.2, 0.5))
        else:
            time.sleep(0.01)
