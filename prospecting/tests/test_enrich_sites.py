# -*- coding: utf-8 -*-
"""Test offline di enrich_sites.py e dell'estensione Overpass (server HTTP locale).
Uso: python3 -m unittest discover -s prospecting/tests -p 'test_*.py'"""
import http.server
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import enrich_sites as es  # noqa: E402
import find_candidates as fc  # noqa: E402


def cf_encode(email, key=0x42):
    return f"{key:02x}" + "".join(f"{b ^ key:02x}" for b in email.encode())


PAGES = {
    "/": '<html><body><a href="/contatti">Contatti</a><a href="https://altro.it/contatti">x</a></body></html>',
    "/contatti": ('<p>Scrivici: <a href="mailto:Info@Clinica.it?subject=Ciao">mail</a></p>'
                  '<img src="logo@2x.png">'),
    "/cf/": f'<a class="__cf_email__" data-cfemail="{cf_encode("vet@cf.it")}">[email protected]</a>',
    "/obf/": "<p>scrivi a studio [at] vetobf [dot] it oggi</p>",
    "/ld/": '<script type="application/ld+json">{"@type":"VeterinaryCare","email":"mailto:ld@vetld.it"}</script>',
    "/none/": "<p>nessun contatto qui</p>",
    "/free/": "<p>Contattaci: dott.rossi@gmail.com</p>",
    "/robots-no/": "<a href='mailto:no@robots.it'>x</a>",
}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/robots.txt":
            body = b"User-agent: *\nDisallow: /robots-no/\n"
            ctype = "text/plain"
        elif self.path in PAGES:
            body, ctype = PAGES[self.path].encode(), "text/html; charset=utf-8"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)


class ExtractTests(unittest.TestCase):
    def test_mailto_cloudflare_obfuscated_jsonld(self):
        self.assertEqual(es.extract_emails(PAGES["/contatti"]), ["info@clinica.it"])
        self.assertEqual(es.extract_emails(PAGES["/cf/"]), ["vet@cf.it"])
        self.assertEqual(es.extract_emails(PAGES["/obf/"]), ["studio@vetobf.it"])
        self.assertEqual(es.extract_emails(PAGES["/ld/"]), ["ld@vetld.it"])

    def test_junk_scartato(self):
        html = "a@sentry.io b@example.com noreply@x.it foto@2x.png privacy@y.it ok@vera.it"
        self.assertEqual(es.extract_emails(html), ["ok@vera.it"])

    def test_pick_best_preferisce_dominio_del_sito(self):
        self.assertEqual(es.pick_best(["a@gmail.com", "b@clinica.it"], "https://www.clinica.it"),
                         "b@clinica.it")
        self.assertIsNone(es.pick_best([], "https://x.it"))


class CrawlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def check(self, path):
        return es.check_site(self.base + path, allow_local=True, delay=0)

    def test_segue_pagina_contatti(self):
        email, page, res = self.check("/")
        self.assertEqual((email, res), ("info@clinica.it", "email"))
        self.assertTrue(page.endswith("/contatti"))

    def test_nessuna_email(self):
        self.assertEqual(self.check("/none/")[2], "nessuna email")

    def test_email_free_accettata_se_unica(self):
        self.assertEqual(self.check("/free/")[0], "dott.rossi@gmail.com")

    def test_robots_vieta(self):
        email, _, res = self.check("/robots-no/")
        self.assertIsNone(email)
        self.assertEqual(res, "robots.txt vieta")

    def test_rete_interna_bloccata_di_default(self):
        _, _, res = es.check_site(self.base + "/", allow_local=False, delay=0)
        self.assertTrue(res.startswith("bloccato"), res)


class ArchiveTests(unittest.TestCase):
    def test_apply_result_e_duplicati(self):
        rows = [{"n": "A", "site": "https://a.it", "email": None, "notes": "n."},
                {"n": "B", "site": "https://b.it", "email": "x@b.it"}]
        self.assertTrue(es.apply_result(rows, 0, "info@a.it", "https://a.it/contatti", "email"))
        self.assertEqual(rows[0]["email"], "info@a.it")
        self.assertIn("sito ufficiale", rows[0]["notes"])
        rows.append({"n": "C", "site": "https://c.it", "email": None})
        self.assertFalse(es.apply_result(rows, 2, "x@b.it", "https://c.it", "email"))
        self.assertIsNone(rows[2]["email"])  # email gia' di un'altra scheda

    def test_needs_check(self):
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        self.assertTrue(es.needs_check({"site": "https://a.it"}, now))
        self.assertFalse(es.needs_check({"site": "https://a.it", "email": "a@a.it"}, now))
        self.assertFalse(es.needs_check({"email": None}, now))
        recent = {"site": "https://a.it", "_site_checked_at": fc.utc_now(), "_site_result": "nessuna email"}
        self.assertFalse(es.needs_check(recent, now))


class OverpassTests(unittest.TestCase):
    def test_query_include_sito_web(self):
        self.assertTrue(fc.WEBSITE_ENRICH)
        q = fc.build_region_query('area["ISO3166-2"="IT-62"]')
        self.assertIn('["website"~"."]', q)
        self.assertIn('["email"~"."]', q)

    def test_filter_records(self):
        recs = [{"n": "a", "email": "a@a.it", "osm_type": "node", "osm_id": 1},
                {"n": "b", "email": None, "site": "https://b.it", "osm_type": "node", "osm_id": 2},
                {"n": "c", "email": None, "site": None, "osm_type": "node", "osm_id": 3}]
        self.assertEqual([r["n"] for r in fc.filter_records(recs)], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
