# Flask-Mercure-SSE

Provide push capabilities using server-sent events to your Flask apps. Based on the [Mercure](https://mercure.rocks) protocol.

 - Get started in seconds
 - Full spec implementation
 - Built-in hub
 - Use any external Mercure hub (like the [Mercure.rocks hub](https://mercure.rocks/docs/hub/install))

## Installation

```
pip install flask-mercure-sse
```

## Getting started

Enable the `MercureSSE` extension:

```python
from flask import Flask
from flask_mercure_sse import MercureSSE

app = Flask(__name__)
mercure = MercureSSE(app)
```

Publish messages from anywhere in your app:

```python
mercure.publish("topic", "message")
```

Generate subscription urls in your templates:

```html
<script>
const es = new EventSource("{{ mercure_hub_url('topic') }})");
// ...
</script>
```

## Configuration

| Key | Description | Default |
| --- | --- | --- |
| MERCURE_HUB_URL | Hub URL | None |
| MERCURE_PUBLIC_HUB_URL | Hub URL to use on the frontend | `$MERCURE_HUB_URL` |
| MERCURE_PUBLISHER_JWT | The authorization JWT to publish on external hubs | Required when hub url is provided |
| MERCURE_AUTHZ_COOKIE_NAME | Authorization cookie name | mercureAuthorization |
| MERCURE_TYPE_IS_TOPIC | Whether to auto set type to topic name when no type is provided | False |
| MERCURE_HUB_ALLOW_PUBLISH | Whether to allow publishing via HTTP with the built-in hub when embedded | False |
| MERCURE_HUB_ALLOW_ANONYMOUS | Whether to allow anonymous subscribers to connect | True |
| MERCURE_HUB_SUBSCRIPTIONS | Whether to enable the [Mercure subscriptions API](https://mercure.rocks/spec#active-subscriptions) | True |
| MERCURE_HUB_KEEPALIVE_INTERVAL | Interval in secs between ping messages to ensure the connection is alive, 0 to disable | 15
| MERCURE_HUB_RECONCILIATION_LENGTH | Number of messages to keep across all topics for [reconciliation](https://mercure.rocks/spec#reconciliation) | 500
| MERCURE_SUBSCRIBER_SECRET_KEY | Secret key to generate subscriber JWTs | app.config["SECRET_KEY"] |
| MERCURE_PUBLISHER_SECRET_KEY | Secret key to generate publisher JWTs | app.config["SECRET_KEY"] |

### About the hub URL

If no hub URL is defined, the defaults are:

 - When the embedded hub is used (ie. in debug mode), the hub url is formed using `request.host_url`
 - Otherwise, the default is <http://localhost:5500/.well-known/mercure>

If you only provide a public URL, the default will be used for "internal calls" (server to server) and the public URL will be used for public URLs.

If you are using an external hub, setting `MERCURE_HUB_URL` is enough.

Set `MERCURE_HUB_URL` to True to always use `request.host_url`.

## Authorization

Publish privately using `private=True` in `publish()`.

Use `MercureSSE.create_subscription_jwt(topics)` or `mercure_subscriber_jwt(topics)` in templates to generate a JWT. Remember to set a `MERCURE_SUBSCRIBER_SECRET_KEY` or the app's secret key will be used.

Pass the subscriber JWT to the hub:

 - Use `mercure_hub_url(topics, "SUBSCRIBER_JWT")` to generate subscription urls with the `authorization` parameter.
 - Use `mercure_authentified_hub_url(topics)` to generate subscription urls using a subscriber jwt generated using `mercure_subscriber_jwt()`.
 - Use `MercureSSE.set_authz_cookie(response, jwt="SUBSCRIBER_JWT")` to define the `mercureAuthorization` cookie (if `jwt` is omitted, `mercure_subscriber_jwt()` is used).

## Subscriptions

Track subscriptions using [Mercure subscriptions API](https://mercure.rocks/spec#active-subscriptions).

Provide a payload when creating JWTs:

```py
mercure = MercureSSE(app)
@mercure.payload_getter
def get_mercure_payload(topics):
    return {'user_id': current_user.id}
```

Check whether a subscription exists:

```py
mercure.is_connected(topic, user_id=ID) # keyword arguments are payload filters
```

List all subscriptions:

```py
subs = mercure.get_subscriptions(topic) # returns the parsed JSON response of the subscriptions endpoint
```

## Built-in hub

The built-in hub can be used in 2 modes:

 - Embedded in your normal flask app. This is for **development only** as it is not scalable at all.
 - As a standalone server using gevent

It implements the full specification.

The embedded hub is only enabled if `app.debug` or `app.testing` is True. **It is expected that you start the standalone server in production.**
(You can always force the use of the embedded hub by setting `MERCURE_HUB` to True)

### In development

First, ensure that a secret key is defined in your app config.

By default, publishing is not possible via the HTTP api for security reasons. You will only be able to publish internally using `MercureSSE.publish()`.

### As standalone server

Run the standalone server: `python -m flask_mercure_sse.server --subscriber-secret SECRET --publisher-secret SECRET`

This will start the server on port 5500. Grab the provided publisher JWT.

In your Flask app, configure the hub:

```py
mercure = MercureSSE(app, hub_url="http://localhost:5500/.well-known/mercure", subscriber_secret_key="SECRET", publisher_jwt="JWT")
```

Setting the hub_url is not needed if you only use the standalone hub in production. You should however set the public url to ensure the hub is accessible externally.

## Multiplexing a single event source

Set `MERCURE_TYPE_IS_TOPIC` to true so that events get the same name as the topic they originate from. This allows you to subscribe to multiple topics at once and discriminate messages based on their event name.

## Using signals as event sources

Use `MercureSSE.publish_signal(signal)` to publish an event each time the signal is dispatched

```py
my_event = signal('my-event')
mercure.publish_signal(my_event) # topic is the event name
```

Check out the parameters of `publish_signal()` for options when handling the event.

## CLI

Some CLI commands are available.

Start with `flask mercure --help`.

## Going to production

Use the built-in hub as a standalone server or use the [Mercure.rocks hub](https://mercure.rocks/docs/hub/install) in production environments.