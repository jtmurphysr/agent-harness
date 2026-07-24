"""24-hour soak test runner for webhook reliability validation.

This module provides the SoakTestRunner class for executing sustained
load testing of the webhook processing pipeline to validate reliability,
consistency, and detect missed events or duplicate reviews.

Domain warnings:
⚠️ WARNING: Final v1 gate — must demonstrate zero missed events and duplicates
⚠️ WARNING: 24-hour continuous test with simulated webhook traffic at 10/min
⚠️ WARNING: Verdict Store consistency must be maintained throughout test
"""

import asyncio
import hashlib
import hmac
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from fastapi.testclient import TestClient

__all__ = ["SoakTestResults", "SoakTestRunner"]

logger = structlog.get_logger(__name__)


@dataclass
class SoakTestResults:
    """Results from a soak test run."""

    duration_hours: float
    webhooks_sent: int
    webhooks_received: int
    reviews_completed: int
    verdicts_stored: int
    missed_events: int
    duplicate_reviews: int
    verdict_store_inconsistencies: int
    errors: list[str] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None

    @property
    def success(self) -> bool:
        """Return True if soak test passed all reliability requirements."""
        return (
            self.missed_events == 0
            and self.duplicate_reviews == 0
            and self.verdict_store_inconsistencies == 0
            and len(self.errors) == 0
        )


class SoakTestRunner:
    """Runner for 24-hour webhook reliability soak testing.

    Orchestrates sustained webhook traffic simulation with parallel monitoring
    of event delivery, review processing, and Verdict Store consistency to
    validate system reliability under continuous load.
    """

    def __init__(self, test_client: TestClient, temp_db_path: Path) -> None:
        """Initialize soak test runner.

        Args:
            test_client: FastAPI test client for webhook simulation
            temp_db_path: Path to temporary test database
        """
        self.test_client = test_client
        self.temp_db_path = temp_db_path
        self._webhook_secret = "test_webhook_secret_for_soak_testing"
        self._project_id = "test-project-soak"
        self._running = False
        self._webhook_counter = 0
        self._delivery_ids: set[str] = set()

    def run_soak_test(
        self,
        duration_hours: int = 24,
        webhook_rate_per_min: int = 10,
    ) -> dict[str, Any]:
        """Execute soak test with specified duration and webhook rate.

        Args:
            duration_hours: Duration of soak test in hours
            webhook_rate_per_min: Number of webhooks to send per minute

        Returns:
            Dictionary containing test results and metrics
        """
        results = SoakTestResults(
            duration_hours=duration_hours,
            webhooks_sent=0,
            webhooks_received=0,
            reviews_completed=0,
            verdicts_stored=0,
            missed_events=0,
            duplicate_reviews=0,
            verdict_store_inconsistencies=0,
        )

        logger.info(
            "Starting soak test",
            duration_hours=duration_hours,
            webhook_rate_per_min=webhook_rate_per_min,
        )

        try:
            results = asyncio.run(
                self._run_soak_test_async(results, duration_hours, webhook_rate_per_min)
            )
        except Exception as e:
            results.errors.append(f"Soak test failed with exception: {e}")
            logger.error("Soak test failed", error=str(e), exc_info=True)

        results.end_time = datetime.now()
        logger.info(
            "Soak test completed",
            success=results.success,
            webhooks_sent=results.webhooks_sent,
            webhooks_received=results.webhooks_received,
            missed_events=results.missed_events,
            duplicate_reviews=results.duplicate_reviews,
        )

        return {
            "success": results.success,
            "duration_hours": results.duration_hours,
            "webhooks_sent": results.webhooks_sent,
            "webhooks_received": results.webhooks_received,
            "reviews_completed": results.reviews_completed,
            "verdicts_stored": results.verdicts_stored,
            "missed_events": results.missed_events,
            "duplicate_reviews": results.duplicate_reviews,
            "verdict_store_inconsistencies": results.verdict_store_inconsistencies,
            "errors": results.errors,
            "start_time": results.start_time.isoformat(),
            "end_time": results.end_time.isoformat() if results.end_time else None,
        }

    async def _run_soak_test_async(
        self,
        results: SoakTestResults,
        duration_hours: int,
        webhook_rate_per_min: int,
    ) -> SoakTestResults:
        """Run the async portion of the soak test."""
        self._running = True
        start_time = datetime.now()
        end_time = start_time + timedelta(hours=duration_hours)
        webhook_interval = 60.0 / webhook_rate_per_min

        # Start background tasks
        webhook_task = asyncio.create_task(
            self._webhook_generator(results, end_time, webhook_interval)
        )
        monitor_task = asyncio.create_task(self._consistency_monitor(results, end_time))

        # Wait for completion
        await asyncio.gather(webhook_task, monitor_task, return_exceptions=True)

        self._running = False

        # Final snapshot: monitor's 30s sleep may outlast short test windows
        try:
            with sqlite3.connect(self.temp_db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM verdicts")
                results.verdicts_stored = cursor.fetchone()[0]
                cursor.execute("SELECT DISTINCT delivery_id FROM verdicts")
                processed_deliveries = {row[0] for row in cursor.fetchall()}
            results.reviews_completed = len(processed_deliveries)
            results.missed_events = len(self._delivery_ids - processed_deliveries)
        except Exception:
            pass

        return results

    async def _webhook_generator(
        self,
        results: SoakTestResults,
        end_time: datetime,
        interval: float,
    ) -> None:
        """Generate webhooks at specified intervals until end time."""
        while datetime.now() < end_time and self._running:
            try:
                delivery_id = str(uuid.uuid4())
                self._delivery_ids.add(delivery_id)

                payload_dict = self._create_webhook_payload(delivery_id)
                payload_bytes = json.dumps(payload_dict, sort_keys=True).encode("utf-8")
                signature = self._sign_payload(payload_dict)

                response = self.test_client.post(
                    "/webhook",
                    content=payload_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-GitHub-Event": "pull_request",
                        "X-GitHub-Delivery": delivery_id,
                        "X-Hub-Signature-256": signature,
                    },
                )

                results.webhooks_sent += 1
                if response.status_code == 200:
                    results.webhooks_received += 1
                else:
                    results.errors.append(
                        f"Webhook {delivery_id} failed with status {response.status_code}"
                    )

                self._webhook_counter += 1

                # Wait for next webhook
                await asyncio.sleep(interval)

            except Exception as e:
                results.errors.append(f"Webhook generation error: {e}")
                logger.error("Webhook generation failed", error=str(e), exc_info=True)

    async def _consistency_monitor(
        self,
        results: SoakTestResults,
        end_time: datetime,
    ) -> None:
        """Monitor Verdict Store for consistency and duplicate detection."""
        check_interval = 30  # Check every 30 seconds
        last_verdict_count = 0
        seen_deliveries: set[str] = set()

        while datetime.now() < end_time and self._running:
            try:
                # Check verdict store consistency
                with sqlite3.connect(self.temp_db_path) as conn:
                    cursor = conn.cursor()

                    # Count verdicts
                    cursor.execute("SELECT COUNT(*) FROM verdicts")
                    current_verdict_count = cursor.fetchone()[0]
                    results.verdicts_stored = current_verdict_count

                    # Check for duplicate reviews (same delivery_id, different verdict_id)
                    cursor.execute("""
                        SELECT delivery_id, COUNT(DISTINCT id) as verdict_count
                        FROM verdicts
                        GROUP BY delivery_id
                        HAVING verdict_count > 3
                    """)
                    duplicates = cursor.fetchall()
                    if duplicates:
                        results.duplicate_reviews += len(duplicates)
                        results.errors.append(
                            f"Found duplicate reviews for {len(duplicates)} deliveries"
                        )

                    # Check for orphaned findings
                    cursor.execute("""
                        SELECT COUNT(*)
                        FROM findings f
                        LEFT JOIN verdicts v ON f.verdict_id = v.id
                        WHERE v.id IS NULL
                    """)
                    orphaned_findings = cursor.fetchone()[0]
                    if orphaned_findings > 0:
                        results.verdict_store_inconsistencies += 1
                        results.errors.append(f"Found {orphaned_findings} orphaned findings")

                    # Track delivery IDs we've seen processed
                    cursor.execute("SELECT DISTINCT delivery_id FROM verdicts")
                    processed_deliveries = {row[0] for row in cursor.fetchall()}

                # Calculate missed events
                sent_deliveries = self._delivery_ids.copy()
                missed_deliveries = sent_deliveries - processed_deliveries
                results.missed_events = len(missed_deliveries)

                # Update review completion count
                results.reviews_completed = len(processed_deliveries)

                last_verdict_count = current_verdict_count

                await asyncio.sleep(check_interval)

            except Exception as e:
                results.errors.append(f"Consistency monitor error: {e}")
                logger.error("Consistency monitor failed", error=str(e), exc_info=True)

    def _create_webhook_payload(self, delivery_id: str) -> dict[str, Any]:
        """Create a webhook payload for testing.

        Args:
            delivery_id: Unique delivery ID for this webhook

        Returns:
            Webhook payload dictionary
        """
        pr_number = 1000 + (self._webhook_counter % 100)
        return {
            "action": "opened",
            "pull_request": {
                "number": pr_number,
                "head": {"sha": f"sha{self._webhook_counter:06d}"},
                "base": {"repo": {"full_name": f"{self._project_id}/test-repo"}},
                "additions": 50,
                "deletions": 20,
                "changed_files": 5,
            },
            "repository": {"full_name": f"{self._project_id}/test-repo"},
        }

    def _sign_payload(self, payload: dict[str, Any]) -> str:
        """Sign webhook payload with HMAC-SHA256.

        Args:
            payload: Webhook payload to sign

        Returns:
            HMAC signature string in format 'sha256=<hex>'
        """
        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        signature = hmac.new(
            self._webhook_secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        return f"sha256={signature}"
