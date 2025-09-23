from flask import current_app
from flask.cli import AppGroup
import click
import secrets


cli = AppGroup("mercure", help="Mercure hub commands")


@cli.command()
def gen_secret_key():
    """Generate a secret key (to be used for subscriber_secret_key or publisher_secret_key)"""
    print(secrets.token_hex(16))


@cli.command()
@click.option("--topic", "-t", multiple=True, default=["*"])
def subscriber_jwt(topic):
    """Generate a JWT for subscribing to topics"""
    print(current_app.extensions["mercure_sse"].instance.create_subscription_jwt(topic))


@cli.command()
@click.option("--topic", "-t", multiple=True, default=["*"])
def publisher_jwt(topic):
    """Generate a JWT for publishing"""
    print(current_app.extensions["mercure_sse"].instance.create_jwt("publisher_secret_key", publish=topic))


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
    print(current_app.extensions["mercure_sse"].instance.publish(topic, data, private, id, type, retry, jwt, hub))