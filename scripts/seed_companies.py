from pymongo import MongoClient

from app import create_app


COMPANIES = [
    {
        "name": "CODALTEC",
        "address": "Av. 40 # 24A - 71",
        "category": "Simulación & Ciberseguridad",
        "products": "Soluciones de simulación y ciberseguridad.",
        "contact": "",
        "website_url": "",
        "image_url": "",
    },
    {
        "name": "SASOFTCO",
        "address": "Cra 44B # 18-43 Mz D Ca 15",
        "category": "ERP a Medida, Apps Mobile",
        "products": "Sistemas ERP a medida y aplicaciones móviles.",
        "contact": "",
        "website_url": "",
        "image_url": "",
    },
    {
        "name": "Ideas Software",
        "address": "Villavicencio, Meta",
        "category": "Sistemas Administrativos",
        "products": "Soluciones de software para gestión administrativa.",
        "contact": "",
        "website_url": "",
        "image_url": "",
    },
    {
        "name": "Pegasus Software",
        "address": "Cra 19A # 35A - 54",
        "category": "Contabilidad & Facturación POS",
        "products": "Software contable y soluciones de facturación POS.",
        "contact": "",
        "website_url": "",
        "image_url": "",
    },
    {
        "name": "Seobyte",
        "address": "Villavicencio, Meta, Colombia",
        "category": "Agencia Digital & Software",
        "products": "Desarrollo de portales web interactivos, plataformas de comercio electrónico (E-commerce), aplicaciones a medida e integración con servicios cloud.",
        "contact": "+57 310 550 7137 (WhatsApp)",
        "website_url": "https://seobyte.co",
        "image_url": "",
    },
    {
        "name": "Software & Apps Col",
        "address": "Cr 19B # 22-03 Macarena",
        "category": "Apps Móviles & Web",
        "products": "Desarrollo de aplicaciones móviles y web.",
        "contact": "",
        "website_url": "",
        "image_url": "",
    },
    {
        "name": "SPS Solutions",
        "address": "Calle 4A # 17-88 Vizcaya",
        "category": "Infraestructura TI & Web",
        "products": "Servicios de infraestructura TI y soluciones web.",
        "contact": "",
        "website_url": "",
        "image_url": "",
    },
    {
        "name": "Ingesoft Orinoquía",
        "address": "Calle 33A # 38-25 Barzal",
        "category": "ERP & Nómina Electrónica",
        "products": "Soluciones ERP y gestión de nómina electrónica.",
        "contact": "",
        "website_url": "",
        "image_url": "",
    },
    {
        "name": "Svenergia Tech",
        "address": "Cra 39 # 26C-12 7 de Agosto",
        "category": "E-learning & EdTech",
        "products": "Tecnología para educación digital y e-learning.",
        "contact": "",
        "website_url": "",
        "image_url": "",
    },
    {
        "name": "SoftLlanos",
        "address": "Calle 15 # 40-08 Camoa",
        "category": "POS & Inventarios",
        "products": "Sistemas POS y control de inventarios.",
        "contact": "",
        "website_url": "",
        "image_url": "",
    },
    {
        "name": "Llanotec",
        "address": "Av. Circunvalar # 35-10",
        "category": "Software Médico & Salud",
        "products": "Soluciones de software para el sector salud.",
        "contact": "",
        "website_url": "",
        "image_url": "",
    },
    {
        "name": "AgroSoft Meta",
        "address": "Calle 26 Sur # 48-12",
        "category": "Software Agrícola & Ganadero",
        "products": "Herramientas digitales para los sectores agrícola y ganadero.",
        "contact": "",
        "website_url": "",
        "image_url": "",
    },
    {
        "name": "MetaDevs Lab",
        "address": "Cra 38 # 33B-15 Barzal",
        "category": "APIs, Cloud & SaaS",
        "products": "Desarrollo de APIs, soluciones cloud y productos SaaS.",
        "contact": "",
        "website_url": "",
        "image_url": "",
    },
    {
        "name": "Global Code",
        "address": "Calle 15 # 37E-22 Esperanza",
        "category": "E-commerce B2B / B2C",
        "products": "Soluciones de comercio electrónico para negocios B2B y B2C.",
        "contact": "",
        "website_url": "",
        "image_url": "",
    },
    {
        "name": "InnovaApp Tech",
        "address": "Cra 40 # 20-55 Centauros",
        "category": "Apps de Logística & Domicilios",
        "products": "Aplicaciones móviles para logística y domicilios.",
        "contact": "",
        "website_url": "",
        "image_url": "",
    },
]


def main():
    app = create_app()
    client = app.extensions["mongo_client"]
    collection = app.extensions["companies_collection"]
    try:
        client.admin.command("ping")
        for company in COMPANIES:
            collection.update_one(
                {"name": company["name"]},
                {"$setOnInsert": company},
                upsert=True,
            )
        print(f"Datos iniciales listos: {len(COMPANIES)} empresas procesadas.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
