from flask import Flask, render_template, request, redirect, url_for, session
from flask_mercure_sse import MercureSSE


app = Flask(__name__)
app.config["SECRET_KEY"] = "changeme"
mercure = MercureSSE(app, hub_allow_publish=True, hub_url="http://localhost:5500/.well-known/mercure")


@app.route("/")
def index():
    return render_template("index.html", username=session.get("username"))


@app.post("/publish")
def publish():
    mercure.publish("messages", f"<p><em>@{session.get('username', 'anonymous')}</em>: {request.form['message']}</p>", private=request.form.get("private") == "on")
    return "ok"


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        session["username"] = request.form["username"]
        r = redirect(url_for("index"))
        mercure.set_authz_cookie(r, topics=["messages"])
        return r
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("username", None)
    r = redirect(url_for("index"))
    mercure.delete_authz_cookie(r)
    return r