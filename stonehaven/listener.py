"""FastAPI webhook listener with HMAC verification and deduplication.

This module provides the FastAPI application for receiving GitHub webhook events,
verifying HMAC signatures, deduplicating by delivery ID, and queueing reviews
for background processing.

⚠️ WARNING: Webhook timeout vs review duration — GitHub timeout is 10 seconds, return 200 immediately
⚠️ WARNING: HMAC signature verification non-negotiable — Verify on every request before processing
⚠️ WARNING: Deduplication by X-GitHub-Delivery header required to prevent duplicate reviews
"""

import hashlib
import hmac
import json
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .registry import ProjectRegistry


class WebhookHandler:
    """Handles webhook processing with HMAC verification and deduplication."""

    def __init__(
        self,
        registry: ProjectRegistry,
        worker: Any = None,
        webhook_secret: str = "webhook-secret-placeholder",
    ) -> None:
        """Initialize webhook handler with project registry.

        Args:
            registry: ProjectRegistry instance for project lookups
            worker: Optional ReviewWorker for background review processing
            webhook_secret: HMAC secret for verifying GitHub webhook signatures
        """
        self.registry = registry
        self._worker = worker
        self._webhook_secret = webhook_secret
        self._processed_deliveries: set[str] = set()

    def _verify_signature(self, payload: bytes, signature: str, secret: str) -> bool:
        """Verify HMAC-SHA256 signature against payload.

        Args:
            payload: Raw webhook payload bytes
            signature: GitHub signature header value (format: sha256=<hex>)
            secret: Webhook secret for HMAC verification

        Returns:
            True if signature is valid, False otherwise
        """
        if not signature.startswith("sha256="):
            return False

        expected_signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

        provided_signature = signature[7:]  # Remove 'sha256=' prefix

        return hmac.compare_digest(expected_signature, provided_signature)

    def _is_duplicate_delivery(self, delivery_id: str) -> bool:
        """Check if delivery ID has already been processed.

        Args:
            delivery_id: GitHub delivery ID from X-GitHub-Delivery header

        Returns:
            True if delivery has been processed, False otherwise
        """
        return delivery_id in self._processed_deliveries

    def _mark_delivery_processed(self, delivery_id: str) -> None:
        """Mark delivery ID as processed to prevent duplicates.

        Args:
            delivery_id: GitHub delivery ID to mark as processed
        """
        self._processed_deliveries.add(delivery_id)

    async def handle_webhook(
        self,
        payload: bytes,
        signature: str,
        delivery_id: str,
    ) -> dict[str, Any]:
        """Handle incoming webhook with signature verification and deduplication.

        Args:
            payload: Raw webhook payload bytes
            signature: HMAC signature from GitHub
            delivery_id: GitHub delivery ID

        Returns:
            Response dictionary with status and message

        Raises:
            HTTPException: If signature verification fails or delivery is duplicate
        """
        if self._is_duplicate_delivery(delivery_id):
            raise HTTPException(status_code=409, detail=f"Delivery {delivery_id} already processed")

        if not self._verify_signature(payload, signature, self._webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

        self._mark_delivery_processed(delivery_id)

        return {
            "status": "received",
            "delivery_id": delivery_id,
            "message": "Webhook processed successfully",
        }


def create_listener_app(handler: WebhookHandler) -> FastAPI:
    """Create FastAPI application with webhook endpoint.

    Args:
        handler: WebhookHandler instance for processing webhooks

    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title="Stonehaven Webhook Listener",
        description="GitHub webhook listener for triumvirate code reviews",
        version="1.0.0",
    )

    @app.post("/webhook")
    async def webhook_endpoint(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
        """GitHub webhook endpoint with HMAC verification and deduplication.

        Returns:
            200 response immediately to meet GitHub timeout requirements
        """
        signature = request.headers.get("X-Hub-Signature-256", "")
        delivery_id = request.headers.get("X-GitHub-Delivery", "")

        if not signature:
            raise HTTPException(status_code=400, detail="Missing X-Hub-Signature-256 header")

        if not delivery_id:
            raise HTTPException(status_code=400, detail="Missing X-GitHub-Delivery header")

        payload = await request.body()

        try:
            result = await handler.handle_webhook(payload, signature, delivery_id)

            if handler._worker is not None:
                try:
                    body = json.loads(payload)
                    repo = body.get("repository", {}).get("full_name", "")
                    pr_number = body.get("pull_request", {}).get("number", 0)
                    if repo and pr_number:
                        background_tasks.add_task(
                            handler._worker.process_review,
                            delivery_id,
                            repo,
                            pr_number,
                        )
                except Exception:
                    pass

            return JSONResponse(status_code=200, content=result)
        except HTTPException:
            raise
        except Exception:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "error",
                    "delivery_id": delivery_id,
                    "message": "Internal error processing webhook",
                },
            )

    @app.get("/health")
    async def health_check() -> JSONResponse:
        """Health check endpoint for service monitoring.

        Returns:
            200 response with service status
        """
        return JSONResponse(
            status_code=200, content={"status": "healthy", "service": "stonehaven-listener"}
        )

    return app


__all__ = ["WebhookHandler", "create_listener_app"]
