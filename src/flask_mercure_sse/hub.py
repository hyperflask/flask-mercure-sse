from flask import current_app, Blueprint, request, abort, stream_with_context, session
import jwt
import queue
import json
import uuid


class Broker:
    def __init__(self):
        self.subscribers = {}

    def subscribe(self, topics, allowed_topics=None):
        q = queue.Queue(maxsize=5)
        sub_info = (allowed_topics or [], q)
        for topic in topics:
            self.subscribers.setdefault(topic, []).append(sub_info)
        return q

    def publish(self, topic, data, private=False, id=None, type=None, retry=None):
        if not id:
            id = f"urn:uuid:{uuid.uuid4()}"
        subscribers = self.subscribers.get(topic, [])
        sse_msg = format_sse_msg(data, id, type, retry)
        for i in reversed(range(len(subscribers))):
            if private:
                allowed = False
                for topic_selector in subscribers[i][0]:
                    if match_topic_selector(topic_selector, topic):
                        allowed = True
                        break
                if not allowed:
                    continue
            try:
                subscribers[i][1].put_nowait(sse_msg)
            except queue.Full:
                del subscribers[i]
        return id


hub_blueprint = Blueprint("mercure_hub", __name__, url_prefix="/.well-known/mercure")


@hub_blueprint.route("")
def subscribe():
    topics = request.args.getlist("topic")
    claim = get_authorization_jwt("subscriber_secret_key")

    if not current_app.extensions["mercure_sse"].hub_allow_anonymous and not claim:
        abort(403)

    @stream_with_context
    def stream():
        sub = current_app.extensions["mercure_sse"].broker.subscribe(topics, claim.get("subscribe", []) if claim else [])
        while True:
            yield sub.get()
            
    return stream(), {"Content-Type": "text/event-stream"}


@hub_blueprint.post("")
def publish():
    if not current_app.extensions["mercure_sse"].hub_allow_publish:
        abort(405)

    claim = get_authorization_jwt("publisher_secret_key")
    if not claim:
        abort(403)

    topic = request.form["topic"]
    allowed = False
    for topic_selector in claim.get("publish", []):
        if match_topic_selector(topic_selector, topic):
            allowed = True
            break
    if not allowed:
        abort(403)

    return current_app.extensions["mercure_sse"].broker.publish(
        topic,
        request.form["data"],
        private=request.form.get("private"),
        id=request.form.get("id"),
        type=request.form.get("type"),
        retry=request.form.get("retry"),
    )


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
        return jwt.decode(auth_value, getattr(current_app.extensions["mercure_sse"], key), ["HS256"]).get("mercure", {})
    

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
    if not isinstance(data, str):
        data = json.dumps(data)
    msg.append(f"data: {data}")
    return "\n".join(msg) + "\n\n"