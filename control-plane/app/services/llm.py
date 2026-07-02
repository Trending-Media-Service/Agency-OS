import os
import json
import logging
import httpx
from typing import Optional

logger = logging.getLogger(__name__)

class VertexAIClient:
    def __init__(self, region: str = "us-central1", project_id: Optional[str] = None):
        self.region = region
        self.project_id = project_id or os.getenv("GCP_PROJECT") or "mock-project"
        self.model = "gemini-1.5-pro"

    async def generate_personalized_content(
        self,
        tenant_id: str,
        brand_id: str,
        prompt: str,
        session=None,
        system_instruction: Optional[str] = None,
    ) -> str:
        """Generates free-form structured content (e.g. a brand-identity JSON profile).

        Returns the model's raw text response (the caller is responsible for json.loads).
        `session` is accepted for cost-logging parity with other call sites but is optional
        and unused by the generation call itself.
        """
        if os.getenv("AOS_ENV") == "test":
            logger.info("[TEST MODE] Returning mock personalized content for LLM request")
            return json.dumps(
                {
                    "tone_of_voice": "Friendly, modern, and direct",
                    "target_persona": "General e-commerce consumers",
                    "past_experience": "No performance logs recorded yet.",
                }
            )

        import google.auth
        import google.auth.transport.requests

        try:
            credentials, resolved_project = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
            token = credentials.token
            project = self.project_id or resolved_project
        except Exception as e:
            logger.error(f"Failed to obtain GCP credentials: {e}")
            raise RuntimeError(f"GCP Authentication failed: {e}")

        url = (
            f"https://{self.region}-aiplatform.googleapis.com/v1/projects/{project}"
            f"/locations/{self.region}/publishers/google/models/{self.model}:generateContent"
        )
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers, timeout=60.0)
            if resp.status_code != 200:
                logger.error(f"Vertex AI API returned error: {resp.status_code} - {resp.text}")
                raise RuntimeError(f"Vertex AI request failed: {resp.text}")
            data = resp.json()
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, ValueError) as e:
                logger.error(f"Failed to parse model response payload: {e}. Raw response: {data}")
                raise RuntimeError("Invalid model response format")

    def generate_edits(self, intent: str, files_context: str) -> dict:
        """Sends the prompt to Vertex AI Gemini model to get code edits in structured JSON."""
        if os.getenv("AOS_ENV") == "test":
            logger.info("[TEST MODE] Returning mock edits for LLM request")
            return {
                "explanation": "Simulated edits for testing",
                "edits": [
                    {
                        "path": "src/App.js",
                        "action": "modify",
                        "content": "function App() {\n  return <Hero color=\"blue\" />;\n}\n"
                    }
                ]
            }

        import google.auth
        import google.auth.transport.requests

        try:
            credentials, resolved_project = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
            token = credentials.token
            project = self.project_id or resolved_project
        except Exception as e:
            logger.error(f"Failed to obtain GCP credentials: {e}")
            raise RuntimeError(f"GCP Authentication failed: {e}")

        url = f"https://{self.region}-aiplatform.googleapis.com/v1/projects/{project}/locations/{self.region}/publishers/google/models/{self.model}:generateContent"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": f"Change request: {intent}\n\nCodebase Context:\n{files_context}"
                        }
                    ]
                }
            ],
            "systemInstruction": {
                "parts": [
                    {
                        "text": "You are a professional software engineer. Generate codebase edits in JSON matching the requested responseSchema. Maintain existing indentation and style."
                    }
                ]
            },
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "explanation": {
                            "type": "STRING"
                        },
                        "edits": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "path": {
                                        "type": "STRING"
                                    },
                                    "action": {
                                        "type": "STRING",
                                        "enum": ["modify", "create", "delete"]
                                    },
                                    "content": {
                                        "type": "STRING"
                                    }
                                },
                                "required": ["path", "action", "content"]
                            }
                        }
                    },
                    "required": ["explanation", "edits"]
                }
            }
        }

        with httpx.Client() as client:
            resp = client.post(url, json=payload, headers=headers, timeout=60.0)
            if resp.status_code != 200:
                logger.error(f"Vertex AI API returned error: {resp.status_code} - {resp.text}")
                raise RuntimeError(f"Vertex AI request failed: {resp.text}")
            
            data = resp.json()
            try:
                # Parse text response from the choices block
                text_content = data["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text_content)
            except (KeyError, IndexError, ValueError) as e:
                logger.error(f"Failed to parse model response payload: {e}. Raw response: {data}")
                raise RuntimeError("Invalid model response format")
