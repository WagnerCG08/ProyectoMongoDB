import re
import unittest
from unittest.mock import patch

from bson import ObjectId

from app import create_app
from app.scraping import ScrapeError


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    def sort(self, field, direction):
        reverse = direction == -1
        self.documents.sort(key=lambda item: item.get(field, "").lower(), reverse=reverse)
        return self

    def __iter__(self):
        return iter(self.documents)


class FakeCollection:
    def __init__(self):
        self.documents = []

    def find(self, query=None):
        query = query or {}
        regex_query = query.get("name")
        if regex_query:
            expression = re.compile(regex_query["$regex"], re.IGNORECASE)
            documents = [item for item in self.documents if expression.search(item["name"])]
        else:
            documents = list(self.documents)
        return FakeCursor(documents)

    def find_one(self, query):
        return next((item for item in self.documents if item["_id"] == query["_id"]), None)

    def insert_one(self, document):
        inserted = {**document, "_id": ObjectId()}
        self.documents.append(inserted)
        return type("InsertResult", (), {"inserted_id": inserted["_id"]})()

    def update_one(self, query, update):
        document = self.find_one(query)
        if document is None:
            return type("UpdateResult", (), {"matched_count": 0})()
        document.update(update["$set"])
        return type("UpdateResult", (), {"matched_count": 1})()

    def delete_one(self, query):
        document = self.find_one(query)
        if document is None:
            return type("DeleteResult", (), {"deleted_count": 0})()
        self.documents.remove(document)
        return type("DeleteResult", (), {"deleted_count": 1})()


class FakeDatabase:
    def __init__(self):
        self.collection = FakeCollection()

    def __getitem__(self, _name):
        return self.collection


class FakeMongoClient:
    def __init__(self):
        self.database = FakeDatabase()

    def __getitem__(self, _name):
        return self.database


class CompanyRoutesTests(unittest.TestCase):
    def setUp(self):
        self.mongo_client = FakeMongoClient()
        app = create_app(
            {"TESTING": True, "SECRET_KEY": "test-key"},
            mongo_client=self.mongo_client,
        )
        self.client = app.test_client()

    def create_company(self, name="Seobyte", **overrides):
        data = {
            "name": name,
            "address": "Villavicencio, Meta",
            "category": "Desarrollo web",
            "products": "Aplicaciones y sitios web",
            "contact": "",
            "website_url": "https://example.com",
            "image_url": "",
        }
        data.update(overrides)
        return self.client.post("/companies", data=data)

    def test_create_and_read_company(self):
        response = self.create_company()
        self.assertEqual(response.status_code, 302)
        detail = self.client.get(response.headers["Location"])
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Seobyte", detail.data)
        self.assertIn(b"https://example.com", detail.data)

    def test_new_company_form_offers_scraping_preview(self):
        response = self.client.get("/companies/new")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Consultar sitio y completar ficha", response.data)
        self.assertIn(b"company-scrape.js", response.data)

    def test_search_matches_partial_name_case_insensitively(self):
        self.create_company("Seobyte")
        response = self.client.get("/?q=oby")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Seobyte", response.data)

    def test_search_treats_regex_metacharacters_as_text(self):
        self.create_company("Tech Company")
        response = self.client.get("/?q=.*")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No encontramos coincidencias", response.data)

    def test_update_company(self):
        self.create_company()
        company_id = str(self.mongo_client.database.collection.documents[0]["_id"])
        response = self.client.post(
            f"/companies/{company_id}/edit",
            data={
                "name": "Seobyte actualizado",
                "address": "Meta",
                "category": "Software",
                "products": "Servicios cloud",
                "contact": "",
                "website_url": "https://example.com",
                "image_url": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(b"Seobyte actualizado", self.client.get(response.headers["Location"]).data)

    def test_delete_company(self):
        self.create_company()
        company_id = str(self.mongo_client.database.collection.documents[0]["_id"])
        response = self.client.post(f"/companies/{company_id}/delete")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.mongo_client.database.collection.documents, [])

    @patch("app.routes.fetch_public_image", return_value=(b"\xff\xd8image", "image/jpeg"))
    def test_company_image_is_served_by_the_application(self, fetch_image):
        self.create_company(image_url="https://example.com/logo.jpg")
        company_id = str(self.mongo_client.database.collection.documents[0]["_id"])
        response = self.client.get(f"/companies/{company_id}/image")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/jpeg")
        self.assertEqual(response.data, b"\xff\xd8image")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        fetch_image.assert_called_once_with("https://example.com/logo.jpg")

    def test_company_without_logo_gets_local_placeholder(self):
        self.create_company(image_url="")
        company_id = str(self.mongo_client.database.collection.documents[0]["_id"])
        response = self.client.get(f"/companies/{company_id}/image")
        self.assertEqual(response.status_code, 302)
        self.assertIn("company-placeholder.svg", response.headers["Location"])

    @patch("app.routes.fetch_public_image", side_effect=ScrapeError("Imagen no permitida."))
    def test_failed_company_image_load_falls_back_to_placeholder(self, _fetch_image):
        self.create_company(image_url="https://example.com/logo.jpg")
        company_id = str(self.mongo_client.database.collection.documents[0]["_id"])
        response = self.client.get(f"/companies/{company_id}/image")
        self.assertEqual(response.status_code, 302)
        self.assertIn("company-placeholder.svg", response.headers["Location"])

    def test_rejects_invalid_official_url(self):
        response = self.create_company(website_url="javascript:alert(1)")
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Ingresa una URL v", response.data)

    @patch("app.routes.scrape_website")
    def test_preview_scrape_and_create_company_with_source_metadata(self, scrape):
        scrape.return_value = {
            "fields": {
                "name": "Empresa desde sitio",
                "website_url": "https://official.example/",
                "products": "Desarrollo de software a medida.",
            },
            "source_url": "https://official.example/",
        }
        preview = self.client.post(
            "/companies/preview",
            json={"website_url": "https://official.example"},
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json["fields"]["name"], "Empresa desde sitio")
        self.assertEqual(self.mongo_client.database.collection.documents, [])

        created = self.client.post(
            "/companies",
            data={
                "name": "Empresa desde sitio",
                "address": "",
                "category": "",
                "products": "Descripción corregida manualmente.",
                "contact": "",
                "website_url": "https://official.example/",
                "image_url": "",
            },
        )
        self.assertEqual(created.status_code, 302)
        company = self.mongo_client.database.collection.documents[0]
        self.assertEqual(company["products"], "Descripción corregida manualmente.")
        self.assertEqual(
            company["scraping_metadata"]["fields_populated"],
            ["name", "website_url"],
        )
        self.assertEqual(
            company["scraping_metadata"]["source_urls"],
            ["https://official.example/"],
        )

    @patch("app.routes.scrape_website", side_effect=ScrapeError("Dominio local bloqueado."))
    def test_preview_reports_blocked_site_without_creating_company(self, _scrape):
        response = self.client.post(
            "/companies/preview",
            json={"website_url": "https://localhost"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Dominio local bloqueado.", response.json["error"])
        self.assertEqual(self.mongo_client.database.collection.documents, [])


if __name__ == "__main__":
    unittest.main()
