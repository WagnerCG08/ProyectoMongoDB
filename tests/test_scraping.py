import socket
import unittest
from unittest.mock import patch

from app.scraping import ScrapeError, _validate_public_https_url, scrape_website
from scripts.scrape_company_sites import (
    CompanyPageParser,
    _normalize_phone,
    _proposed_updates,
)


class CompanyPageParserTests(unittest.TestCase):
    def test_extracts_metadata_contacts_and_images(self):
        parser = CompanyPageParser()
        parser.feed(
            '<html><head><title>Empresa</title>'
            '<meta property="og:description" content="Desarrollo de software">'
            '<meta property="og:image" content="/assets/logo.png"></head>'
            '<body><p>Desarrollo de software</p><script>tel:+1000</script>'
            '<a href="tel:+573001234567">Llámanos</a>'
            '<img src="/assets/company-logo.svg"></body></html>'
        )
        self.assertEqual(parser.title_parts, ["Empresa"])
        self.assertEqual(parser.metadata["og:description"], "Desarrollo de software")
        self.assertEqual(parser.contacts, ["tel:+573001234567"])
        self.assertEqual(parser.images, ["/assets/company-logo.svg"])
        self.assertEqual(parser.content_blocks, ["Desarrollo de software"])

    def test_preview_only_proposes_empty_fields(self):
        current = {
            "website_url": "https://manual.example",
            "contact": "",
            "image_url": "",
            "products": "Descripción ingresada manualmente",
        }
        scraped = {
            "candidate_fields": {
                "website_url": "https://official.example",
                "contact": "+573001234567",
                "image_url": "https://official.example/logo.png",
                "products": "Descripción del sitio oficial",
            },
            "source_urls": ["https://official.example/"],
            "fetched_at": "2026-10-30T12:00:00+00:00",
        }
        updates = _proposed_updates(current, scraped)
        self.assertEqual(updates["contact"], "+573001234567")
        self.assertEqual(updates["image_url"], "https://official.example/logo.png")
        self.assertNotIn("website_url", updates)
        self.assertNotIn("products", updates)
        self.assertEqual(
            updates["scraping_metadata"]["fields_populated"],
            ["contact", "image_url"],
        )

    def test_normalizes_only_complete_colombian_phone_numbers(self):
        self.assertEqual(_normalize_phone("(+57) 320 494-9937"), "+573204949937")
        self.assertEqual(_normalize_phone("310 573 6581"), "+573105736581")
        self.assertEqual(_normalize_phone("(57) 320 494-997"), "")


class WebsiteScrapingTests(unittest.TestCase):
    def test_rejects_non_https_local_and_nonstandard_port_urls(self):
        invalid_urls = (
            "http://example.com",
            "https://localhost",
            "https://127.0.0.1",
            "https://example.com:8443",
        )
        for url in invalid_urls:
            with self.subTest(url=url), self.assertRaises(ScrapeError):
                _validate_public_https_url(url)

    @patch(
        "app.scraping.socket.getaddrinfo",
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )
    def test_rejects_domain_resolving_to_private_ip(self, _getaddrinfo):
        with self.assertRaisesRegex(ScrapeError, "direcciones IP públicas"):
            _validate_public_https_url("https://example.com")

    @patch("app.scraping._read_page")
    @patch("app.scraping._read_robots", return_value=None)
    @patch(
        "app.scraping.socket.getaddrinfo",
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    def test_scrapes_preview_fields_without_fetching_image(
        self, _getaddrinfo, _robots_allow, read_page
    ):
        read_page.return_value = (
            "https://example.com/about",
            '<html><head><title>Example Company | Home</title>'
            '<meta property="og:description" content="Software development company">'
            '<meta property="og:image" content="https://images.example/logo.png">'
            '</head><body><a href="tel:+573001234567">Call</a></body></html>',
        )
        result = scrape_website("https://example.com/about")
        self.assertEqual(result["fields"]["name"], "Example Company")
        self.assertEqual(
            result["fields"]["products"], "Software development company"
        )
        self.assertEqual(result["fields"]["contact"], "+573001234567")
        self.assertNotIn("image_url", result["fields"])
        self.assertEqual(result["source_url"], "https://example.com/about")

    @patch("app.scraping._read_page")
    @patch("app.scraping._read_robots", return_value=None)
    @patch(
        "app.scraping.socket.getaddrinfo",
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    def test_source_reference_drops_tracking_query_parameters(
        self, _getaddrinfo, _read_robots, read_page
    ):
        read_page.return_value = (
            "https://example.com/software/?utm_source=ads&campaign=long-tracking-value",
            '<html><head><title>Example Company</title></head></html>',
        )
        result = scrape_website("https://example.com")
        self.assertEqual(result["source_url"], "https://example.com/software/")


if __name__ == "__main__":
    unittest.main()
