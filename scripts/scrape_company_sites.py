import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.robotparser
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

from app import create_app


USER_AGENT = "MetaTechDirectoryResearch/1.0 (educational directory)"
REQUEST_DELAY_SECONDS = 1.5
MAX_PAGE_BYTES = 2_000_000
_LAST_REQUEST_TIME = 0.0
_ROBOTS_CACHE = {}
COMPANY_SITES = {
    "CODALTEC": {
        "website_url": "https://codaltec.com/",
        "pages": (
            "https://codaltec.com/",
            "https://codaltec.com/puntos-de-atencion-al-ciudadano/",
        ),
    },
    "SASOFTCO": {
        "website_url": "https://sasoftco.com/",
        "pages": (
            "https://sasoftco.com/",
            "https://sasoftco.com/ubicacion-villavicencio/",
        ),
    },
    "Ideas Software": {
        "website_url": "https://ideasw.co/web/",
        "pages": ("https://ideasw.co/web/",),
    },
    "Seobyte": {
        "website_url": "https://seobyte.co/",
        "pages": ("https://seobyte.co/",),
    },
}


class CompanyPageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.metadata = {}
        self.images = []
        self.contacts = []
        self.text_parts = []
        self.content_blocks = []
        self._block_tag = None
        self._block_parts = []
        self._ignored_depth = 0
        self._inside_title = False
        self.title_parts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in ("script", "style", "noscript", "svg"):
            self._ignored_depth += 1
        if tag == "title":
            self._inside_title = True
        if tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            value = attributes.get("content")
            if key and value:
                self.metadata[key.lower()] = value.strip()
        if tag == "img" and attributes.get("src"):
            self.images.append(attributes["src"].strip())
        if tag == "a":
            href = attributes.get("href", "").strip()
            if href.lower().startswith(("tel:", "mailto:")):
                self.contacts.append(href)
        if tag in ("p", "h1", "h2", "h3", "address") and self._block_tag is None:
            self._block_tag = tag
            self._block_parts = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "title":
            self._inside_title = False
        if tag == self._block_tag and self._block_tag is not None:
            block = " ".join(self._block_parts).strip()
            if block:
                self.content_blocks.append(block)
            self._block_tag = None
            self._block_parts = []

    def handle_data(self, data):
        if self._ignored_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._inside_title:
            self.title_parts.append(text)
        self.text_parts.append(text)
        if self._block_tag is not None:
            self._block_parts.append(text)


def _read_response(url):
    global _LAST_REQUEST_TIME
    elapsed = time.monotonic() - _LAST_REQUEST_TIME
    if elapsed < REQUEST_DELAY_SECONDS:
        time.sleep(REQUEST_DELAY_SECONDS - elapsed)
    _LAST_REQUEST_TIME = time.monotonic()
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        final_url = response.geturl()
        if urllib.parse.urlsplit(final_url).hostname != urllib.parse.urlsplit(url).hostname:
            raise RuntimeError(f"El sitio redirigió fuera del dominio esperado: {url}")
        content_type = response.headers.get_content_type()
        if content_type not in ("text/html", "application/xhtml+xml", "text/plain"):
            raise RuntimeError(f"Tipo de contenido no esperado en {url}: {content_type}")
        body = response.read(MAX_PAGE_BYTES + 1)
        if len(body) > MAX_PAGE_BYTES:
            raise RuntimeError(f"La página supera el límite de {MAX_PAGE_BYTES} bytes: {url}")
        charset = response.headers.get_content_charset() or "utf-8"
        return final_url, body.decode(charset, errors="replace")


def _robots_allows(url):
    parsed_url = urllib.parse.urlsplit(url)
    origin = urllib.parse.urlunsplit((parsed_url.scheme, parsed_url.netloc, "", "", ""))
    cached = _ROBOTS_CACHE.get(origin)
    if cached is not None:
        parser, note = cached
        allowed = parser.can_fetch(USER_AGENT, url) if parser else True
        return allowed, note if allowed else "bloqueado por robots.txt"

    robots_url = urllib.parse.urljoin(origin, "/robots.txt")
    parser = urllib.robotparser.RobotFileParser()
    try:
        _final_url, text = _read_response(robots_url)
    except urllib.error.HTTPError as error:
        if 400 <= error.code < 500:
            note = f"robots.txt no disponible (HTTP {error.code})"
            _ROBOTS_CACHE[origin] = (None, note)
            return True, note
        raise RuntimeError(f"No se pudo comprobar robots.txt de {robots_url}: {error}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"No se pudo comprobar robots.txt de {robots_url}: {error}") from error

    parser.set_url(robots_url)
    parser.parse(text.splitlines())
    allowed = parser.can_fetch(USER_AGENT, url)
    note = "permitido por robots.txt"
    _ROBOTS_CACHE[origin] = (parser, note)
    return allowed, note if allowed else "bloqueado por robots.txt"


def _parse_page(url):
    final_url, html = _read_response(url)
    parser = CompanyPageParser()
    parser.feed(html)
    return {
        "url": final_url,
        "metadata": parser.metadata,
        "title": " ".join(parser.title_parts).strip(),
        "images": parser.images,
        "contacts": parser.contacts,
        "text": " ".join(parser.text_parts),
        "content_blocks": parser.content_blocks,
    }


def _unique(values):
    return list(dict.fromkeys(value for value in values if value))


def _contact_values(pages):
    phones = []
    emails = []
    for page in pages:
        for contact in page["contacts"]:
            value = urllib.parse.unquote(contact.split(":", 1)[1]).strip()
            if contact.lower().startswith("tel:"):
                normalized_phone = _normalize_phone(value)
                if normalized_phone:
                    phones.append(normalized_phone)
            elif contact.lower().startswith("mailto:"):
                email = value.split("?", 1)[0]
                if email and not re.search(r"example|youurmail|yourmail", email, re.I):
                    emails.append(email)
    return _unique(phones), _unique(emails)


def _normalize_phone(value):
    digits = re.sub(r"\D", "", value)
    if len(digits) == 10:
        return f"+57{digits}"
    if len(digits) == 12 and digits.startswith("57"):
        return f"+{digits}"
    return ""


def _image_url(pages):
    for page in pages:
        for key in ("og:image", "twitter:image"):
            image = page["metadata"].get(key)
            if image:
                candidate = urllib.parse.urljoin(page["url"], image)
                if _same_site(candidate, page["url"]):
                    return candidate

    for page in pages:
        for image in page["images"]:
            candidate = urllib.parse.urljoin(page["url"], image)
            image_name = image.lower()
            if any(name in image_name for name in ("logo", "isotipo")) and _same_site(
                candidate, page["url"]
            ):
                return candidate
    return ""


def _same_site(candidate, source):
    candidate_url = urllib.parse.urlsplit(candidate)
    source_url = urllib.parse.urlsplit(source)
    candidate_host = (candidate_url.hostname or "").removeprefix("www.")
    source_host = (source_url.hostname or "").removeprefix("www.")
    return (
        candidate_url.scheme == "https"
        and candidate_host == source_host
        and candidate_url.username is None
        and candidate_url.password is None
    )


def _candidate_address(pages):
    for page in pages:
        if not re.search(r"\bVillavicencio\b", page["text"], flags=re.IGNORECASE):
            continue
        for block in page["content_blocks"]:
            match = re.search(
                r"(?:Direcci[oó]n)\s*:\s*(.{8,120}?)"
                r"(?=\s+(?:Tel[eé]fono|Celular|WhatsApp|Correo|Email)\b|$)",
                block,
                flags=re.IGNORECASE,
            )
            if match:
                return match.group(1).strip()
    return ""


def _products_description(pages):
    for page in pages:
        description = (
            page["metadata"].get("og:description")
            or page["metadata"].get("description")
            or page["metadata"].get("twitter:description")
            or ""
        ).strip()
        if len(description) > 40 and description.lower() not in (
            page["title"].lower(),
            "sitio web ideas software ltda",
        ) and not re.search(
            r"encu[eé]ntra|direcci[oó]n|visita la sede|ubicaci[oó]n",
            description,
            flags=re.IGNORECASE,
        ):
            return description

    for page in pages:
        for block in page["content_blocks"]:
            if (
                40 <= len(block) <= 500
                and block != block.upper()
                and not re.search(
                    r"(?:south america software company|sasoftco|ideas software ltda)",
                    block,
                    flags=re.IGNORECASE,
                )
                and re.search(
                    r"(?:desarrollo|desarrollamos|software|soluciones|tecnolog[ií]a)",
                    block,
                    flags=re.IGNORECASE,
                )
                and not re.search(
                    r"(?:men[uú]|privacidad|cookies|derechos reservados)",
                    block,
                    flags=re.IGNORECASE,
                )
            ):
                return block
    return ""


def scrape_company(company_name, source):
    pages = []
    robots_checks = []
    for index, url in enumerate(source["pages"]):
        allowed, note = _robots_allows(url)
        robots_checks.append({"url": url, "result": note})
        if not allowed:
            continue
        if index:
            time.sleep(REQUEST_DELAY_SECONDS)
        pages.append(_parse_page(url))

    if not pages:
        raise RuntimeError(f"No se pudo consultar ninguna página autorizada de {company_name}.")

    phones, emails = _contact_values(pages)
    for page in pages:
        labeled_phones = re.findall(
            r"(?:Tel[eé]fono|Celular|WhatsApp|L[ií]nea)\s*(?:M[oó]vil)?\s*:\s*"
            r"(\(?\+?\d[\d\s().-]{6,20})",
            page["text"],
            flags=re.IGNORECASE,
        )
        phones.extend(
            normalized_phone
            for value in labeled_phones
            if (normalized_phone := _normalize_phone(value))
        )
    phones = _unique(phones)
    candidate = {
        "website_url": source["website_url"],
        "address": _candidate_address(pages),
        "contact": "; ".join(phones),
        "image_url": _image_url(pages),
        "products": _products_description(pages),
    }
    return {
        "company": company_name,
        "source_urls": [page["url"] for page in pages],
        "robots_checks": robots_checks,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "candidate_fields": {
            key: value for key, value in candidate.items() if value
        },
        "contact_emails_not_stored": emails,
    }


def _proposed_updates(current, scraped):
    updates = {}
    for field, value in scraped["candidate_fields"].items():
        existing_value = current.get(field)
        if value and not (isinstance(existing_value, str) and existing_value.strip()):
            updates[field] = value
    if updates:
        updates["scraping_metadata"] = {
            "source_urls": scraped["source_urls"],
            "fetched_at": scraped["fetched_at"],
            "fields_populated": sorted(
                field for field in updates if field != "scraping_metadata"
            ),
        }
    return updates


def build_preview(collection):
    preview = []
    for name, source in COMPANY_SITES.items():
        scraped = scrape_company(name, source)
        current = collection.find_one({"name": name})
        if current is None:
            raise RuntimeError(
                f"No existe el registro '{name}' en MongoDB; no se creará uno automáticamente."
            )
        preview.append(
            {
                **scraped,
                "current_fields": {
                    field: current.get(field, "")
                    for field in ("address", "contact", "category", "products", "website_url", "image_url")
                },
                "proposed_updates": _proposed_updates(current, scraped),
            }
        )
    return preview


def apply_preview(collection, preview):
    for item in preview:
        updates = item["proposed_updates"]
        if not updates:
            continue
        update_fields = {
            field: value
            for field, value in updates.items()
            if field != "scraping_metadata"
        }
        update_fields["scraping_metadata"] = updates["scraping_metadata"]
        result = collection.update_one(
            {
                "name": item["company"],
                "$and": [
                    {
                        "$or": [
                            {field: {"$exists": False}},
                            {field: ""},
                            {field: None},
                        ]
                    }
                    for field in update_fields
                    if field != "scraping_metadata"
                ],
            },
            {"$set": update_fields},
        )
        if result.matched_count != 1:
            raise RuntimeError(
                f"El registro '{item['company']}' cambió durante la vista previa; "
                "no se aplicaron sus datos."
            )


def main():
    argument_parser = argparse.ArgumentParser(
        description="Extrae datos públicos de sitios oficiales verificados."
    )
    argument_parser.add_argument(
        "--apply",
        action="store_true",
        help="Guarda en MongoDB únicamente los campos que siguen vacíos.",
    )
    args = argument_parser.parse_args()

    app = create_app()
    client = app.extensions["mongo_client"]
    collection = app.extensions["companies_collection"]
    try:
        client.admin.command("ping")
        preview = build_preview(collection)
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        if args.apply:
            apply_preview(collection, preview)
            print("Actualización aplicada solo a campos vacíos.")
        else:
            print("Vista previa solamente; MongoDB no fue modificado.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
