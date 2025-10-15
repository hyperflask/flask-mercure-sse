from flask import Flask, request
from dotenv import load_dotenv
import secrets
import os
from flask_mercure_sse import MercureSSE


def create_app(publisher_secret=None, subscriber_secret=None, allow_anonymous=True, cors_origins="*", subscriptions=True):
    app = Flask(__name__)

    load_dotenv()
    if "FLASK_SECRET_KEY" in os.environ:
        app.config["SECRET_KEY"] = os.environ["FLASK_SECRET_KEY"]
    for k, v in os.environ.items():
        if k.startswith("MERCURE_"):
            app.config[k] = v

    mercure = MercureSSE(app, hub=True, publisher_secret_key=publisher_secret, subscriber_secret_key=subscriber_secret,
               hub_allow_publish=True, hub_allow_anonymous=allow_anonymous, hub_subscriptions=subscriptions)
    
    if not mercure.state.publisher_secret_key:
        mercure.state.publisher_secret_key = secrets.token_urlsafe(32)
        mercure.state.publisher_jwt = mercure.create_jwt("publisher_secret_key", publish=["*"])
        print(f"Generated publisher secret key: {mercure.state.publisher_secret_key}")
    
    if not mercure.state.subscriber_secret_key:
        mercure.state.subscriber_secret_key = secrets.token_urlsafe(32)
        print(f"Generated subscriber secret key: {mercure.state.subscriber_secret_key}")

    print(f"Publisher JWT: {mercure.state.publisher_jwt}")

    @app.after_request
    def after_request(response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*") if cors_origins == "*" else cors_origins
        response.headers["Access-Control-Allow-Credentials"] = "true"
        return response

    return app
