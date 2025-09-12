# Flask-Mercure-SSE

Provide push capabilities using server-sent events to your Flask apps. Based on the [Mercure](https://mercure.rocks) protocol.

 - Built-in hub for development
 - Use any external Mercure hub
 - Use external hub like the [Mercure.rocks hub](https://mercure.rocks/docs/hub/install) for production and scaling

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

## About the built-in hub

The built-in hub is for **development only** as it is not scalable at all.

It implements all the required part of the Mercure specification including authorization. Subscriptions are not implemented.

## Configuration

| Key | Description | Default |
| --- | --- | --- |
| MERCURE_HUB_URL | External hub url | None |
| MERCURE_PUBLISHER_JWT | The authorization JWT to publish on external hubs | Required when hub url is provided |
| MERCURE_AUTHZ_COOKIE_NAME | Authorization cookie name | mercureAuthorization |
| MERCURE_HUB_ALLOW_PUBLISH | Whether to allow publishing via HTTP with the built-in hub | False |
| MERCURE_HUB_ALLOW_ANONYMOUS | Whether to allow anonymous subscribers to connect | True |
| MERCURE_SUBSCRIBER_SECRET_KEY | Secret key to generate subscriber JWTs | app.config["SECRET_KEY"] |
| MERCURE_PUBLISHER_SECRET_KEY | Secret key to generate publisher JWTs | app.config["SECRET_KEY"] |

## Authorization

Publish privately using `private=True` in `publish()`.

### Using external hubs

Provide the authorization JWT to the frontend:

 - Use `mercure_hub_url(topics, "SUBSCRIBER_JWT")` to generate subscription urls with the `authorization` parameter.
 - Use `mercure_authentified_hub_url(topics)` to generate subscription urls using a subscriber jwt generated using `mercure_subscriber_jwt()`.
 - Use `MercureSSE.set_authz_cookie(response, jwt="SUBSCRIBER_JWT")` to define the `mercureAuthorization` cookie.

Use `mercure_subscriber_jwt(topics)` in templates to generate a JWT.

### Using the built-in hub

First, ensure that a secret key is defined in your app config.

By default, publishing is not possible via the HTTP api for security reason. You will only need to publish internally using `MercureSSE.publish()`.

Create authorization JWT for subscribers using `MercureSSE.create_subscription_jwt(topics)`.

To authorize subscribers:

 - Pass the JWT to `mercure_hub_url()` in templates like external hubs
 - Use `MercureSSE.set_authz_cookie(response, topics)` to define the `mercureAuthorization` cookie.

When publishing via HTTP is allowed, `app.extensions["mercure"].publisher_jwt` is used as the authorization JWT.

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

It is recommended to use the official [Mercure.rocks hub](https://mercure.rocks/docs/hub/install) in production environments.