"""Shared controlled fixtures extracted from test_model_stream_errors."""
import json
import httpx


def stream(*events, done=True):
    data = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events)
    return httpx.Response(200, text=data + ('data: [DONE]\n\n' if done else ''), headers={'Content-Type': 'text/event-stream'})


def client_for(monkeypatch, handler):
    monkeypatch.setattr('app.integrations.models.transport.client', lambda settings: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
