from flask import Flask, render_template, request, redirect, url_for
from flask_mercure_sse import MercureSSE


app = Flask(__name__)
app.config["SECRET_KEY"] = "changeme"
mercure = MercureSSE(app, hub_allow_publish=True)


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/publish")
def publish():
    mercure.publish("messages", f"<p>{request.form['message']}</p>", private=request.form.get("private") == "on")
    return "ok"


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        mercure.set_authz_session(subscribe=["messages"])
        return redirect(url_for("index"))
    return render_template("login.html")