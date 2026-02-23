import logging
from flask import Flask, jsonify
from monitor_homeserve import obtener_servicios  # tu función de HomeServe

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

@app.route("/")
def index():
    return "Bot HomeServe funcionando 🚀"

@app.route("/test_servicios")
def test_servicios():
    servicios = obtener_servicios()
    return jsonify(servicios)
