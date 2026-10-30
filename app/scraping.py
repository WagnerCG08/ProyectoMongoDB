import http.client
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.robotparser
import urllib.request
from html.parser import HTMLParser


USER_AGENT = "MetaTechDirectory/1.0 (educational company directory)"
MAX_URL_LENGTH = 2048
MAX_PAGE_BYTES = 1_000_000
MAX_IMAGE_BYTES = 5_000_000
TIMEOUT_SECONDS = 10
REDIRECT_LIMIT = 3


class ScrapeError(ValueError):
    pass


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, pinned_address, **kwargs):
        super().__init__(host, **kwargs)
        self.pinned_address = pinned_address

    def connect(self):
        self.sock = socket.create_connection(
            (self.pinned_address, self.port),
            self.timeout,
            self.source_address,
        )
        if self._tunnel_host:
            self._tunnel()
            server_hostname = self._tunnel_host
        else:
            server_hostname = self.host
        self.sock = self._context.wrap_socket(
            self.sock,
            server_hostname=server_hostname,
        )


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, request):
        _parsed, pinned_address = _validate_public_https_url(request.full_url)
        return self.do_open(
            lambda host, **kwargs: _PinnedHTTPSConnection(
                host,
                pinned_address,
                **kwargs,
            ),
            request,
            context=self._context,
        )


class _CompanyPageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.metadata = {}
        self.title_parts = []
        self.text_parts = []
        self.phones = []
        self.images = []
        self._inside_title = False
        self._ignored_depth = 0

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
        if tag == "a":
            href = attributes.get("href", "").strip()
            if href.lower().startswith("tel:"):
                self.phones.append(urllib.parse.unquote(href[4:]).strip())
        if tag == "img" and attributes.get("src"):
            self.images.append(attributes["src"].strip())

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "title":
            self._inside_title = False

    def handle_data(self, data):
        if self._ignored_depth:
            return
        text = " ".join(data.split())
        if text:
            self.text_parts.append(text)
            if self._inside_title:
                self.title_parts.append(text)


def _normalized_host(host):
    return (host or "").rstrip(".").lower()


def _validate_public_https_url(url):
    if not isinstance(url, str) or not url or len(url) > MAX_URL_LENGTH:
        raise ScrapeError("Ingresa una URL HTTPS válida (máximo 2048 caracteres).")

    try:
        parsed = urllib.parse.urlsplit(url.strip())
        port = parsed.port
    except ValueError as error:
        raise ScrapeError("La URL no tiene un formato válido.") from error

    hostname = parsed.hostname
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment
    ):
        raise ScrapeError("Solo se permiten direcciones HTTPS públicas en el puerto estándar.")

    hostname = hostname.lower()
    if (
        hostname == "localhost"
        or hostname.endswith((".localhost", ".local", ".internal", ".test", ".invalid"))
    ):
        raise ScrapeError("No se permiten direcciones locales o internas.")

    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ScrapeError("Ingresa el dominio del sitio, no una dirección IP.")

    try:
        addresses = socket.getaddrinfo(
            hostname,
            443,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as error:
        raise ScrapeError("No fue posible resolver el dominio ingresado.") from error

    resolved_ips = [entry[4][0].split("%", 1)[0] for entry in addresses]
    if not resolved_ips or any(
        not ipaddress.ip_address(address).is_global for address in resolved_ips
    ):
        raise ScrapeError("El dominio debe resolver únicamente a direcciones IP públicas.")

    return parsed, resolved_ips[0]


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, initial_host, robots_parser=None):
        super().__init__()
        self.initial_host = _normalized_host(initial_host)
        self.robots_parser = robots_parser
        self.max_repeats = REDIRECT_LIMIT
        self.max_redirections = REDIRECT_LIMIT

    def redirect_request(self, request, response, code, message, headers, new_url):
        parsed, _pinned_address = _validate_public_https_url(new_url)
        if _normalized_host(parsed.hostname) != self.initial_host:
            raise ScrapeError("Se bloqueó una redirección a otro dominio.")
        if self.robots_parser and not self.robots_parser.can_fetch(
            USER_AGENT, new_url
        ):
            raise ScrapeError("El sitio bloquea la página de destino según robots.txt.")
        return super().redirect_request(
            request, response, code, message, headers, new_url
        )


def _open_public_url(url, robots_parser=None):
    parsed, _pinned_address = _validate_public_https_url(url)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _SafeRedirectHandler(parsed.hostname, robots_parser),
        _PinnedHTTPSHandler(),
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    try:
        response = opener.open(request, timeout=TIMEOUT_SECONDS)
    except urllib.error.HTTPError:
        raise
    except ScrapeError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ScrapeError("No se pudo consultar la página. Verifica la URL e inténtalo de nuevo.") from error

    final_url = response.geturl()
    final_parsed, _pinned_address = _validate_public_https_url(final_url)
    if _normalized_host(final_parsed.hostname) != _normalized_host(parsed.hostname):
        response.close()
        raise ScrapeError("Se bloqueó una redirección a otro dominio.")
    return response, final_url


def fetch_public_image(url):
    parsed, _pinned_address = _validate_public_https_url(url)
    robots_parser = _read_robots(url)
    if robots_parser and not robots_parser.can_fetch(USER_AGENT, url):
        raise ScrapeError("El sitio no permite consultar la imagen según robots.txt.")

    try:
        response, _final_url = _open_public_url(url, robots_parser)
    except urllib.error.HTTPError as error:
        raise ScrapeError(f"El sitio respondió con el estado HTTP {error.code}.") from error

    with response:
        content_type = response.headers.get_content_type()
        if content_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            raise ScrapeError("El recurso no es una imagen JPEG, PNG, WebP o GIF.")
        try:
            body = response.read(MAX_IMAGE_BYTES + 1)
        except (OSError, TimeoutError) as error:
            raise ScrapeError("La conexión se interrumpió al cargar la imagen.") from error
        if len(body) > MAX_IMAGE_BYTES:
            raise ScrapeError("La imagen supera el tamaño máximo permitido.")
        if not body:
            raise ScrapeError("El servidor devolvió una imagen vacía.")
        return body, content_type


def _read_page(url, *, robots=False, robots_parser=None):
    try:
        response, final_url = _open_public_url(url, robots_parser)
    except urllib.error.HTTPError as error:
        if robots and error.code in (404, 410):
            raise
        raise ScrapeError(f"El sitio respondió con el estado HTTP {error.code}.") from error

    with response:
        content_type = response.headers.get_content_type()
        if robots:
            if content_type not in ("text/plain", "application/octet-stream"):
                raise ScrapeError("El archivo robots.txt no tiene un formato válido.")
            limit = 512_000
        else:
            if content_type not in ("text/html", "application/xhtml+xml"):
                raise ScrapeError("La URL no corresponde a una página HTML.")
            limit = MAX_PAGE_BYTES
        try:
            body = response.read(limit + 1)
        except (OSError, TimeoutError) as error:
            raise ScrapeError("La conexión se interrumpió al leer la página.") from error
        if len(body) > limit:
            raise ScrapeError("La página supera el tamaño máximo permitido.")
        charset = response.headers.get_content_charset() or "utf-8"
        try:
            text = body.decode(charset, errors="replace")
        except LookupError as error:
            raise ScrapeError("La página declara una codificación no compatible.") from error
        return final_url, text


def _read_robots(url):
    parsed = urllib.parse.urlsplit(url)
    robots_url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, "/robots.txt", "", "")
    )
    parser = urllib.robotparser.RobotFileParser()
    try:
        final_url, text = _read_page(robots_url, robots=True)
    except urllib.error.HTTPError as error:
        if error.code in (404, 410):
            return None
        raise ScrapeError("No se pudieron comprobar las reglas del sitio (robots.txt).") from error

    if _normalized_host(urllib.parse.urlsplit(final_url).hostname) != _normalized_host(
        parsed.hostname
    ):
        raise ScrapeError("El archivo robots.txt redirige a otro dominio.")
    parser.set_url(robots_url)
    parser.parse(text.splitlines())
    return parser


def _normalize_phone(phone):
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        return f"+57{digits}"
    if len(digits) == 12 and digits.startswith("57"):
        return f"+{digits}"
    return ""


def _site_name(parser, hostname):
    name = (
        parser.metadata.get("og:site_name")
        or parser.metadata.get("application-name")
        or parser.metadata.get("og:title")
        or " ".join(parser.title_parts)
    ).strip()
    if not name:
        return hostname.removeprefix("www.").split(".")[0].replace("-", " ").title()
    name = re.split(r"\s+[|–—]\s+|\s+::\s+", name, maxsplit=1)[0].strip()
    return name[:120]


def _source_reference(url):
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path or "/", "", "")
    )


def scrape_website(url):
    parsed, _pinned_address = _validate_public_https_url(url)
    normalized_url = urllib.parse.urlunsplit(
        (
            "https",
            parsed.netloc,
            parsed.path or "/",
            parsed.query,
            "",
        )
    )
    robots_parser = _read_robots(normalized_url)
    if robots_parser and not robots_parser.can_fetch(USER_AGENT, normalized_url):
        raise ScrapeError("El sitio no permite consultar esta página según robots.txt.")

    final_url, html = _read_page(
        normalized_url,
        robots_parser=robots_parser,
    )
    parser = _CompanyPageParser()
    parser.feed(html)

    fields = {
        "name": _site_name(parser, parsed.hostname),
        "website_url": urllib.parse.urlunsplit(
            ("https", parsed.netloc, "/", "", "")
        ),
    }

    description = (
        parser.metadata.get("og:description")
        or parser.metadata.get("description")
        or parser.metadata.get("twitter:description")
        or ""
    ).strip()
    if description:
        fields["products"] = description[:1000]

    phone_values = list(dict.fromkeys(
        phone for item in parser.phones if (phone := _normalize_phone(item))
    ))
    if phone_values:
        fields["contact"] = "; ".join(phone_values)

    source_host = _normalized_host(urllib.parse.urlsplit(final_url).hostname)
    image = parser.metadata.get("og:image") or parser.metadata.get("twitter:image")
    if image:
        image_url = urllib.parse.urljoin(final_url, image)
        image_parsed = urllib.parse.urlsplit(image_url)
        if (
            image_parsed.scheme == "https"
            and _normalized_host(image_parsed.hostname) == source_host
            and image_parsed.username is None
            and image_parsed.password is None
        ):
            fields["image_url"] = image_url

    fields = {key: value for key, value in fields.items() if value}
    return {
        "fields": fields,
        "source_url": _source_reference(final_url),
    }
