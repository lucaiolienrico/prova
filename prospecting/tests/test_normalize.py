import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from find_candidates import norm_email  # noqa: E402


class NormEmail(unittest.TestCase):
    def test_multi_indirizzo_prende_il_primo(self):
        self.assertEqual(norm_email("a@x.it;b@x.it"), "a@x.it")

    def test_separatore_finale(self):
        self.assertEqual(norm_email("vitadacani@vitadacani.org;"), "vitadacani@vitadacani.org")

    def test_pec_solo_se_unica(self):
        self.assertEqual(norm_email("x@pec.it;info@x.it"), "info@x.it")
        self.assertEqual(norm_email("x@pec.it"), "x@pec.it")

    def test_non_valida(self):
        self.assertIsNone(norm_email("non-una-email"))
        self.assertIsNone(norm_email(None))


if __name__ == "__main__":
    unittest.main()
