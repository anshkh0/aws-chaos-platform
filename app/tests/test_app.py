import pytest
from app import app


@pytest.fixture
def client():
    # Spins up the Flask test client — no real server needed
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_index_returns_200(client):
    response = client.get("/")
    assert response.status_code == 200


def test_index_content(client):
    response = client.get("/")
    assert b"Chaos Platform Running" in response.data


def test_health_returns_200(client):
    # This is what the ALB polls — must always return 200
    response = client.get("/health")
    assert response.status_code == 200


def test_health_content(client):
    response = client.get("/health")
    assert b"OK" in response.data


def test_metrics_returns_200(client):
    response = client.get("/metrics")
    assert response.status_code == 200


def test_metrics_content_type(client):
    # Prometheus expects a specific content type
    response = client.get("/metrics")
    assert "text/plain" in response.content_type


def test_metrics_contains_request_counter(client):
    # Verify our real Prometheus counter is being exported
    response = client.get("/metrics")
    assert b"http_requests_total" in response.data


def test_metrics_contains_health_gauge(client):
    response = client.get("/metrics")
    assert b"app_healthy" in response.data