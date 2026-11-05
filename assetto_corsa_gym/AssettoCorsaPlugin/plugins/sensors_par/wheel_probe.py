"""Wheel state from the CSP Lua probe DR01WheelProbe (shared memory Local\\DR01_wheels).

The probe (Lua app in the DR_01 research repository, ac_plugin/lua/DR01WheelProbe) writes the
player car's ac.StateWheel fields every graphics frame: tyre forces fx, fy (N), load, surface grip
under each wheel. acsys does not expose tyre forces, so the plugin reads them here and adds them
to its state record in the same frame as the rest of the record (DR_01: D-21, N-31).

The field layout must match LAYOUT in DR01WheelProbe.lua (checked by a test in DR_01).
Runs inside the game: Python 3.3, no f-strings.
"""
import ctypes
import mmap

MEMORY_NAME = "Local\\DR01_wheels"

_F = ctypes.c_float
_I = ctypes.c_int32


class WheelProbe(ctypes.Structure):
    _fields_ = [
        ("frame", _I), ("physicsAllowed", _I), ("physicsAvailable", _I), ("simTimeS", _F),
        ("mass", _F), ("fuel", _F), ("accG", _F * 3), ("localVelocity", _F * 3),
        ("fx", _F * 4), ("fy", _F * 4), ("mz", _F * 4), ("dx", _F * 4), ("dy", _F * 4),
        ("load", _F * 4), ("ndSlip", _F * 4), ("slipAngle", _F * 4), ("slipRatio", _F * 4),
        ("surfaceGrip", _F * 4), ("surfaceSectionIndex", _I * 4), ("surfaceSectorID", _I * 4),
        ("surfaceValidTrack", _I * 4),
        ("tyreWear", _F * 4), ("tyreVirtualKM", _F * 4), ("speedDifference", _F * 4),
        ("contactPoint", _F * 12),
    ]


class WheelProbeReader(object):
    """Copies of the probe memory. Opening creates the mapping if the probe is not running yet;
    then `frame` stays 0, which the client treats as "no probe data"."""

    def __init__(self, name=MEMORY_NAME):
        self.size = ctypes.sizeof(WheelProbe)
        self._mm = mmap.mmap(-1, self.size, name)

    def read(self, attempts=3):
        """Consistent copy of the probe state, or None if the probe kept writing during the copy.

        The probe increments `frame` after writing a whole frame, so a copy is consistent when
        `frame` is the same before and after copying.
        """
        for _ in range(attempts):
            before = _I.from_buffer_copy(self._mm[0:4]).value
            probe = WheelProbe.from_buffer_copy(self._mm[0:self.size])
            if probe.frame == before:
                return probe
        return None

    def close(self):
        self._mm.close()


def record_fields(probe):
    """Record fields from a probe copy: game units and signs (fx positive backwards, fy positive left).

    probe_load lets the client check that the probe and the acsys channels come from the same frame.
    """
    return {
        "probe_frame": probe.frame,
        "probe_fx": list(probe.fx),
        "probe_fy": list(probe.fy),
        "probe_load": list(probe.load),
        "probe_surface_grip": list(probe.surfaceGrip),
        "probe_surface_valid": list(probe.surfaceValidTrack),
    }
