from flask import Blueprint, current_app, request, abort, stream_with_context, json
from collections import namedtuple
import jwt
import queue
import uuid
import urllib.parse


Subscriber = namedtuple("Subscriber", ["id", "topics", "allowed_topics", "queue", "payload"])


class HubNotAllowed(Exception):
    pass


class Hub:
    def __init__(self, publish_subscriptions=True, reconciliation_length=500, logger=None):
        self.topics = {}
        self.subscribers = {}
        self.publish_subscriptions = publish_subscriptions
        self.reconciliation_length = reconciliation_length
        self.last_events = []
        self.logger = logger

    def subscribe(self, topics, allowed_topics=None, payload=None, reconciliate_from=None):
        id = f"urn:uuid:{uuid.uuid4()}"
        q = queue.Queue(maxsize=5)
        sub = Subscriber(id, topics, allowed_topics or [], q, payload or {})
        if self.logger:
            self.logger.debug(f"New subscriber {sub.id} for topics {topics} with allowed topics {allowed_topics}")
        self.subscribers[sub.id] = sub

        for topic in topics:
            self.topics.setdefault(topic, {})[sub.id] = sub
            if self.publish_subscriptions:
                event = format_subscription_event(topic, sub)
                self.publish(get_subscription_id(topic, sub), json.dumps(event), type="Subscription", private=True)
                self.publish(get_subscription_id(topic), json.dumps(event), type="Subscription", private=True)

        if reconciliate_from:
            msgs = []
            for topic, id, sse_msg, private in self.last_events:
                if id == reconciliate_from:
                    break
                if topic in topics:
                    msgs.append((topic, sse_msg, private))
            for topic, sse_msg, private in reversed(msgs):
                self.dispatch(sub, topic, sse_msg, private)

        return sub
    
    def unsubscribe(self, sub):
        if sub.id not in self.subscribers:
            return
        if self.logger:
            self.logger.debug(f"Unsubscribing subscriber {sub.id}")
        del self.subscribers[sub.id]
        for topic in sub.topics:
            is_subbed = self.topics.get(topic, {}).pop(sub.id, None)
            if is_subbed and self.publish_subscriptions:
                event = format_subscription_event(topic, sub, active=False)
                self.publish(get_subscription_id(topic, sub), json.dumps(event), type="Subscription", private=True)
                self.publish(get_subscription_id(topic), json.dumps(event), type="Subscription", private=True)

    def publish(self, topic, data, private=False, id=None, type=None, retry=None, allowed_topics=None):
        if allowed_topics is not None:
            if not any(match_topic_selector(t, topic) for t in allowed_topics):
                raise HubNotAllowed()
        if not id:
            id = f"urn:uuid:{uuid.uuid4()}"
        if self.logger:
            self.logger.debug(f"Publishing message {id} to topic {topic} (private={private})")
        sse_msg = format_sse_msg(data, id, type, retry)
        if self.reconciliation_length:
            self.last_events.insert(0, (topic, id, sse_msg, private))
            del self.last_events[self.reconciliation_length:]
        for sub in self.topics.get(topic, {}).values():
            self.dispatch(sub, topic, sse_msg, private)
        return id
    
    def dispatch(self, sub, topic, msg, private=False):
        if private and not any(match_topic_selector(t, topic) for t in sub.allowed_topics):
            return False
        try:
            sub.queue.put_nowait(msg)
            return True
        except:
            if self.logger:
                self.logger.debug(f"Dropping message for subscriber {sub.id} (queue error)")
            self.unsubscribe(sub)
            return False
        
    def get_subscriptions(self, topic=None, subscriber=None, allowed_topics=None):
        if topic:
            topic = urllib.parse.unquote(topic)
            if allowed_topics is not None and not any(match_topic_selector(t, topic) for t in allowed_topics):
                raise HubNotAllowed()
            if topic not in self.topics:
                return [], "earliest"
            subscriptions = [(topic, self.topics[topic])]
            last_event_id = next((e[1] for e in self.last_events if e[0] == topic), "earliest")
        else:
            subscriptions = [(topic, subs) for topic, subs in self.topics.items()
                            if any(match_topic_selector(t, topic) for t in allowed_topics)]
            last_event_id = self.last_events[0][1] if self.last_events else "earliest"

        if subscriber:
            subscriber = urllib.parse.unquote(subscriber)
            subscriptions = [(t, {subscriber: subs[subscriber]}) for t, subs in subscriptions if subscriber in subs]

        return subscriptions, last_event_id


hub_blueprint = Blueprint("mercure_hub", __name__, url_prefix="/.well-known/mercure")


@hub_blueprint.route("")
def subscribe():
    state = current_app.extensions["mercure_sse"]
    claim = get_authorization_jwt("subscriber_secret_key")
    if not state.hub_allow_anonymous and not claim:
        abort(401)

    topics = request.args.getlist("topic")
    reconciliate_from = request.headers.get("Last-Event-ID", request.args.get("lastEventID"))

    sub = state.instance.hub.subscribe(
        topics=topics,
        allowed_topics=claim.get("subscribe", []) if claim else [],
        payload=claim.get("payload", None) if claim else None,
        reconciliate_from=reconciliate_from
    )

    @stream_with_context
    def stream():
        try:
            while True:
                try:
                    msg = sub.queue.get(timeout=state.hub_keepalive_interval or None)
                except queue.Empty:
                    yield ":ping\n\n"
                    continue
                if msg is None:
                    break
                yield msg
        except GeneratorExit:
            state.instance.hub.unsubscribe(sub)


    return stream(), {"Content-Type": "text/event-stream"}


@hub_blueprint.post("")
def publish():
    state = current_app.extensions["mercure_sse"]
    if not state.hub_allow_publish:
        abort(405)

    claim = get_authorization_jwt("publisher_secret_key")
    if not claim:
        abort(401)

    try:
        return state.instance.hub.publish(
            topic=request.form["topic"],
            data=request.form["data"],
            private=request.form.get("private"),
            id=request.form.get("id"),
            type=request.form.get("type"),
            retry=request.form.get("retry"),
            allowed_topics=claim.get("publish", [])
        )
    except HubNotAllowed:
        abort(403)


@hub_blueprint.route("/subscriptions")
@hub_blueprint.route("/subscriptions/<topic>")
@hub_blueprint.route("/subscriptions/<topic>/<subscriber>")
def get_subscriptions(topic=None, subscriber=None):
    state = current_app.extensions["mercure_sse"]
    if not state.hub_subscriptions:
        abort(404)

    claim = get_authorization_jwt("subscriber_secret_key")
    if not claim:
        abort(401)

    allowed_topics = claim.get("subscribe", [])
    if topic:
        topic = urllib.parse.unquote(topic)
    if subscriber:
        subscriber = urllib.parse.unquote(subscriber)

    try:
        subscriptions, last_event_id = state.instance.hub.get_subscriptions(topic=topic, subscriber=subscriber, allowed_topics=allowed_topics)
    except HubNotAllowed:
        abort(403)
    if not subscriptions:
        abort(404)

    data = format_subscriptions_response(get_subscription_id(topic, subscriber), subscriptions, last_event_id)
    return json.dumps(data), 200, {"Content-Type": "application/ld+json"}


def get_authorization_jwt(key):
    auth_value = None
    cookie_name = current_app.extensions["mercure_sse"].authz_cookie_name
    if request.headers.get("Authorization"):
        auth_value = request.headers["Authorization"].split(" ")[1]
    elif request.cookies.get(cookie_name):
        auth_value = request.cookies[cookie_name]
    elif request.args.get("authorization"):
        auth_value = request.args["authorization"]
    if auth_value:
        try:
            secret = getattr(current_app.extensions["mercure_sse"], key)
            return jwt.decode(auth_value, secret, ["HS256"]).get("mercure", {})
        except Exception as e:
            current_app.logger.debug(e)
            abort(403)


def match_topic_selector(selector, topic):
    if selector == "*":
        return True
    if selector == topic:
        return True
    if selector.endswith("*") and topic.startswith(selector[:-1]):
        return True
    return False


def format_sse_msg(data, id=None, type=None, retry=None):
    msg = []
    if type:
        msg.append(f"event: {type}")
    if id:
        msg.append(f"id: {id}")
    if retry:
        msg.append(f"retry: {retry}")
    msg.extend(f"data: {line}" for line in data.splitlines())
    return "\n".join(msg) + "\n\n"


def format_subscription_event(topic, sub, active=True):
    return {
        "id": get_subscription_id(topic, sub),
        "type": "Subscription",
        "topic": topic,
        "subscriber": sub.id,
        "active": active,
        "payload": sub.payload,
    }


def get_subscription_id(topic, sub=None):
    id = f"/.well-known/mercure/subscriptions/{urllib.parse.quote(topic)}"
    if sub:
        id += f"/{urllib.parse.quote(sub.id)}"
    return id


def format_subscriptions_response(id, subscriptions, last_event_id):
    return {
        "@context": "https://mercure.rocks/",
        "id": id,
        "type": "Subscriptions",
        "lastEventID": last_event_id,
        "subscriptions": [
            format_subscription_event(topic, sub) for topic, subs in subscriptions for sub in subs.values()
        ]
    }