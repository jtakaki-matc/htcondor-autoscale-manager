
import os

import htcondor

from flask import Flask
from flask_apscheduler import APScheduler

import htcondor_autoscale_manager.occupancy_metric
import htcondor_autoscale_manager.patch_annotation

app = Flask(__name__)

config = {}
for key, val in os.environ.items():
    if key.startswith("FLASK_"):
        app.config[key[6:]] = val

scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

g_metric = 1.0

@scheduler.task("interval", id="metric_update", seconds=60)
def metric_update():
    resource = app.config.get("RESOURCE_NAME")
    if not resource:
        print("RESOURCE_NAME not set - cannot compute metric.")
        return
    query = app.config.get("POD_LABEL_SELECTOR")
    if not query:
        print("POD_LABEL_SELECTOR not set - cannot query kubernetes for pods.")
        return

    with htcondor.SecMan() as sm:
        if 'BEARER_TOKEN' in app.config:
            sm.setToken(htcondor.Token(app.config['BEARER_TOKEN']))
        elif 'BEARER_TOKEN' in os.environ:
            sm.setToken(htcondor.Token(os.environ['BEARER_TOKEN']))
        elif 'BEARER_TOKEN_FILE' in app.config:
            with open(app.config['BEARER_TOKEN_FILE']) as fp:
                sm.setToken(htcondor.Token(fp.read().strip()))
        elif 'BEARER_TOKEN_FILE' in os.environ:
            with open(os.environ['BEARER_TOKEN_FILE']) as fp:
                sm.setToken(htcondor.Token(fp.read().strip()))
        try:
            global g_metric
            g_metric, counts = htcondor_autoscale_manager.occupancy_metric(query, resource)
        except Exception as exc:
            print(f"Exception occurred during metric update: {exc}")
            return

    # Annotate the 'cost' of deleting the pod
    for pod in counts['pods']:
        if pod not in counts['online_pods']:
            htcondor_autoscale_manager.patch_annotation(pod, 0)
        elif pod in counts['idle_pods']:
            htcondor_autoscale_manager.patch_annotation(pod, 5)

@app.route("/metrics")
def metrics():
    return f"occupancy {g_metric}\n"

def entry():
    app.run()
