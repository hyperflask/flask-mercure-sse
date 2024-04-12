from .hub import Broker, hub_blueprint
from dataclasses import dataclass
from flask import current_app, url_for, session
from flask.cli import AppGroup
import typing as t
import requests
import jwt
import urllib.parse
import click


@dataclass
class MercureSSEState:
    instance: "MercureSSE"
    hub_url: str
    publisher_jwt: str
    authz_cookie_name: str
    hub_allow_publish: bool # whether to allow publishing via the built-in hub
    hub_allow_anonymous: bool # whether to allow anonymous subscribers on the built-in hub
    subscriber_secret_key: t.Optional[str] = None
    publisher_secret_key: t.Optional[str] = None
    broker: t.Optional[Broker] = None


class MercureSSE:
    def __init__(self, app=None, **kwargs):
        if app:
            self.init_app(app, **kwargs)

    def init_app(self, app, hub_url=None, publisher_jwt=None, subscriber_secret_key=None, publisher_secret_key=None,
                 hub_allow_publish=False, hub_allow_anonymous=True, authz_cookie_name="mercureAuthorization"):
        if not subscriber_secret_key:
            subscriber_secret_key = app.config["SECRET_KEY"]
        if not publisher_secret_key:
            publisher_secret_key = app.config["SECRET_KEY"]
        if not publisher_jwt and publisher_secret_key:
            publisher_jwt = jwt.encode({"mercure": {"publish": ["*"]}}, publisher_secret_key)

        self.app = app
        self.state = state = MercureSSEState(
            instance=self,
            hub_url=app.config.get("MERCURE_HUB_URL", hub_url),
            publisher_jwt=app.config.get("MERCURE_PUBLISHER_JWT", publisher_jwt),
            authz_cookie_name=app.config.get("MERCURE_AUTHZ_COOKIE_NAME", authz_cookie_name),
            hub_allow_publish=app.config.get("MERCURE_HUB_ALLOW_PUBLISH", hub_allow_publish),
            hub_allow_anonymous=app.config.get("MERCURE_HUB_ALLOW_ANONYMOUS", hub_allow_anonymous),
            subscriber_secret_key=app.config.get("MERCURE_SUBSCRIBER_SECRET_KEY", subscriber_secret_key),
            publisher_secret_key=app.config.get("MERCURE_PUBLISHER_SECRET_KEY", publisher_secret_key),
            broker=Broker() if not hub_url else None
        )

        app.extensions["mercure_sse"] = state
        app.jinja_env.globals.update(mercure_hub_url=mercure_hub_url,
                                     mercure_subscriber_jwt=self.create_subscription_jwt)
        if not hub_url:
            app.register_blueprint(hub_blueprint)

        cli = AppGroup("mercure", help="Mercure hub commands")

        @cli.command()
        @click.option("--topic", "-t", multiple=True, default=["*"])
        def subscriber_jwt(topic):
            """Generate a JWT for subscribing to topics"""
            print(self.create_subscription_jwt(topic))

        @cli.command()
        @click.option("--topic", "-t", multiple=True, default=["*"])
        def publisher_jwt(topic):
            """Generate a JWT for publishing"""
            print(self.create_jwt("publisher_secret_key", publish=topic))

        @cli.command()
        @click.option("--hub", help="Hub URL")
        @click.option("--jwt", help="Authorization JWT")
        @click.option("--private", is_flag=True)
        @click.option("--id")
        @click.option("--type")
        @click.option("--retry")
        @click.argument("topic")
        @click.argument("data")
        def publish(topic, data, private, id, type, retry, jwt=None, hub=None):
            print(self.publish(topic, data, private, id, type, retry, jwt, hub))

        app.cli.add_command(cli)

    def create_jwt(self, key, publish=None, subscribe=None):
        key = getattr(self.state, key)
        if not key:
            raise ValueError(f"Missing key {key}")
        return jwt.encode({"mercure": {"publish": publish, "subscribe": subscribe}}, key)
    
    def create_subscription_jwt(self, topics):
        return self.create_jwt("subscriber_secret_key", subscribe=topics)
    
    def set_authz_cookie(self, response, topics=None, jwt=None):
        if not jwt:
            jwt = self.create_subscription_jwt(topics or ["*"])

        if self.hub_url:
            path = self.hub_url
            secure = True
        else:
            path = "/.well-known/mercure"
            secure = not self.app.debug

        response.set_cookie(self.state.authz_cookie_name, jwt,
                            path=path, httponly=True, secure=secure, samesite="strict")
        return response
    
    def set_authz_session(self, subscribe=None, publish=None):
        session["mercure"] = {"subscribe": subscribe, "publish": publish}

    def publish(self, topic, data, private=False, id=None, type=None, retry=None, jwt=None, hub_url=None):
        if not hub_url:
            hub_url = self.state.hub_url
        if not jwt:
            jwt = self.state.publisher_jwt

        if not hub_url and self.state.broker:
            return self.state.broker.publish(topic, data, private, id, type, retry)
        
        data = {
            "topic": topic,
            "data": data
        }
        if private:
            data["private"] = "on"
        if id:
            data["id"] = id
        if type:
            data["type"] = type
        if retry:
            data["retry"] = retry
        
        r = requests.post(hub_url, data=data, headers={"Authorization": f"Bearer {jwt}"})
        return r.text
    

def mercure_hub_url(topics, subscriber_jwt=None):
    state = current_app.extensions["mercure_sse"]

    url = state.hub_url
    if not url:
        url = url_for("mercure_hub.subscribe")

    params = [("topic", topics)]
    if subscriber_jwt:
        params.append(("authorization", subscriber_jwt))

    return url + "?" + urllib.parse.urlencode(params, doseq=True)


def mercure_publish(topic, data, **kwargs):
    return current_app.extensions["mercure_sse"].instance.publish(topic, data, **kwargs)


def publish_signal(signal, topic=None, data=None, signal_name_as_type=False, signal_kwargs_as_data=False, marshaler=None, callback=None, **publish_kwargs):
    def listener(sender, **kwargs):
        _data = data
        if signal_kwargs_as_data:
            _data = dict(data or {}, **kwargs)
        publish_kwargs["topic"] = topic
        publish_kwargs["data"] = marshaler(_data) if marshaler else _data
        if signal_name_as_type:
            publish_kwargs["type"] = signal.name
        if hasattr(sender, "__mercure_publish__"):
            publish_kwargs.update(sender.__mercure_publish__)
        if callback:
            callback(publish_kwargs)
        if not publish_kwargs.get("topic"):
            publish_kwargs["topic"] = signal.name
        current_app.extensions["mercure_sse"].instance.publish(**publish_kwargs)

    signal.connect(listener, weak=False)


def publish_signal_in_topic(signal, topic=None, **kwargs):
    kwargs["signal_name_as_type"] = True
    return publish_signal(signal, topic, **kwargs)