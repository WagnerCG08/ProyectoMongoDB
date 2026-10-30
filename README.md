# Directorio MetaTech

Aplicación local para consultar casas desarrolladoras de software en MongoDB. Incluye búsqueda por nombre parcial, fichas de empresa y operaciones CRUD. La imagen de cada ficha enlaza al sitio oficial cuando ese enlace está registrado.

## Requisitos

- Python 3.10 o superior.
- MongoDB Community Server instalado y ejecutándose en el equipo.

La aplicación usa por defecto `mongodb://127.0.0.1:27017` y la base de datos `directorio_desarrolladoras`. Puedes sobrescribirlos con `MONGO_URI` y `MONGO_DATABASE`.

## Instalación en Windows (PowerShell)

Desde la carpeta del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Inicia el servicio MongoDB Community desde **Servicios** de Windows (el nombre suele ser `MongoDB`), o inicia `mongod` con la ruta de datos configurada en tu instalación. Después carga los registros de ejemplo:

```powershell
python -m scripts.seed_companies
```

La carga inicial agrega las 15 empresas de las imágenes y puede repetirse sin duplicarlas. Los sitios oficiales, contactos e imágenes que no aparecen en la información proporcionada se dejan vacíos para completar desde la interfaz; no se inventan enlaces.

Inicia la aplicación:

```powershell
$env:SECRET_KEY = "cambia-esta-clave-local"
python run.py
```

Abre [http://127.0.0.1:5000](http://127.0.0.1:5000). La aplicación escucha solo en la interfaz local. Puedes buscar por nombre completo o parcial, abrir una ficha y crear, editar o eliminar registros.

Para usar otra instancia local:

```powershell
$env:MONGO_URI = "mongodb://127.0.0.1:27017"
$env:MONGO_DATABASE = "directorio_desarrolladoras"
```

En cada ficha puedes guardar la URL del sitio oficial y una URL de imagen/logo. La imagen mostrada se puede pulsar para abrir el sitio oficial en otra pestaña. Las direcciones web deben usar `http://` o `https://`.

## Pruebas

```powershell
python -m unittest discover -s tests -v
```

Las pruebas usan una colección simulada y no necesitan que MongoDB esté iniciado.

## Scraping

La carga inicial toma los datos visibles en las imágenes de referencia. El script `scripts/scrape_company_sites.py` consulta únicamente los sitios oficiales confirmados de CODALTEC, SASOFTCO, Ideas Software y Seobyte. Revisa `robots.txt`, consulta las páginas secuencialmente y guarda la URL de origen y la fecha de consulta en `scraping_metadata`.

También puedes agregar una empresa desde la interfaz: ingresa la URL **HTTPS** en el formulario y pulsa **Consultar sitio y completar ficha**. La aplicación propone el nombre, la descripción, el teléfono publicado y la imagen Open Graph si puede verificarlos en la página. Revisa y edita los campos antes de pulsar **Crear empresa**; los datos solo se guardan al enviar ese formulario. Los campos que el sitio no publica se dejan para completar manualmente.

La consulta de URL ingresadas está limitada a HTTPS en el puerto estándar, comprueba que el dominio resuelva únicamente a direcciones públicas y fija la conexión a una de esas IP para evitar cambios de DNS entre la validación y la conexión. También vuelve a validar cada redirección, bloquea redirecciones a otro host o a rutas no permitidas por `robots.txt` y limita el tamaño de respuesta. No se envían formularios al sitio.

Las imágenes de las fichas se sirven mediante una ruta segura de la aplicación para evitar problemas de carga directa desde sitios externos. Se aceptan solo JPEG, PNG, WebP y GIF públicos de hasta 5 MB; si una imagen no está disponible, se muestra la imagen local de reemplazo. El archivo remoto no se almacena en el proyecto.

Primero genera una vista previa sin escribir en MongoDB:

```powershell
python -m scripts.scrape_company_sites
```

Revisa los valores obtenidos y las fuentes impresas. Para aplicar los resultados:

```powershell
python -m scripts.scrape_company_sites --apply
```

El script de carga para empresas existentes solo completa campos vacíos; no reemplaza información ya registrada. El flujo de la interfaz permite crear un registro nuevo luego de revisar la vista previa. Ninguno de los dos métodos visita buscadores o directorios ni evita controles de acceso.
