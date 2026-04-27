from django.test import SimpleTestCase

from apps.moderation.metrics import compute_participation_metrics


class ComputeParticipationMetricsTests(SimpleTestCase):
    """
    Helper agnostic ai numeri: i contatori passati possono essere turn count
    o speaking time in secondi. La logica over/under (2× / 0.5× media) è
    identica. Il min check è sull'elapsed_seconds della sessione.
    """

    def test_empty_dict_returns_zero_avg_and_no_flags(self):
        result = compute_participation_metrics({}, elapsed_seconds=0)
        self.assertEqual(result["over_participators"], [])
        self.assertEqual(result["under_participators"], [])
        self.assertEqual(result["avg_speaking_time_s"], 0.0)
        self.assertFalse(result["min_time_reached"])

    def test_below_min_elapsed_no_flags_evaluated(self):
        # elapsed 200s = 3.3 min, sotto la soglia di 8 min → min_time_reached=False
        result = compute_participation_metrics(
            {"Marco": 100.0, "Lucia": 30.0, "Anna": 5.0},
            elapsed_seconds=200,
        )
        self.assertFalse(result["min_time_reached"])

    def test_above_min_elapsed_evaluates_flags(self):
        # elapsed 600s = 10 min, sopra la soglia → min_time_reached=True
        result = compute_participation_metrics(
            {"Marco": 180.0, "Lucia": 60.0, "Anna": 15.0},
            elapsed_seconds=600,
        )
        self.assertTrue(result["min_time_reached"])

    def test_exclusion_flagged_when_under_threshold(self):
        # speaking_time totale 255s, avg=85, under_threshold=42.5
        # Marco: 180 > 170 (2*85) → over
        # Lucia: 60 not < 42.5 → not under
        # Anna: 15 < 42.5 → under
        result = compute_participation_metrics(
            {"Marco": 180.0, "Lucia": 60.0, "Anna": 15.0},
            elapsed_seconds=600,
        )
        self.assertEqual(result["over_participators"], ["Marco"])
        self.assertEqual(result["under_participators"], ["Anna"])
        self.assertAlmostEqual(result["avg_speaking_time_s"], 85.0)

    def test_strict_inequality_at_exact_threshold(self):
        # avg=2.0, over=4.0, under=1.0
        # Marco 4.0 NOT > 4.0 (strict), Lucia 2.0, Anna 0.0 < 1.0
        result = compute_participation_metrics(
            {"Marco": 4.0, "Lucia": 2.0, "Anna": 0.0},
            elapsed_seconds=600,
        )
        self.assertAlmostEqual(result["avg_speaking_time_s"], 2.0)
        self.assertEqual(result["over_participators"], [])
        self.assertEqual(result["under_participators"], ["Anna"])

    def test_under_list_sorted_ascending(self):
        # avg=25, under_threshold=12.5
        # Anna(5), Lucia(8), Carla(2) all under. Sort ascending: Carla, Anna, Lucia.
        result = compute_participation_metrics(
            {"Marco": 85.0, "Anna": 5.0, "Lucia": 8.0, "Carla": 2.0},
            elapsed_seconds=600,
        )
        self.assertEqual(result["under_participators"], ["Carla", "Anna", "Lucia"])

    def test_over_list_sorted_descending(self):
        # 50,50,1,1,1,1: avg≈17.33, over≈34.67. Marco 50 over, Anna 50 over.
        # Tie → alphabetical asc within same value: Anna, Marco.
        result = compute_participation_metrics(
            {"Marco": 50.0, "Anna": 50.0, "Lucia": 1.0, "Carla": 1.0,
             "Dino": 1.0, "Ivan": 1.0},
            elapsed_seconds=600,
        )
        self.assertEqual(result["over_participators"], ["Anna", "Marco"])

    def test_custom_thresholds_and_min_elapsed(self):
        # over_threshold=3, under_threshold=0.2, min_elapsed_seconds=120
        # avg=2, over_cutoff=6, under_cutoff=0.4
        result = compute_participation_metrics(
            {"Marco": 5.0, "Lucia": 1.0, "Anna": 0.0},
            elapsed_seconds=130,
            over_threshold=3.0,
            under_threshold=0.2,
            min_elapsed_seconds=120.0,
        )
        self.assertEqual(result["over_participators"], [])
        self.assertEqual(result["under_participators"], ["Anna"])
        self.assertTrue(result["min_time_reached"])

    def test_default_min_elapsed_is_8_minutes(self):
        # 480s = 8 min: min_time_reached True at exactly threshold
        result_at = compute_participation_metrics(
            {"Marco": 100.0, "Lucia": 50.0, "Anna": 10.0},
            elapsed_seconds=480,
        )
        self.assertTrue(result_at["min_time_reached"])
        # 479s: just below
        result_below = compute_participation_metrics(
            {"Marco": 100.0, "Lucia": 50.0, "Anna": 10.0},
            elapsed_seconds=479,
        )
        self.assertFalse(result_below["min_time_reached"])

    def test_works_with_int_input_for_backwards_compat(self):
        """Helper agnostic: accetta dict con int (turn count) o float (seconds)."""
        result = compute_participation_metrics(
            {"Marco": 5, "Lucia": 1, "Anna": 0},
            elapsed_seconds=600,
        )
        # avg=2.0, over_cutoff=4, under_cutoff=1
        self.assertEqual(result["over_participators"], ["Marco"])
        self.assertEqual(result["under_participators"], ["Anna"])
