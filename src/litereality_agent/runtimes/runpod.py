"""Small RunPod Serverless transport shared by model services."""

from __future__ import annotations

import json
import urllib.request


class RunPodClient:
    """Submit and inspect queued jobs without importing model-specific code."""

    def __init__(
        self,
        api_key: str,
        endpoint_id: str,
        *,
        base_url: str = "https://api.runpod.ai/v2",
        http_timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.base = f"{base_url.rstrip('/')}/{endpoint_id}"
        self.http_timeout = http_timeout

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        request = urllib.request.Request(
            f"{self.base}/{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=self.http_timeout) as response:
            return json.loads(response.read().decode())

    def run(self, job_input: dict) -> str:
        response = self._request("POST", "run", {"input": job_input})
        job_id = response.get("id")
        if not job_id:
            raise RuntimeError(f"RunPod /run returned no job id: {response}")
        return str(job_id)

    def status(self, job_id: str) -> dict:
        return self._request("GET", f"status/{job_id}")

    def cancel(self, job_id: str) -> dict:
        return self._request("POST", f"cancel/{job_id}")

    def health(self) -> dict:
        return self._request("GET", "health")
