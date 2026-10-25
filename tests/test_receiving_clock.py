from sandbox.checkpoints import same_instant


def test_time_zone_conversion_preserves_original_receiving_instant():
 assert same_instant('2026-10-23T04:50:00Z','2026-10-23T10:20:00+05:30')


def test_clock_reset_and_timezone_ambiguity_are_not_accepted():
 assert not same_instant('2026-10-23T05:50:00Z','2026-10-23T10:20:00+05:30')
 assert not same_instant('2026-10-23T10:20:00','2026-10-23T10:20:00+05:30')
