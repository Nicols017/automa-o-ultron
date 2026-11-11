import unittest
from chatops.install_request import installation_command


class InstallRequestTests(unittest.TestCase):
    def test_exact_command_for_known_program_and_host(self):
        self.assertIn("/instalar 192.0.2.4 Google.Chrome", installation_command(
            "instala o Chrome no PC 192.0.2.4", {"chrome": "Google.Chrome"}))

    def test_no_inferred_action_from_questions_or_mixed_requests(self):
        for text in ("como instalar chrome?", "não instala chrome", "instala chrome e reinicia"):
            self.assertIsNone(installation_command(text, {"chrome": "Google.Chrome"}))
