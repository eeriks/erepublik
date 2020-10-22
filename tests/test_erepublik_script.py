#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for `erepublik` package."""

from erepublik import Citizen

import unittest


class TestErepublik(unittest.TestCase):
    """Tests for `erepublik` package."""

    def setUp(self):
        """Set up test fixtures, if any."""
        self.citizen = Citizen("email", "password", False)
        self.citizen.config.interactive = False

    def test_should_do_levelup(self):
        self.citizen.energy.recovered = 1900
        self.citizen.energy.recoverable = 2940
        self.citizen.energy.interval = 30
        self.citizen.energy.limit = 3000
        self.citizen.details.xp = 14850
        self.assertTrue(self.citizen.should_do_levelup)

        self.citizen.energy.recoverable = 1000
        self.assertFalse(self.citizen.should_do_levelup)

    def test_should_travel_to_fight(self):
        self.citizen.config.always_travel = True
        self.assertTrue(self.citizen.should_travel_to_fight())
        self.citizen.config.always_travel = False
        self.assertFalse(self.citizen.should_travel_to_fight())

        self.citizen.energy.recovered = 1900
        self.citizen.energy.recoverable = 2940
        self.citizen.energy.interval = 30
        self.citizen.energy.limit = 3000
        self.citizen.details.xp = 14850
        self.assertTrue(self.citizen.should_travel_to_fight())
        self.citizen.details.xp = 15000
        self.assertFalse(self.citizen.should_travel_to_fight())

        self.citizen.energy.recovered = 3000
        self.citizen.energy.recoverable = 2910
        self.assertTrue(self.citizen.should_travel_to_fight())
        self.citizen.energy.recoverable = 2900
        self.assertFalse(self.citizen.should_travel_to_fight())

        # self.citizen.next_reachable_energy and self.citizen.config.next_energy
        self.citizen.config.next_energy = True
        self.citizen.energy.limit = 5000
        self.citizen.details.next_pp = [5000, 5250, 5750, 6250, 6750]
        self.citizen.details.pp = 4900
        self.citizen.energy.recovered = 4000
        self.citizen.energy.recoverable = 4510
        self.assertEqual(self.citizen.next_reachable_energy, 850)
        self.citizen.energy.recoverable = 4490
        self.assertTrue(self.citizen.should_travel_to_fight())
        self.assertEqual(self.citizen.next_reachable_energy, 350)
        self.citizen.energy.recovered = 100
        self.citizen.energy.recoverable = 150
        self.assertFalse(self.citizen.should_travel_to_fight())
        self.assertEqual(self.citizen.next_reachable_energy, 0)

    def test_should_fight(self):
        def is_wc_close():
            return self.citizen.max_time_till_full_ff > self.citizen.time_till_week_change
        self.citizen.config.fight = False
        self.assertEqual(self.citizen.should_fight(), (0, "Fighting not allowed!", False))

        self.citizen.config.fight = True

        # Level up
        self.citizen.energy.limit = 3000
        self.citizen.details.xp = 24705
        if not is_wc_close:
            self.assertEqual(self.citizen.should_fight(), (0, 'Level up', False))

            self.citizen.energy.recovered = 3000
            self.citizen.energy.recoverable = 2950
            self.citizen.energy.interval = 30
            self.assertEqual(self.citizen.should_fight(), (900, 'Level up', True))
            self.citizen.my_companies.ff_lockdown = 160
            self.assertEqual(self.citizen.should_fight(), (900, 'Level up', True))
            self.citizen.my_companies.ff_lockdown = 0

            # Level up reachable
            self.citizen.details.xp = 24400
            self.assertEqual(self.citizen.should_fight(), (305, 'Fighting for close Levelup. Doing 305 hits', True))
            self.citizen.my_companies.ff_lockdown = 160
            self.assertEqual(self.citizen.should_fight(), (305, 'Fighting for close Levelup. Doing 305 hits', True))
            self.citizen.my_companies.ff_lockdown = 0

            self.citizen.details.xp = 21000
            self.assertEqual(self.citizen.should_fight(), (75, 'Obligatory fighting for at least 75pp', True))
            self.citizen.my_companies.ff_lockdown = 160
            self.assertEqual(self.citizen.should_fight(), (75, 'Obligatory fighting for at least 75pp', True))
            self.citizen.my_companies.ff_lockdown = 0
            self.citizen.details.pp = 80

            # All-in (type = all-in and full ff)
            self.citizen.config.all_in = True
            self.assertEqual(self.citizen.should_fight(), (595, 'Fighting all-in. Doing 595 hits', False))
            self.citizen.my_companies.ff_lockdown = 160
            self.assertEqual(self.citizen.should_fight(), (
                435, 'Fight count modified (old count: 595 | FF: 595 | WAM ff_lockdown: 160 | New count: 435)', False
            ))
            self.citizen.my_companies.ff_lockdown = 0

            self.citizen.config.air = True
            self.citizen.energy.recoverable = 1000
            self.assertEqual(self.citizen.should_fight(), (400, 'Fighting all-in in AIR. Doing 400 hits', False))
            self.citizen.my_companies.ff_lockdown = 160
            self.assertEqual(self.citizen.should_fight(), (
                240, 'Fight count modified (old count: 400 | FF: 400 | WAM ff_lockdown: 160 | New count: 240)', False
            ))
            self.citizen.my_companies.ff_lockdown = 0
            self.citizen.config.all_in = False

            self.citizen.config.next_energy = True
            self.citizen.energy.limit = 5000
            self.citizen.details.next_pp = [100, 150, 250, 400, 500]
            self.assertEqual(self.citizen.should_fight(), (320, 'Fighting for +1 energy. Doing 320 hits', False))
            self.citizen.my_companies.ff_lockdown = 160
            self.assertEqual(self.citizen.should_fight(), (
                160, 'Fight count modified (old count: 320 | FF: 400 | WAM ff_lockdown: 160 | New count: 160)', False
            ))
            self.citizen.my_companies.ff_lockdown = 0
            self.citizen.energy.limit = 3000
            self.citizen.details.next_pp = [19250, 20000]
            self.citizen.config.next_energy = False

            # 1h worth of energy
            self.citizen.energy.recoverable = 2910
            self.assertEqual(self.citizen.should_fight(), (30, 'Fighting for 1h energy. Doing 30 hits', True))
