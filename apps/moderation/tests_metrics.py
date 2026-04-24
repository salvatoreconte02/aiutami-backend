from django.test import SimpleTestCase

from apps.moderation.metrics import compute_participation_metrics


class ComputeParticipationMetricsTests(SimpleTestCase):
    def test_empty_dict_returns_zero_avg_and_no_flags(self):
        result = compute_participation_metrics({})
        self.assertEqual(result["over_participators"], [])
        self.assertEqual(result["under_participators"], [])
        self.assertEqual(result["avg_turns"], 0.0)
        self.assertFalse(result["min_turns_reached"])

    def test_all_zero_turns_below_min_threshold(self):
        result = compute_participation_metrics({"Marco": 0, "Lucia": 0, "Anna": 0})
        self.assertEqual(result["over_participators"], [])
        self.assertEqual(result["under_participators"], [])
        self.assertEqual(result["avg_turns"], 0.0)
        self.assertFalse(result["min_turns_reached"])

    def test_equal_participation_no_flags(self):
        result = compute_participation_metrics({"Marco": 4, "Lucia": 3, "Anna": 2})
        self.assertEqual(result["over_participators"], [])
        self.assertEqual(result["under_participators"], [])
        self.assertAlmostEqual(result["avg_turns"], 3.0)
        self.assertTrue(result["min_turns_reached"])

    def test_exclusion_flagged_when_one_has_zero_turns(self):
        result = compute_participation_metrics({"Marco": 5, "Lucia": 1, "Anna": 0})
        self.assertEqual(result["over_participators"], ["Marco"])
        self.assertEqual(result["under_participators"], ["Anna"])
        self.assertAlmostEqual(result["avg_turns"], 2.0)
        self.assertTrue(result["min_turns_reached"])

    def test_monopolization_and_exclusion_both_flagged(self):
        result = compute_participation_metrics({"Marco": 9, "Lucia": 2, "Anna": 1})
        self.assertEqual(result["over_participators"], ["Marco"])
        self.assertEqual(result["under_participators"], ["Anna"])
        self.assertAlmostEqual(result["avg_turns"], 4.0)
        self.assertTrue(result["min_turns_reached"])

    def test_min_turns_reached_false_when_below_threshold(self):
        result = compute_participation_metrics({"Marco": 3, "Lucia": 1, "Anna": 0})
        self.assertFalse(result["min_turns_reached"])

    def test_min_turns_reached_true_exactly_at_threshold(self):
        result = compute_participation_metrics({"Marco": 4, "Lucia": 1, "Anna": 1})
        self.assertTrue(result["min_turns_reached"])

    def test_min_turns_scales_with_n(self):
        below = compute_participation_metrics(
            {"A": 3, "B": 2, "C": 2, "D": 1, "E": 1}
        )
        self.assertFalse(below["min_turns_reached"])
        at_threshold = compute_participation_metrics(
            {"A": 3, "B": 3, "C": 2, "D": 1, "E": 1}
        )
        self.assertTrue(at_threshold["min_turns_reached"])

    def test_under_list_sorted_by_ascending_turn_count(self):
        result = compute_participation_metrics(
            {"Marco": 85, "Anna": 5, "Lucia": 8, "Carla": 2}
        )
        self.assertEqual(result["under_participators"], ["Carla", "Anna", "Lucia"])

    def test_over_list_sorted_by_descending_turn_count(self):
        result = compute_participation_metrics(
            {"Marco": 50, "Anna": 50, "Lucia": 1, "Carla": 1, "Dino": 1, "Ivan": 1}
        )
        self.assertEqual(result["over_participators"], ["Anna", "Marco"])

    def test_custom_thresholds(self):
        result = compute_participation_metrics(
            {"Marco": 5, "Lucia": 1, "Anna": 0},
            over_threshold=3.0,
            under_threshold=0.2,
            min_turns_factor=1,
        )
        self.assertEqual(result["over_participators"], [])
        self.assertEqual(result["under_participators"], ["Anna"])
        self.assertTrue(result["min_turns_reached"])

    def test_strict_inequality_at_exact_threshold(self):
        """Soglia strict >: chi sta esattamente a 2×avg non è over, chi sta a 0.5×avg non è under."""
        result = compute_participation_metrics({"Marco": 4, "Lucia": 2, "Anna": 0})
        self.assertAlmostEqual(result["avg_turns"], 2.0)
        self.assertEqual(result["over_participators"], [])
        self.assertEqual(result["under_participators"], ["Anna"])
