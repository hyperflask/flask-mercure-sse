from dataclasses import dataclass
from flask import current_app, json, request
import typing as t
import requests
import jwt
import urllib.parse
import os
from .hub import Hub, hub_blueprint, get_subscription_id, format_subscriptions_response
from .cli import cli


@dataclass
class MercureSSEState:
    instance: "MercureSSE"
    hub_url: str
    public_hub_url: t.Optional[str]
    publisher_jwt: str
    authz_cookie_name: str
    type_is_topic: bool
    hub_allow_publish: bool # whether to allow publishing via the built-in hub
    hub_allow_anonymous: bool # whether to allow anonymous subscribers on the built-in hub
    hub_subscriptions: bool # whether to enable the subscriptions api
    hub_keepalive_interval: int # in seconds, 0 to disable
    hub_reconciliation_length: int # in seconds, 0 to disable
    subscriber_secret_key: t.Optional[str]
    publisher_secret_key: t.Optional[str]


HUB_URL_FROM_REQUEST = True


class MercureSSE:
    def __init__(self, app=None, **kwargs):
        if app:
            self.init_app(app, **kwargs)

    def init_app(self, app, hub_url=None, public_hub_url=None, publisher_jwt=None, subscriber_secret_key=None, publisher_secret_key=None,
                 hub_allow_publish=False, hub_allow_anonymous=True, hub_subscriptions=True, hub_keepalive_interval=15,
                 hub_reconciliation_length=500, authz_cookie_name="mercureAuthorization", type_is_topic=False, hub=None):
        if not subscriber_secret_key:
            # env var compatible with official mercure hub
            subscriber_secret_key = os.environ.get("MERCURE_SUBSCRIBER_JWT_KEY", app.config["SECRET_KEY"])
        if not publisher_secret_key:
            # env var compatible with official mercure hub
            publisher_secret_key = os.environ.get("MERCURE_PUBLISHER_JWT_KEY", app.config["SECRET_KEY"])
        if not publisher_jwt and publisher_secret_key:
            publisher_jwt = jwt.encode({"mercure": {"publish": ["*"]}}, publisher_secret_key, algorithm="HS256")

        self.app = app
        self.state = state = MercureSSEState(
            instance=self,
            hub_url=app.config.get("MERCURE_HUB_URL", hub_url),
            public_hub_url=app.config.get("MERCURE_PUBLIC_HUB_URL", public_hub_url),
            publisher_jwt=app.config.get("MERCURE_PUBLISHER_JWT", publisher_jwt),
            authz_cookie_name=app.config.get("MERCURE_AUTHZ_COOKIE_NAME", authz_cookie_name),
            type_is_topic=app.config.get("MERCURE_TYPE_IS_TOPIC", type_is_topic),
            hub_allow_publish=app.config.get("MERCURE_HUB_ALLOW_PUBLISH", hub_allow_publish),
            hub_allow_anonymous=app.config.get("MERCURE_HUB_ALLOW_ANONYMOUS", hub_allow_anonymous),
            hub_subscriptions=app.config.get("MERCURE_HUB_SUBSCRIPTIONS", hub_subscriptions),
            hub_keepalive_interval=app.config.get("MERCURE_HUB_KEEPALIVE_INTERVAL", hub_keepalive_interval),
            hub_reconciliation_length=app.config.get("MERCURE_HUB_RECONCILIATION_LENGTH", hub_reconciliation_length),
            subscriber_secret_key=app.config.get("MERCURE_SUBSCRIBER_SECRET_KEY", subscriber_secret_key),
            publisher_secret_key=app.config.get("MERCURE_PUBLISHER_SECRET_KEY", publisher_secret_key)
        )
        self._payload_getter = None

        app.extensions["mercure_sse"] = state
        app.jinja_env.globals.update(mercure_hub_url=self.hub_url,
                                     mercure_authentified_hub_url=self.authentified_hub_url,
                                     mercure_subscriber_jwt=self.create_subscription_jwt,
                                     mercure_topic=as_topic,
                                     mercure_subscription_topic=get_subscription_id,
                                     mercure_subscriptions=lambda topic: self.get_subscriptions(topic)["subscriptions"])

        hub = app.config.get("MERCURE_HUB", hub)
        if hub is None:
            hub = app.debug or app.testing

        if not hub and not state.hub_url:
            state.hub_url = "http://localhost:5500/.well-known/mercure"
        
        self.hub = None
        if hub:
            self.hub = Hub(publish_subscriptions=state.hub_subscriptions,
                           reconciliation_length=state.hub_reconciliation_length,
                           logger=app.logger)
            app.register_blueprint(hub_blueprint)

        app.cli.add_command(cli)

    def payload_getter(slf, func):
        slf._payload_getter = func
        return func

    def create_jwt(self, key, **data):
        key = getattr(self.state, key)
        if not key:
            raise ValueError(f"Missing key {key}")
        return jwt.encode({"mercure": data}, key, algorithm="HS256")
    
    def create_subscription_jwt(self, topics, payload=None):
        if not isinstance(topics, (list, tuple)):
            topics = (topics,)
        data = {"subscribe": list(map(as_topic, topics))}
        if self._payload_getter:
            _payload = self._payload_getter(topics)
            if payload:
                payload = dict(_payload, **payload)
            else:
                payload = _payload
        if payload is not None:
            data["payload"] = payload
        return self.create_jwt("subscriber_secret_key", **data)

    def set_authz_cookie(self, response, topics=None, jwt=None, payload=None, secure=None, **kwargs):
        if not jwt:
            jwt = self.create_subscription_jwt(topics or ["*"], payload=payload)

        if self.state.hub_url:
            parts = urllib.parse.urlparse(self.state.hub_url)
            kwargs.setdefault("domain", parts.hostname)
            kwargs.setdefault("path", parts.path)
            secure = secure if secure is not None else parts.scheme == "https"
        else:
            kwargs.setdefault("path", "/.well-known/mercure")
            secure = secure if secure is not None else request.is_secure

        kwargs.setdefault("httponly", True)
        kwargs.setdefault("samesite", "strict")

        response.set_cookie(self.state.authz_cookie_name, jwt, secure=secure, **kwargs)
        return response
    
    def delete_authz_cookie(self, response):
        return self.set_authz_cookie(response, jwt="", expires=0)
    
    def hub_base_url(self, public=True):
        hub_url = self.state.public_hub_url if public and self.state.public_hub_url else self.state.hub_url
        if (self.hub and not hub_url) or hub_url == True:
            return request.host_url.rstrip("/") + "/.well-known/mercure"
        if not hub_url:
            raise Exception("No hub_url configured")
        return hub_url
    
    def hub_url(self, topics=None, subscriber_jwt=None, with_subscriptions=False, public=True):
        url = self.hub_base_url(public=public)
        params = []
        if topics:
            if not isinstance(topics, (list, tuple)):
                topics = (topics,)
            if with_subscriptions:
                topics = topics + [get_subscription_id(t) for t in topics]
            params.extend(("topic", as_topic(t)) for t in topics)
        if subscriber_jwt:
            params.append(("authorization", subscriber_jwt))
        return url + "?" + urllib.parse.urlencode(params, doseq=True)

    def authentified_hub_url(self, topics=None, payload=None, with_subscriptions=False):
        return self.hub_url(topics, self.create_subscription_jwt(topics or ["*"], payload=payload), with_subscriptions=with_subscriptions)

    def publish(self, topic, data=None, private=False, id=None, type=None, retry=None, jwt=None, hub_url=None):
        if not jwt:
            jwt = self.state.publisher_jwt

        if data is None:
            if hasattr(topic, "__mercure_sse__"):
                topic, data = topic.__mercure__()
            else:
                data = topic
                if not hasattr(topic, "__mercure_sse_topic__"):
                    topic = topic.__class__.__name__

        if hasattr(data, "__mercure_sse_data__"):
            data = data.__mercure_sse_data__()
        elif not isinstance(data, (str, bytes)):
            data = json.dumps(data)

        topic = as_topic(topic)
        if type is True or (type is None and self.state.type_is_topic):
            type = topic

        if self.hub:
            return self.hub.publish(topic, data, private, id, type, retry)
        if not hub_url:
            hub_url = self.hub_base_url(public=False)
        
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
    
    def get_subscriptions(self, topic=None, subscriber=None):
        topic = as_topic(topic)

        if self.hub:
            subscriptions, last_event_id = self.hub.get_subscriptions(topic, subscriber)
            return format_subscriptions_response(get_subscription_id(topic, subscriber), subscriptions, last_event_id)

        hub_url = self.hub_base_url(public=False)
        if not hub_url:
            raise Exception("No hub_url configured")
        
        topic = get_subscription_id(topic, subscriber)
        jwt = self.create_subscription_jwt(topic)

        hub_url = hub_url.rstrip("/") + topic[len("/.well-known/mercure"):]
        r = requests.get(hub_url, headers={"Authorization": f"Bearer {jwt}"})
        r.raise_for_status()
        return r.json()
    
    def is_connected(self, topic, **payload_filter):
        subscriptions = self.get_subscriptions(topic)
        if not payload_filter:
            return len(subscriptions["subscriptions"]) > 0
        for sub in subscriptions["subscriptions"]:
            if all(sub["payload"].get(k) == v for k, v in payload_filter.items()):
                return True
        return False

    def publish_signal(self, *args, **kwargs):
        kwargs["sse"] = self
        publish_signal(*args, **kwargs)


def mercure_publish(topic, data=None, **kwargs):
    return current_app.extensions["mercure_sse"].instance.publish(topic, data, **kwargs)


def publish_signal(signal, topic=None, data=None, signal_name_as_type=False, signal_kwargs_as_data=False, marshaler=None, callback=None, sse=None, **publish_kwargs):
    if not sse:
        sse = current_app.extensions["mercure_sse"].instance
    def listener(sender, **kwargs):
        _data = data
        if signal_kwargs_as_data:
            _data = dict(data or {}, **kwargs)
        publish_kwargs["topic"] = topic
        publish_kwargs["data"] = marshaler(_data) if marshaler else _data
        if signal_name_as_type:
            publish_kwargs["type"] = signal.name
        sender_kwargs = getattr(sender, "__mercure_publish__", None)
        if sender_kwargs:
            publish_kwargs.update(sender_kwargs)
        if callback:
            if callback(publish_kwargs) is False:
                return
        if not publish_kwargs.get("topic"):
            publish_kwargs["topic"] = signal.name
        sse.publish(**publish_kwargs)

    signal.connect(listener, weak=False)


def as_topic(obj):
    topic = getattr(obj, "__mercure_sse_topic__", None)
    if topic:
        return topic
    return str(obj)