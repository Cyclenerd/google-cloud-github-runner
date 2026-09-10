"""
Tests for the gcp-auto-<tier>-<cores>[-min<N>] label grammar and the failover ladder.
"""
import re

import pytest

from app.utils.auto_label import (
    InvalidAutoLabel,
    LADDERS,
    RUNG_MACHINE_TYPES,
    is_auto_label,
    parse_auto_label,
    rung_template_prefix,
)


class TestParser:
    @pytest.mark.parametrize('label,tier,cores,floor', [
        ('gcp-auto-compute-16', 'compute', 16, 2),
        ('gcp-auto-general-4', 'general', 4, 2),
        ('gcp-auto-compute-16-min8', 'compute', 16, 8),
        ('gcp-auto-compute-8-min8', 'compute', 8, 8),
        ('gcp-auto-general-2', 'general', 2, 2),
    ])
    def test_valid_labels(self, label, tier, cores, floor):
        request = parse_auto_label(label)
        assert (request.tier, request.cores, request.floor, request.label) == (tier, cores, floor, label)
        assert request.requested_rung == f"{tier}-{cores}"

    @pytest.mark.parametrize('label', [
        'gcp-auto-compute-32',          # unknown cores
        'gcp-auto-storage-4',           # unknown tier
        'gcp-auto-compute-4-min8',      # floor above request
        'gcp-auto-compute-4-min3',      # floor not a rung
        'gcp-auto-compute',             # missing cores
        'gcp-auto-compute-4-',          # trailing dash
        'gcp-auto-Compute-4',           # case
        'gcp-auto-compute-4-min8-x',
    ])
    def test_malformed_auto_labels_raise(self, label):
        with pytest.raises(InvalidAutoLabel):
            parse_auto_label(label)

    @pytest.mark.parametrize('label', [
        'gcp-ubuntu-24-04-8core', 'gcp-ubuntu-24.04', 'dependabot', 'ubuntu-latest', '', None,
        'gcp-autobuild-4',  # only the exact 'gcp-auto-' prefix is the auto grammar
    ])
    def test_explicit_and_foreign_labels_are_not_auto(self, label):
        assert parse_auto_label(label) is None
        assert not is_auto_label(label)

    def test_template_regex_never_matches_an_auto_label_and_vice_versa(self):
        """The existing template lookup is ^prefix-\\d{14,}[a-z0-9]*$; an auto label has no timestamp."""
        template_regex = re.compile(r"^gcp-auto-compute-16-\d{14,}[a-z0-9]*$")
        assert not template_regex.match('gcp-auto-compute-16')
        assert not template_regex.match('gcp-auto-compute-16-min8')
        assert parse_auto_label('gcp-auto-compute-16') is not None
        # and a rung template name is never an auto label
        assert parse_auto_label('gcp-ubuntu-24-04-compute-16-20260909120000') is None


class TestLadder:
    def test_compute_ladder_order(self):
        assert parse_auto_label('gcp-auto-compute-16').ladder() == [
            'compute-16', 'general-16', 'compute-8', 'general-8', 'compute-4', 'general-4', 'compute-2', 'general-2',
        ]

    def test_general_ladder_order_never_tries_compute(self):
        assert parse_auto_label('gcp-auto-general-16').ladder() == ['general-16', 'general-8', 'general-4', 'general-2']
        assert all(rung.startswith('general-') for rung in LADDERS['general'])

    def test_ladder_starts_at_requested_rung(self):
        assert parse_auto_label('gcp-auto-compute-8').ladder() == [
            'compute-8', 'general-8', 'compute-4', 'general-4', 'compute-2', 'general-2',
        ]
        assert parse_auto_label('gcp-auto-general-4').ladder() == ['general-4', 'general-2']

    def test_floor_stops_the_ladder(self):
        assert parse_auto_label('gcp-auto-compute-16-min8').ladder() == [
            'compute-16', 'general-16', 'compute-8', 'general-8',
        ]
        assert parse_auto_label('gcp-auto-compute-8-min8').ladder() == ['compute-8', 'general-8']
        assert parse_auto_label('gcp-auto-general-16-min16').ladder() == ['general-16']

    def test_every_rung_has_a_machine_type(self):
        for rungs in LADDERS.values():
            for rung in rungs:
                assert rung in RUNG_MACHINE_TYPES
        assert RUNG_MACHINE_TYPES['compute-16'] == 'c4-standard-16'
        assert RUNG_MACHINE_TYPES['general-2'] == 'e2-standard-2'

    def test_template_prefix(self, monkeypatch):
        monkeypatch.delenv('AUTO_TEMPLATE_PREFIX', raising=False)
        assert rung_template_prefix('compute-16') == 'gcp-ubuntu-24-04-compute-16'
        monkeypatch.setenv('AUTO_TEMPLATE_PREFIX', 'gcp-ubuntu-22-04')
        assert rung_template_prefix('general-2') == 'gcp-ubuntu-22-04-general-2'
