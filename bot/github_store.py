from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class GitHubConfig:
    token: str
    repository: str
    path: str
    branch: str = "main"


class GitHubStore:
    def __init__(self, config: GitHubConfig) -> None:
        self.config = config
        owner, separator, repository = config.repository.partition("/")
        if not separator or not owner or not repository:
            raise ValueError("GITHUB_REPOSITORY must use owner/repository")
        quoted_path = urllib.parse.quote(config.path.strip("/"), safe="/")
        self.api_url = (
            f"https://api.github.com/repos/{owner}/{repository}/contents/{quoted_path}"
        )

    def publish(self, content: bytes) -> str:
        existing_sha = self._existing_sha()
        body: dict[str, object] = {
            "message": "Publish e-paper image",
            "content": base64.b64encode(content).decode("ascii"),
            "branch": self.config.branch,
        }
        if existing_sha:
            body["sha"] = existing_sha

        request = self._request(
            self.api_url,
            method="PUT",
            data=json.dumps(body).encode("utf-8"),
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
        return str(payload["commit"]["sha"])

    def _existing_sha(self) -> str | None:
        query = urllib.parse.urlencode({"ref": self.config.branch})
        request = self._request(f"{self.api_url}?{query}")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.load(response)
            return str(payload["sha"])
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise

    def _request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
    ) -> urllib.request.Request:
        return urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.config.token}",
                "Content-Type": "application/json",
                "User-Agent": "esp-super-mini-epaper-bot",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
