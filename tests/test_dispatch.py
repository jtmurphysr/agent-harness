"""Tests for reviewers/dispatch.py - parallel reviewer invocation."""

import asyncio
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from github.pr import PRDiff
from reviewers.dispatch import DispatchError, ReviewerDispatcher, ReviewResult
from reviewers.models import ModelConfig, ModelResolver


@pytest.fixture
def mock_model_resolver():
    """Mock ModelResolver for testing."""
    resolver = Mock(spec=ModelResolver)
    resolver.resolve_model.return_value = ModelConfig(
        model_class="code_review",
        model_name="claude-3-5-sonnet-20241022",
        temperature=0.3,
        max_tokens=4096,
    )
    return resolver


@pytest.fixture
def sample_pr_diff():
    """Sample PRDiff for testing."""
    return PRDiff(
        pr_number=123,
        pr_sha="abc123",
        pr_size_lines=50,
        diff_content="@@ -1,3 +1,3 @@\n-old line\n+new line\n",
        changed_files=["src/main.py", "tests/test_main.py"],
    )


@pytest.fixture
def sample_project_context():
    """Sample project context for testing."""
    return {
        "project": {"name": "test-project"},
        "monthly_cost_cap_usd": 100.0,
        "reviewers": {
            "engineer": {
                "enabled": True,
                "model_class": "code_review",
            },
            "architect": {
                "enabled": True,
                "model_class": "structural_review",
            },
            "sre": {
                "enabled": True,
                "model_class": "adversarial_review",
            },
        },
    }


@pytest.fixture
def temp_agent_files(tmp_path):
    """Create temporary agent files for testing."""
    agent_files = {}

    for reviewer in ["engineer", "architect", "sre"]:
        agent_file = tmp_path / f"{reviewer}.md"
        agent_file.write_text(f"""<!-- GENERATED FILE — DO NOT EDIT -->
<!-- Source: {reviewer}.template.md v1.4.2 + project_context.md -->

# {reviewer.title()} Review Agent

You are the {reviewer} reviewer for this project.
Provide your review in the following format:

## Good
What was done well

## Bad  
Issues that need fixing

## Ugly
Critical problems

## Closing Question
One question for the team
""")
        agent_files[reviewer] = agent_file

    return agent_files


class TestReviewerDispatcher:
    """Test ReviewerDispatcher class."""

    def test_init(self, mock_model_resolver):
        """Test ReviewerDispatcher initialization."""
        dispatcher = ReviewerDispatcher(mock_model_resolver)
        assert dispatcher.model_resolver is mock_model_resolver
        assert isinstance(dispatcher._cost_tracker, dict)

    @pytest.mark.asyncio
    async def test_dispatch_reviewers_all_enabled(
        self, mock_model_resolver, temp_agent_files, sample_pr_diff, sample_project_context
    ):
        """Test dispatching all enabled reviewers successfully."""
        dispatcher = ReviewerDispatcher(mock_model_resolver)

        # Mock the single reviewer dispatch to return successful results
        mock_results = [
            ReviewResult(
                reviewer="engineer",
                raw_response="## Good\nLooks good\n## Bad\nNothing\n## Ugly\nNothing\n## Closing Question\nAny concerns?",
                template_version="1.4.2",
                duration_ms=1000,
            ),
            ReviewResult(
                reviewer="architect",
                raw_response="## Good\nGood structure\n## Bad\nNothing\n## Ugly\nNothing\n## Closing Question\nScalable?",
                template_version="1.4.2",
                duration_ms=1200,
            ),
            ReviewResult(
                reviewer="sre",
                raw_response="## Good\nSecure\n## Bad\nNothing\n## Ugly\nNothing\n## Closing Question\nMonitorable?",
                template_version="1.4.2",
                duration_ms=800,
            ),
        ]

        with patch.object(dispatcher, "_dispatch_single_reviewer") as mock_dispatch:
            mock_dispatch.side_effect = mock_results

            results = await dispatcher.dispatch_reviewers(
                temp_agent_files, sample_pr_diff, sample_project_context
            )

            assert len(results) == 3
            assert all(isinstance(result, ReviewResult) for result in results)
            assert [r.reviewer for r in results] == ["engineer", "architect", "sre"]
            assert mock_dispatch.call_count == 3

    @pytest.mark.asyncio
    async def test_dispatch_reviewers_parallel_execution(
        self, mock_model_resolver, temp_agent_files, sample_pr_diff, sample_project_context
    ):
        """Test that reviewers are executed in parallel."""
        dispatcher = ReviewerDispatcher(mock_model_resolver)

        # Mock delay to verify parallel execution
        async def mock_reviewer(*args, **kwargs):
            await asyncio.sleep(0.1)  # Simulate work
            reviewer_name = args[0]
            return ReviewResult(
                reviewer=reviewer_name,
                raw_response="Mock response",
                template_version="1.4.2",
                duration_ms=100,
            )

        with patch.object(dispatcher, "_dispatch_single_reviewer", side_effect=mock_reviewer):
            import time

            start_time = time.time()

            results = await dispatcher.dispatch_reviewers(
                temp_agent_files, sample_pr_diff, sample_project_context
            )

            end_time = time.time()
            total_time = end_time - start_time

            # If executed serially, would take ~0.3s (3 * 0.1s)
            # If executed in parallel, should take ~0.1s
            assert total_time < 0.2, f"Execution took too long: {total_time}s"
            assert len(results) == 3

    @pytest.mark.asyncio
    async def test_dispatch_reviewers_partial_failure(
        self, mock_model_resolver, temp_agent_files, sample_pr_diff, sample_project_context
    ):
        """Test handling of partial reviewer failures."""
        dispatcher = ReviewerDispatcher(mock_model_resolver)

        async def mock_reviewer(reviewer_name, *args, **kwargs):
            if reviewer_name == "architect":
                raise DispatchError("Mock failure")
            return ReviewResult(
                reviewer=reviewer_name,
                raw_response="Mock response",
                template_version="1.4.2",
                duration_ms=100,
            )

        with patch.object(dispatcher, "_dispatch_single_reviewer", side_effect=mock_reviewer):
            results = await dispatcher.dispatch_reviewers(
                temp_agent_files, sample_pr_diff, sample_project_context
            )

            # Should get results from engineer and sre, but not architect
            assert len(results) == 2
            reviewer_names = [r.reviewer for r in results]
            assert "engineer" in reviewer_names
            assert "sre" in reviewer_names
            assert "architect" not in reviewer_names

    @pytest.mark.asyncio
    async def test_dispatch_reviewers_all_fail(
        self, mock_model_resolver, temp_agent_files, sample_pr_diff, sample_project_context
    ):
        """Test when all reviewers fail."""
        dispatcher = ReviewerDispatcher(mock_model_resolver)

        with patch.object(
            dispatcher, "_dispatch_single_reviewer", side_effect=DispatchError("Mock failure")
        ), pytest.raises(DispatchError, match="All reviewers failed"):
            await dispatcher.dispatch_reviewers(
                temp_agent_files, sample_pr_diff, sample_project_context
            )

    @pytest.mark.asyncio
    async def test_dispatch_single_reviewer_success(
        self, mock_model_resolver, temp_agent_files, sample_pr_diff, sample_project_context
    ):
        """Test successful single reviewer dispatch."""
        dispatcher = ReviewerDispatcher(mock_model_resolver)

        with patch.object(dispatcher, "_invoke_claudegate_fallback", return_value="Mock response"):
            result = await dispatcher._dispatch_single_reviewer(
                "engineer",
                temp_agent_files["engineer"],
                sample_pr_diff,
                sample_project_context,
            )

            assert isinstance(result, ReviewResult)
            assert result.reviewer == "engineer"
            assert result.raw_response == "Mock response"
            assert result.template_version == "1.4.2"
            assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_dispatch_single_reviewer_missing_file(
        self, mock_model_resolver, sample_pr_diff, sample_project_context
    ):
        """Test single reviewer dispatch with missing agent file."""
        dispatcher = ReviewerDispatcher(mock_model_resolver)

        with pytest.raises(DispatchError, match="Agent file not found"):
            await dispatcher._dispatch_single_reviewer(
                "engineer",
                Path("/nonexistent/file.md"),
                sample_pr_diff,
                sample_project_context,
            )

    @pytest.mark.asyncio
    async def test_dispatch_single_reviewer_disabled(
        self, mock_model_resolver, temp_agent_files, sample_pr_diff, sample_project_context
    ):
        """Test single reviewer dispatch when reviewer is disabled."""
        dispatcher = ReviewerDispatcher(mock_model_resolver)

        # Disable the engineer reviewer
        sample_project_context["reviewers"]["engineer"]["enabled"] = False

        with pytest.raises(DispatchError, match="Reviewer engineer is disabled"):
            await dispatcher._dispatch_single_reviewer(
                "engineer",
                temp_agent_files["engineer"],
                sample_pr_diff,
                sample_project_context,
            )

    @pytest.mark.asyncio
    async def test_dispatch_single_reviewer_no_model_class(
        self, mock_model_resolver, temp_agent_files, sample_pr_diff, sample_project_context
    ):
        """Test single reviewer dispatch when no model class configured."""
        dispatcher = ReviewerDispatcher(mock_model_resolver)

        # Remove model class from engineer
        del sample_project_context["reviewers"]["engineer"]["model_class"]

        with pytest.raises(DispatchError, match="No model class configured"):
            await dispatcher._dispatch_single_reviewer(
                "engineer",
                temp_agent_files["engineer"],
                sample_pr_diff,
                sample_project_context,
            )

    @pytest.mark.asyncio
    async def test_dispatch_reviewers_inference_fallback(
        self, mock_model_resolver, temp_agent_files, sample_pr_diff, sample_project_context
    ):
        """Test fallback from local inference to Claudegate."""
        dispatcher = ReviewerDispatcher(mock_model_resolver)

        with (
            patch.object(
                dispatcher, "_invoke_local_inference", side_effect=Exception("Local failed")
            ),
            patch.object(
                dispatcher, "_invoke_claudegate_fallback", return_value="Claudegate response"
            ),
        ):
            result = await dispatcher._dispatch_single_reviewer(
                "engineer",
                temp_agent_files["engineer"],
                sample_pr_diff,
                sample_project_context,
            )

            assert result.raw_response == "Claudegate response"

    @pytest.mark.asyncio
    async def test_dispatch_reviewers_cost_cap_exceeded(
        self, mock_model_resolver, temp_agent_files, sample_pr_diff, sample_project_context
    ):
        """Test handling when cost cap is exceeded."""
        dispatcher = ReviewerDispatcher(mock_model_resolver)

        # Set cost tracker to exceed cap
        dispatcher._cost_tracker["test-project"] = 150.0  # Exceeds cap of 100.0

        with patch.object(
            dispatcher, "_invoke_local_inference", side_effect=Exception("Local failed")
        ), pytest.raises(DispatchError, match="Monthly cost cap.*exceeded"):
            await dispatcher._dispatch_single_reviewer(
                "engineer",
                temp_agent_files["engineer"],
                sample_pr_diff,
                sample_project_context,
            )

    def test_extract_template_version_found(self, mock_model_resolver):
        """Test extracting template version from agent file."""
        dispatcher = ReviewerDispatcher(mock_model_resolver)

        agent_content = """<!-- GENERATED FILE — DO NOT EDIT -->
<!-- Source: engineer.template.md v1.4.2 + project_context.md -->

# Engineer Review Agent
"""

        version = dispatcher._extract_template_version(agent_content)
        assert version == "1.4.2"

    def test_extract_template_version_not_found(self, mock_model_resolver):
        """Test extracting template version when not found."""
        dispatcher = ReviewerDispatcher(mock_model_resolver)

        agent_content = """# Engineer Review Agent

Some content without version info.
"""

        version = dispatcher._extract_template_version(agent_content)
        assert version == "unknown"

    @pytest.mark.asyncio
    async def test_invoke_local_inference_stub(self, mock_model_resolver):
        """Test local inference stub implementation."""
        dispatcher = ReviewerDispatcher(mock_model_resolver)

        with pytest.raises(Exception, match="Local inference not available"):
            await dispatcher._invoke_local_inference("prompt", Mock(), Mock())

    @pytest.mark.asyncio
    async def test_invoke_claudegate_fallback_success(
        self, mock_model_resolver, sample_pr_diff, sample_project_context
    ):
        """Test successful Claudegate fallback."""
        dispatcher = ReviewerDispatcher(mock_model_resolver)

        model_config = ModelConfig(
            model_class="code_review",
            model_name="claude-3-5-sonnet-20241022",
            temperature=0.3,
            max_tokens=4096,
        )

        response = await dispatcher._invoke_claudegate_fallback(
            "Test prompt", sample_pr_diff, model_config, sample_project_context
        )

        assert "## Good" in response
        assert "## Bad" in response
        assert "## Ugly" in response
        assert "## Closing Question" in response

        # Check cost tracking was updated
        assert "test-project" in dispatcher._cost_tracker
        assert dispatcher._cost_tracker["test-project"] == 0.10

    @pytest.mark.asyncio
    async def test_invoke_claudegate_fallback_cost_tracking(
        self, mock_model_resolver, sample_pr_diff, sample_project_context
    ):
        """Test cost tracking in Claudegate fallback."""
        dispatcher = ReviewerDispatcher(mock_model_resolver)

        model_config = ModelConfig(
            model_class="code_review",
            model_name="claude-3-5-sonnet-20241022",
            temperature=0.3,
            max_tokens=4096,
        )

        # Make multiple calls to test cost accumulation
        await dispatcher._invoke_claudegate_fallback(
            "Test prompt", sample_pr_diff, model_config, sample_project_context
        )
        await dispatcher._invoke_claudegate_fallback(
            "Test prompt", sample_pr_diff, model_config, sample_project_context
        )

        # Cost should have accumulated
        assert dispatcher._cost_tracker["test-project"] == 0.20


class TestReviewResult:
    """Test ReviewResult model."""

    def test_review_result_creation(self):
        """Test creating ReviewResult instance."""
        result = ReviewResult(
            reviewer="engineer",
            raw_response="Mock response",
            template_version="1.4.2",
            duration_ms=1000,
        )

        assert result.reviewer == "engineer"
        assert result.raw_response == "Mock response"
        assert result.template_version == "1.4.2"
        assert result.duration_ms == 1000


class TestDispatchError:
    """Test DispatchError exception."""

    def test_dispatch_error_creation(self):
        """Test creating DispatchError instance."""
        error = DispatchError("Test error message")
        assert str(error) == "Test error message"
        assert isinstance(error, Exception)
