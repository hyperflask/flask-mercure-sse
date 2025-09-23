try:
    from gevent.pywsgi import WSGIServer
    from gevent import monkey
    monkey.patch_all()
    def serve(app, host, port):
        print("Serving on http://%s:%d" % (host, port))
        WSGIServer((host, port), app).serve_forever()
except ImportError:
    try:
        import eventlet
        import eventlet.wsgi
        eventlet.monkey_patch()
        def serve(app, host, port):
            eventlet.wsgi.server(eventlet.listen((host, port)), app)
    except ImportError:
        raise ImportError("Please install either gevent or eventlet to run the server.")


import click
import logging
from .app import create_app


@click.command()
@click.option("--host", default="0.0.0.0", help="Host to run the server on.")
@click.option("--port", default=5500, help="Port to run the server on.")
@click.option("--publisher-secret", default=None, help="Publisher secret key.")
@click.option("--subscriber-secret", default=None, help="Subscriber secret key.")
@click.option("--allow-anonymous/--no-allow-anonymous", is_flag=True, default=True, help="Allow anonymous subscriptions.")
@click.option("--cors-origins", default="*", help="CORS origins.")
@click.option("--subscriptions/--no-subscriptions", is_flag=True, default=True, help="Enable subscriptions.")
@click.option("--debug", is_flag=True, default=False, help="Enable debug mode.")
def run_server(host, port, publisher_secret, subscriber_secret, allow_anonymous, cors_origins, subscriptions, debug):
    app = create_app(publisher_secret=publisher_secret, subscriber_secret=subscriber_secret,
                     allow_anonymous=allow_anonymous, cors_origins=cors_origins, subscriptions=subscriptions)
    if debug:
        app.debug = True
        logging.getLogger().setLevel(logging.DEBUG)
    serve(app, host, port)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_server()