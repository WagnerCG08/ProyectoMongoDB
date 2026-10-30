import os
import secrets

from flask import Flask, render_template
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from app.routes import bp


def create_app(test_config=None, mongo_client=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        MONGO_URI=os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017"),
        MONGO_DATABASE=os.environ.get("MONGO_DATABASE", "directorio_desarrolladoras"),
        MONGO_CONNECT_TIMEOUT_MS=2000,
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    if mongo_client is None:
        mongo_client = MongoClient(
            app.config["MONGO_URI"],
            serverSelectionTimeoutMS=app.config["MONGO_CONNECT_TIMEOUT_MS"],
        )

    app.extensions["mongo_client"] = mongo_client
    app.extensions["companies_collection"] = mongo_client[
        app.config["MONGO_DATABASE"]
    ]["companies"]
    app.register_blueprint(bp)

    @app.errorhandler(PyMongoError)
    def handle_database_error(_error):
        return render_template("database_error.html"), 503

    return app
