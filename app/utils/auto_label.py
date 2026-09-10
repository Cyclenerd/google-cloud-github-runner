"""
Auto-failover request labels: ``gcp-auto-<tier>-<cores>[-min<N>]``.

Beside the explicit template labels (``gcp-ubuntu-24-04-8core`` -> one regional template), a job
may ask for a *class* of machine and let the manager walk a ladder of prebuilt templates until one
zone of the region has capacity. The ladder is owner-specified and fixed here:

* compute: c4-16 > e2-16 > c4-8 > e2-8 > c4-4 > e2-4 > c4-2 > e2-2  (compute may downgrade into general)
* general: e2-16 > e2-8 > e2-4 > e2-2                                (general never tries compute)

The optional floor ``-min<N>`` (default 2) stops the walk: the manager fails loudly rather than land
on fewer cores than the floor. Within each rung every zone of the region is tried before stepping
down (rung -> zones -> next rung).

Templates are regular regional templates named ``<prefix>-<rung>-<14+ digits>`` (e.g.
``gcp-ubuntu-24-04-compute-16-20260909120000``) so the existing template lookup finds them.
"""
import os
import re
from dataclasses import dataclass

AUTO_LABEL_PREFIX = 'gcp-auto-'
TIERS = ('compute', 'general')
CORES = (16, 8, 4, 2)
DEFAULT_FLOOR = 2
# Template name prefix in front of the rung, e.g. gcp-ubuntu-24-04-compute-16-<timestamp>.
DEFAULT_TEMPLATE_PREFIX = 'gcp-ubuntu-24-04'

# Rung name -> machine type; the rung name is what goes into template names and labels.
RUNG_MACHINE_TYPES = {
    'compute-16': 'c4-standard-16',
    'compute-8': 'c4-standard-8',
    'compute-4': 'c4-standard-4',
    'compute-2': 'c4-standard-2',
    'general-16': 'e2-standard-16',
    'general-8': 'e2-standard-8',
    'general-4': 'e2-standard-4',
    'general-2': 'e2-standard-2',
}

# Full ladders per tier, top to bottom. The walk starts at the rung matching the request's cores.
LADDERS = {
    'compute': [
        'compute-16', 'general-16',
        'compute-8', 'general-8',
        'compute-4', 'general-4',
        'compute-2', 'general-2',
    ],
    'general': ['general-16', 'general-8', 'general-4', 'general-2'],
}

_AUTO_LABEL_RE = re.compile(
    r'^gcp-auto-(?P<tier>compute|general)-(?P<cores>16|8|4|2)(?:-min(?P<floor>16|8|4|2))?$'
)


class InvalidAutoLabel(ValueError):
    """A label that starts with ``gcp-auto-`` but does not follow the grammar."""


@dataclass(frozen=True)
class AutoRequest:
    """A parsed ``gcp-auto-...`` label."""
    label: str
    tier: str
    cores: int
    floor: int

    @property
    def requested_rung(self):
        return f"{self.tier}-{self.cores}"

    def ladder(self):
        """Rungs to try, in order, from the requested rung down to the floor (inclusive)."""
        rungs = LADDERS[self.tier]
        start = rungs.index(self.requested_rung)
        return [rung for rung in rungs[start:] if rung_cores(rung) >= self.floor]


def is_auto_label(label):
    """True when the label uses the ``gcp-auto-`` prefix (valid or not)."""
    return isinstance(label, str) and label.startswith(AUTO_LABEL_PREFIX)


def parse_auto_label(label):
    """
    Parse a ``gcp-auto-<tier>-<cores>[-min<N>]`` label.

    Returns:
        AutoRequest or None: None when the label is not an auto label at all.

    Raises:
        InvalidAutoLabel: when the label starts with ``gcp-auto-`` but is malformed
            (unknown tier/cores, or a floor above the requested cores).
    """
    if not is_auto_label(label):
        return None
    match = _AUTO_LABEL_RE.match(label)
    if not match:
        raise InvalidAutoLabel(
            f"Invalid auto label '{label}': expected gcp-auto-<compute|general>-<16|8|4|2>[-min<16|8|4|2>]"
        )
    cores = int(match.group('cores'))
    floor = int(match.group('floor')) if match.group('floor') else DEFAULT_FLOOR
    if floor > cores:
        raise InvalidAutoLabel(f"Invalid auto label '{label}': floor min{floor} is above the requested {cores} cores")
    return AutoRequest(label=label, tier=match.group('tier'), cores=cores, floor=floor)


def rung_cores(rung):
    return int(rung.rsplit('-', 1)[1])


def rung_template_prefix(rung, template_prefix=None):
    """Template name prefix for a rung, matched by the existing ``^prefix-\\d{14,}`` lookup."""
    prefix = template_prefix or os.environ.get('AUTO_TEMPLATE_PREFIX', DEFAULT_TEMPLATE_PREFIX)
    return f"{prefix}-{rung}"
