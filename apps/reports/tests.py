from django.test import TestCase
from unittest.mock import patch, MagicMock

from apps.reports.llm_service import ReportLLMService


class ReportLLMServiceTests(TestCase):
    def test_generate_report_text_returns_string(self):
        """generate_report_text should return a string."""
        data = {
            "session_title": "Murder Mystery - Villa Rosa",
            "duration_minutes": 28,
            "participants": [
                {"name": "Mario", "turns": 12, "percentage": 38},
                {"name": "Luigi", "turns": 8, "percentage": 25},
            ],
            "ai_interventions": 3,
            "ai_intervention_percentage": 6,
            "votes": [
                {"name": "Mario", "chose": "Eddie", "correct": True},
                {"name": "Luigi", "chose": "Mickey", "correct": False},
            ],
            "guilty": "Eddie",
            "success_rate": 50,
            "final_summary": "I partecipanti hanno discusso gli indizi...",
        }

        result = ReportLLMService.generate_report_text(data)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    @patch.object(ReportLLMService, '_build_azure_client')
    def test_generate_report_text_calls_azure(self, mock_client):
        """generate_report_text should call Azure OpenAI."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Test report content"
        mock_client.return_value.chat.completions.create.return_value = mock_response

        data = {
            "session_title": "Test Session",
            "duration_minutes": 20,
            "participants": [],
            "ai_interventions": 0,
            "ai_intervention_percentage": 0,
            "votes": [],
            "guilty": "Eddie",
            "success_rate": 0,
            "final_summary": "Test summary",
        }

        result = ReportLLMService.generate_report_text(data)

        mock_client.return_value.chat.completions.create.assert_called_once()
        self.assertEqual(result, "Test report content")

    def test_fallback_report_on_error(self):
        """Fallback report is returned on Azure error."""
        with patch.object(ReportLLMService, '_build_azure_client', side_effect=Exception("API Error")):
            data = {
                "session_title": "Test Session",
                "duration_minutes": 20,
                "participants": [{"name": "Mario", "turns": 5, "percentage": 50}],
                "ai_interventions": 2,
                "ai_intervention_percentage": 10,
                "votes": [{"name": "Mario", "chose": "Eddie", "correct": True}],
                "guilty": "Eddie",
                "success_rate": 100,
                "final_summary": "Test summary",
            }

            result = ReportLLMService.generate_report_text(data)

            # Should return fallback with basic info
            self.assertIn("Test Session", result)
            self.assertIn("Eddie", result)
