import time
from flask import Flask, Response, request
from prometheus_client import (
    Counter, Histogram, Gauge,
    generate_latest, CONTENT_TYPE_LATEST
)

app = Flask(__name__)

#Prometheus metrics
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests received",
    ["method", "endpoint", "status"]
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["endpoint"]
)

HEALTH_STATUS = Gauge(
    "app_healthy",
    "1 if the app is healthy, 0 if not"
)
HEALTH_STATUS.set(1)


#Middleware: time and count every request
@app.before_request
def start_timer():
    request._start_time = time.time()


@app.after_request
def track_metrics(response):
    # Skip the /metrics endpoint itself so scraping doesn't inflate counts
    if request.path != "/metrics":
        duration = time.time() - getattr(request, "_start_time", time.time())
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.path,
            status=response.status_code
        ).inc()
        REQUEST_LATENCY.labels(endpoint=request.path).observe(duration)
    return response


# Routes
@app.route("/")
def index():
    return "OK - Chaos Platform Running", 200


@app.route("/health")
def health():
    return "OK", 200


@app.route("/metrics")
def metrics():
    # Real Prometheus metrics
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)