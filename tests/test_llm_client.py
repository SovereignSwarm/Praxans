import unittest

from llm.client import OllamaClient, USER_SETTINGS


class _FakeListClient:
    def __init__(self, names):
        self._names = names

    def list(self):
        return {"models": [{"name": n} for n in self._names]}


class _FakeOllama:
    def __init__(self, names):
        self._names = names

    def Client(self, **kwargs):
        return _FakeListClient(self._names)

    def list(self):
        return {"models": [{"name": n} for n in self._names]}


class OllamaClientDetectionTests(unittest.TestCase):
    def test_detect_model_force_refresh_reloads_target_setting(self):
        original_model = USER_SETTINGS.llm_model
        try:
            USER_SETTINGS.llm_model = "model-a"
            client = OllamaClient()
            client._ollama = _FakeOllama(["model-a", "model-b"])
            client._client = client._make_client(client.request_timeout)

            self.assertEqual(client.detect_model(), "model-a")

            USER_SETTINGS.llm_model = "model-b"
            self.assertEqual(client.detect_model(force_refresh=True), "model-b")
        finally:
            USER_SETTINGS.llm_model = original_model


if __name__ == "__main__":
    unittest.main()
