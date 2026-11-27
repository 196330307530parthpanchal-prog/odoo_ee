"""Standalone tests (no Odoo needed):  python3 tests/run_rules_tests.py"""

import importlib.util, os, sys, unittest
from datetime import date, datetime, timedelta

spec = importlib.util.spec_from_file_location(
    "rules", os.path.join(os.path.dirname(__file__), "..", "lib", "attendance_rules.py")
)
R = importlib.util.module_from_spec(spec)
sys.modules["rules"] = R  # dataclasses need the module registered
spec.loader.exec_module(R)

D = date(2026, 9, 7)

def dt(h, m, s=0, day=D):
    return datetime(day.year, day.month, day.day, h, m, s)


def day(rule, i, o, **kw):
    s = R.summarise_punches([(i, o)])
    return R.evaluate_day(rule, working=True, summary=s, **kw)


GEN, A, B, C, G1 = (R.SHIFT_RULES[k] for k in ("general", "a", "b", "c", "g1"))
CL = R.LeaveInfo("CL", "full")
SHORT = R.LeaveInfo("SHORT", "short")


class Rules(unittest.TestCase):
    def test_match_rule(self):
        for n, k in [
            ("General Shift", "general"),
            ("Shift A", "a"),
            ("shift  b", "b"),
            ("Shift C", "c"),
            ("G1 Shift", "g1"),
        ]:
            self.assertEqual(R.match_rule(n).key, k)
        self.assertIsNone(R.match_rule("Standard 40 hours/week"))

    def test_rule_numbers(self):
        self.assertEqual((GEN.full_min, GEN.half_min), (560, 285))
        self.assertEqual((A.full_min, A.half_min), (510, 255))
        self.assertEqual((C.full_min, C.half_min, C.overnight), (510, 255, True))
        self.assertEqual((G1.full_min, G1.half_min), (570, 285))

    # ---- General shift ---------------------------------------------------
    def test_general_full(self):
        self.assertEqual(day(GEN, dt(9, 0), dt(18, 20)), "PP")  # exactly 9:20
        self.assertEqual(day(GEN, dt(9, 0), dt(18, 20, 59)), "PP")

    def test_general_one_minute_short_is_hd(self):
        self.assertEqual(day(GEN, dt(9, 0), dt(18, 19, 59)), "HD")  # 9:19:59 -> 9:19
        self.assertEqual(day(GEN, dt(9, 1), dt(18, 20)), "HD")  # 9:19

    def test_general_grace(self):
        self.assertEqual(day(GEN, dt(9, 1), dt(18, 20), grace_available=True), "PP")
        # grace never lifts a bigger shortfall
        self.assertEqual(day(GEN, dt(9, 10), dt(18, 20), grace_available=True), "HD")

    def test_general_half_day_boundary(self):
        self.assertEqual(day(GEN, dt(9, 0), dt(13, 45)), "HD")  # 4:45
        self.assertEqual(day(GEN, dt(9, 0), dt(13, 44)), "A")  # 4:44
        self.assertEqual(day(GEN, dt(9, 0), dt(10, 0)), "A")

    # ---- Other shifts ----------------------------------------------------
    def test_shift_a(self):
        self.assertEqual(day(A, dt(6, 0), dt(14, 30)), "PP")
        self.assertEqual(day(A, dt(6, 0), dt(14, 29)), "HD")
        self.assertEqual(day(A, dt(6, 0), dt(10, 15)), "HD")  # 4:15 = 8:30/2
        self.assertEqual(day(A, dt(6, 0), dt(10, 14)), "A")

    def test_shift_b(self):
        self.assertEqual(day(B, dt(14, 0), dt(22, 30)), "PP")
        self.assertEqual(day(B, dt(14, 0), dt(18, 15)), "HD")
        self.assertEqual(day(B, dt(14, 0), dt(18, 14)), "A")

    def test_shift_c_overnight(self):
        nxt = D + timedelta(days=1)
        self.assertEqual(day(C, dt(22, 0), dt(6, 30, day=nxt)), "PP")
        self.assertEqual(day(C, dt(22, 0), dt(2, 15, day=nxt)), "HD")
        self.assertEqual(day(C, dt(22, 0), dt(2, 14, day=nxt)), "A")

    def test_g1(self):
        self.assertEqual(day(G1, dt(9, 30), dt(19, 0)), "PP")
        self.assertEqual(day(G1, dt(9, 30), dt(14, 15)), "HD")  # 4:45
        self.assertEqual(day(G1, dt(9, 30), dt(14, 14)), "A")

    def test_grace_only_for_general(self):
        self.assertEqual(day(A, dt(6, 1), dt(14, 30), grace_available=True), "HD")

    # ---- Short leave ----------------------------------------------------
    def test_short_leave(self):
        self.assertEqual(
            day(GEN, dt(9, 0), dt(16, 30), leaves=[SHORT]), "SHORT"
        )  # 7:30
        self.assertEqual(day(GEN, dt(9, 0), dt(16, 29), leaves=[SHORT]), "HD")  # 7:29
        self.assertEqual(day(GEN, dt(9, 0), dt(16, 30)), "HD")  # not applied -> HD
        self.assertEqual(day(GEN, dt(9, 0), dt(18, 30), leaves=[SHORT]), "PP")

    def test_short_leave_shows_odoo_abbreviation(self):
        for abbr in ("SHORT", "SLV", "Short Leave", "SH"):
            leave = R.LeaveInfo(abbr, "short")
            st, kind = R.evaluate_day_detail(
                GEN,
                working=True,
                summary=R.summarise_punches([(dt(9, 0), dt(16, 45))]),
                leaves=[leave],
            )
            self.assertEqual((st, kind), (abbr, "short"))
            self.assertEqual(R.status_category(st, kind), "short")
        # registered but under 7h30 -> normal rule (HD), not the abbreviation
        st, kind = R.evaluate_day_detail(
            GEN,
            working=True,
            summary=R.summarise_punches([(dt(9, 0), dt(16, 0))]),
            leaves=[SHORT],
        )
        self.assertEqual((st, kind), ("HD", ""))
        # unregistered -> HD
        self.assertEqual(day(GEN, dt(9, 0), dt(16, 45)), "HD")

    def test_sick_leave_is_not_short_leave(self):
        self.assertFalse(R.is_short_leave("Sick Leave", "SL"))
        self.assertTrue(R.is_short_leave("Short Leave", ""))
        self.assertTrue(R.is_short_leave("Short", "SHORT"))

    # ---- Leaves / WO / mispunch ---------------------------------------
    def test_full_leave_not_wo(self):
        s = R.summarise_punches([])
        self.assertEqual(
            R.evaluate_day(GEN, working=True, summary=s, leaves=[CL]), "CL"
        )

    def test_weekoff_holiday_future(self):
        self.assertEqual(R.evaluate_day(GEN, working=False), "WO")
        self.assertEqual(R.evaluate_day(GEN, working=True, holiday=True), "PH")
        self.assertEqual(R.evaluate_day(GEN, working=True, is_future=True), "")
        self.assertEqual(R.evaluate_day(GEN, working=True), "A")

    def test_mispunch(self):
        s = R.summarise_punches([(dt(9, 0), dt(9, 0))])
        self.assertEqual(R.evaluate_day(GEN, working=True, summary=s), "MP")
        s = R.summarise_punches([(dt(9, 0), None)])
        self.assertEqual(R.evaluate_day(GEN, working=True, summary=s), "MP")

    def test_half_day_leave(self):
        am = R.LeaveInfo("CL", "half_am")
        pm = R.LeaveInfo("SL", "half_pm")
        self.assertEqual(day(GEN, dt(13, 0), dt(18, 30), leaves=[am]), "CL/P")
        self.assertEqual(day(GEN, dt(9, 0), dt(13, 50), leaves=[pm]), "P/SL")
        self.assertEqual(day(GEN, dt(9, 0), dt(10, 0), leaves=[pm]), "A/SL")
        s = R.summarise_punches([])
        self.assertEqual(
            R.evaluate_day(GEN, working=True, summary=s, leaves=[am]), "CL/A"
        )

    # ---- Shift-day assignment ---------------------------------------------
    def test_night_shift_assignment(self):
        rule_for = lambda d: C
        self.assertEqual(R.assign_shift_day(dt(21, 55), rule_for), D)
        self.assertEqual(
            R.assign_shift_day(dt(0, 30, day=D + timedelta(days=1)), rule_for), D
        )

    def test_shift_change_boundary(self):
        # Night shift C on the 7th, Shift A on the 8th: 06:05 on the 8th is A's start.
        rf = lambda d: C if d == D else A
        nxt = D + timedelta(days=1)
        self.assertEqual(R.assign_shift_day(dt(6, 5, day=nxt), rf), nxt)
        self.assertEqual(R.assign_shift_day(dt(22, 5), rf), D)

    def test_span_vs_multi_punch(self):
        s = R.summarise_punches([(dt(9, 0), dt(13, 0)), (dt(14, 0), dt(18, 20))])
        self.assertEqual(s["minutes"], 560)  # lunch is inside the stay

    def test_implausible_pair_is_mispunch(self):
        # 18:30 Thursday paired with 09:00 Monday (62h30) must NOT be PP
        out = datetime(2026, 9, 28, 9, 0)
        s = R.summarise_punches([(datetime(2026, 9, 25, 18, 30), out)])
        self.assertFalse(s["has_pair"])
        self.assertEqual(R.evaluate_day(A, working=True, summary=s), "MP")
        # 14h30 overnight stay is still accepted
        s = R.summarise_punches([(dt(18, 30), dt(9, 0, day=D + timedelta(days=1)))])
        self.assertTrue(s["has_pair"])

    def test_labels(self):
        self.assertEqual(
            [r.label for r in (GEN, A, B, C, G1)], ["General", "A", "B", "C", "G1"]
        )

    # ---- Two shifts on one day (regular + extra) ------------------------------
    def test_combine_a_plus_b(self):
        AB = R.combine_rules([A, B])
        self.assertEqual((AB.full_min, AB.half_min), (990, 495))
        self.assertEqual((AB.start_min, AB.end_min), (360, 1350))
        self.assertEqual(AB.name, "Shift A + Shift B")
        self.assertFalse(AB.is_general)

    def test_combine_single_and_duplicates(self):
        self.assertIs(R.combine_rules([A]), A)
        self.assertIs(R.combine_rules([A, A]), A)

    def test_combine_no_overlap(self):
        GB = R.combine_rules(
            [R.SHIFT_RULES["a"], R.SHIFT_RULES["c"]]
        )  # A 06-14:30, C 22-06:30
        self.assertEqual(GB.full_min, 1020)  # 17h, 0 overlap

    def double(self, i, o, **kw):
        AB = R.combine_rules([A, B])
        lim = R.pair_limit_minutes(AB)
        s = R.summarise_punches([(i, o)], max_pair_minutes=lim, mode="sum")
        return R.evaluate_day(AB, working=True, summary=s, **kw)

    def test_double_shift_full(self):
        self.assertEqual(self.double(dt(6, 0), dt(22, 30)), "PP")  # 16h30 accepted
        self.assertEqual(self.double(dt(6, 0), dt(22, 29)), "HD")

    def test_double_shift_only_one_worked(self):
        self.assertEqual(self.double(dt(6, 0), dt(14, 30)), "HD")  # 8h30 >= 8h15
        self.assertEqual(self.double(dt(6, 0), dt(14, 0)), "A")  # 8h00 < 8h15

    def test_double_shift_two_pairs_sum(self):
        AB = R.combine_rules([A, B])
        lim = R.pair_limit_minutes(AB)
        s = R.summarise_punches(
            [(dt(6, 0), dt(14, 30)), (dt(14, 0), dt(22, 30))],
            max_pair_minutes=lim,
            mode="sum",
        )
        self.assertEqual(s["minutes"], 1020)  # pairs are added, not merged
        s = R.summarise_punches(
            [(dt(6, 0), dt(14, 30)), (dt(15, 0), dt(22, 30))],
            max_pair_minutes=lim,
            mode="sum",
        )
        self.assertEqual(s["minutes"], 960)  # 30 min break not counted
        self.assertEqual(R.evaluate_day(AB, working=True, summary=s), "HD")

    def test_pair_limit_scales(self):
        self.assertEqual(R.pair_limit_minutes(A), 16 * 60)
        self.assertEqual(R.pair_limit_minutes(R.combine_rules([A, B])), 990 + 180)

    # ---- Total ----------------------------------------------------------
    def test_total(self):
        self.assertEqual(
            R.total_days(["PP", "A", "HD", "CL/A", "WO", "MP", "P/SL"], 7),
            7 - 1 - 0.5 - 0.5 - 1,
        )

    def test_categories(self):
        for c, k in [
            ("PP", "present"),
            ("HD", "half_day"),
            ("A", "absent"),
            ("WO", "week_off"),
            ("CL", "leave"),
            ("CL/P", "half_leave"),
            ("A/CL", "half_abs"),
            ("MP", "mispunch"),
            ("", "blank"),
        ]:
            self.assertEqual(R.status_category(c), k)


if __name__ == "__main__":
    unittest.main(verbosity=1)
