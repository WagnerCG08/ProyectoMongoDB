import re
from io import BytesIO
from datetime import datetime, timezone
from urllib.parse import urlsplit

from bson import ObjectId
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    send_file,
    url_for,
)

from app.scraping import ScrapeError, fetch_public_image, scrape_website

bp = Blueprint("companies", __name__)

FORM_FIELDS = (
    ("name", "Nombre"),
    ("address", "Dirección"),
    ("category", "Categoría"),
    ("products", "Productos y servicios"),
    ("contact", "Teléfono o WhatsApp"),
    ("website_url", "Sitio web oficial"),
    ("image_url", "URL de imagen o logo"),
)


def _collection():
    return current_app.extensions["companies_collection"]


def _company_id(raw_id):
    if not ObjectId.is_valid(raw_id):
        abort(404)
    return ObjectId(raw_id)


def _company_form_data():
    data = {field: request.form.get(field, "").strip() for field, _label in FORM_FIELDS}
    errors = []

    if not data["name"]:
        errors.append("El nombre de la empresa es obligatorio.")

    for field, label in (("website_url", "sitio oficial"), ("image_url", "imagen o logo")):
        value = data[field]
        if value:
            try:
                parsed_url = urlsplit(value)
                _ = parsed_url.port
            except ValueError:
                errors.append(f"Ingresa una URL válida para el {label} (http o https).")
                continue
            if (
                parsed_url.scheme not in ("http", "https")
                or not parsed_url.hostname
                or parsed_url.username is not None
                or parsed_url.password is not None
            ):
                errors.append(f"Ingresa una URL válida para el {label} (http o https).")

    return data, errors


def _render_form(company=None, status=200):
    return (
        render_template(
            "company_form.html",
            company=company or {},
            fields=FORM_FIELDS,
            is_edit=company is not None,
        ),
        status,
    )


@bp.get("/")
def index():
    search = request.args.get("q", "").strip()[:100]
    query = {"name": {"$regex": re.escape(search), "$options": "i"}} if search else {}
    companies = list(_collection().find(query).sort("name", 1))
    return render_template("index.html", companies=companies, search=search)


@bp.get("/companies/new")
def new_company():
    session.pop("scrape_preview", None)
    return _render_form()


@bp.post("/companies/preview")
def preview_company():
    session.pop("scrape_preview", None)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "La solicitud no contiene una URL válida."}), 400

    website_url = payload.get("website_url")
    if not isinstance(website_url, str):
        return jsonify({"error": "Ingresa la URL HTTPS del sitio oficial."}), 400
    website_url = website_url.strip()
    try:
        preview = scrape_website(website_url)
    except ScrapeError as error:
        return jsonify({"error": str(error)}), 400

    session["scrape_preview"] = {
        "website_url": preview["fields"]["website_url"],
        "source_url": preview["source_url"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fields": preview["fields"],
    }
    return jsonify(preview)


@bp.post("/companies")
def create_company():
    company, errors = _company_form_data()
    if errors:
        for error in errors:
            flash(error, "error")
        return _render_form(company, 400)

    scrape_preview = session.pop("scrape_preview", None)
    if scrape_preview and scrape_preview["website_url"] == company["website_url"]:
        scraped_fields = scrape_preview["fields"]
        source_fields = sorted(
            field
            for field, value in scraped_fields.items()
            if company.get(field) == value
        )
        if source_fields:
            company["scraping_metadata"] = {
                "source_urls": [scrape_preview["source_url"]],
                "fetched_at": scrape_preview["fetched_at"],
                "fields_populated": source_fields,
            }

    result = _collection().insert_one(company)
    flash("La empresa se creó correctamente.", "success")
    return redirect(url_for("companies.detail", company_id=str(result.inserted_id)))


@bp.get("/companies/<company_id>")
def detail(company_id):
    company = _collection().find_one({"_id": _company_id(company_id)})
    if company is None:
        abort(404)
    return render_template("company_detail.html", company=company)


@bp.get("/companies/<company_id>/image")
def company_image(company_id):
    company = _collection().find_one({"_id": _company_id(company_id)})
    if company is None:
        abort(404)

    stored_image_url = company.get("image_url")
    image_url = stored_image_url.strip() if isinstance(stored_image_url, str) else ""
    if not image_url:
        return redirect(url_for("static", filename="img/company-placeholder.svg"))

    try:
        image_bytes, content_type = fetch_public_image(image_url)
    except ScrapeError as error:
        current_app.logger.warning(
            "No se pudo cargar la imagen de la empresa %s: %s",
            company.get("name", company_id),
            error,
        )
        return redirect(url_for("static", filename="img/company-placeholder.svg"))

    response = make_response(
        send_file(BytesIO(image_bytes), mimetype=content_type, conditional=True)
    )
    response.headers["Cache-Control"] = "public, max-age=3600"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.get("/companies/<company_id>/edit")
def edit_company(company_id):
    company = _collection().find_one({"_id": _company_id(company_id)})
    if company is None:
        abort(404)
    return _render_form(company)


@bp.post("/companies/<company_id>/edit")
def update_company(company_id):
    company_id = _company_id(company_id)
    existing_company = _collection().find_one({"_id": company_id})
    if existing_company is None:
        abort(404)

    company, errors = _company_form_data()
    if errors:
        company["_id"] = company_id
        for error in errors:
            flash(error, "error")
        return _render_form(company, 400)

    _collection().update_one({"_id": company_id}, {"$set": company})
    flash("Los datos de la empresa se actualizaron.", "success")
    return redirect(url_for("companies.detail", company_id=str(company_id)))


@bp.post("/companies/<company_id>/delete")
def delete_company(company_id):
    result = _collection().delete_one({"_id": _company_id(company_id)})
    if result.deleted_count == 0:
        abort(404)
    flash("La empresa se eliminó correctamente.", "success")
    return redirect(url_for("companies.index"))
