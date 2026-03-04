"""Tests for src.metadata — extract_metadata and classify_memory_type."""

from __future__ import annotations

from src.metadata import classify_memory_type, extract_metadata

# ===== extract_metadata =====


class TestExtractMetadata:
    def test_word_count(self):
        result = extract_metadata("hello world foo bar")
        assert result["word_count"] == 4

    def test_word_count_empty(self):
        result = extract_metadata("")
        assert result["word_count"] == 0

    def test_urls_detected(self):
        result = extract_metadata("check https://example.com and http://foo.bar/baz")
        assert result["urls"] == ["https://example.com", "http://foo.bar/baz"]

    def test_no_urls_key_when_none(self):
        result = extract_metadata("no links here")
        assert "urls" not in result

    def test_mentions_detected(self):
        result = extract_metadata("talked to @alice and @bob about it")
        assert result["mentions"] == ["alice", "bob"]

    def test_no_mentions_key_when_none(self):
        result = extract_metadata("no mentions here")
        assert "mentions" not in result

    def test_dates_iso_detected(self):
        result = extract_metadata("meeting on 2024-01-15 and 2024-02-20")
        assert result["referenced_dates"] == ["2024-01-15", "2024-02-20"]

    def test_dates_slash_detected(self):
        result = extract_metadata("due by 1/15/2024 and 12/31/24")
        assert result["referenced_dates"] == ["1/15/2024", "12/31/24"]

    def test_no_dates_key_when_none(self):
        result = extract_metadata("no dates here")
        assert "referenced_dates" not in result

    def test_indexed_at_present(self):
        result = extract_metadata("anything")
        assert "indexed_at" in result
        # Should be an ISO timestamp string
        assert "T" in result["indexed_at"]

    def test_complex_content(self):
        content = (
            "Met with @alice on 2024-03-01 to discuss "
            "https://example.com/project — need to follow up"
        )
        result = extract_metadata(content)
        assert result["word_count"] > 0
        assert "urls" in result
        assert "mentions" in result
        assert "referenced_dates" in result
        assert "indexed_at" in result


# ===== classify_memory_type =====


class TestClassifyMemoryType:
    def test_task_keywords(self):
        assert classify_memory_type("todo: fix the bug") == "task"
        assert classify_memory_type("I need to deploy by deadline") == "task"
        assert classify_memory_type("task: review PR") == "task"
        assert classify_memory_type("I should update the docs") == "task"
        assert classify_memory_type("I must finish this") == "task"

    def test_idea_keywords(self):
        assert classify_memory_type("idea: build a chatbot") == "idea"
        assert classify_memory_type("what if we used GraphQL?") == "idea"
        assert classify_memory_type("maybe we could try React") == "idea"
        assert classify_memory_type("concept: microservices migration") == "idea"
        assert classify_memory_type("brainstorm session notes") == "idea"

    def test_idea_with_task_keyword_matches_task_first(self):
        # "should" is a task keyword and is checked before "maybe we"
        assert classify_memory_type("maybe we should try React") == "task"

    def test_reference_keywords(self):
        assert classify_memory_type("check http://docs.example.com") == "reference"
        assert classify_memory_type("visit https://github.com") == "reference"
        assert classify_memory_type("reference: RFC 7519") == "reference"
        assert classify_memory_type("link: architecture diagram") == "reference"
        assert classify_memory_type("source: internal wiki") == "reference"

    def test_decision_keywords(self):
        assert classify_memory_type("decided to go with Postgres") == "decision"
        assert classify_memory_type("decision: use FastMCP") == "decision"
        assert classify_memory_type("we chose TypeScript") == "decision"
        assert classify_memory_type("going with option A") == "decision"
        assert classify_memory_type("picked the blue theme") == "decision"

    def test_preference_keywords(self):
        assert classify_memory_type("I prefer dark mode") == "preference"
        assert classify_memory_type("I always use vim") == "preference"
        assert classify_memory_type("I never eat sushi") == "preference"
        assert classify_memory_type("I like Python") == "preference"
        assert classify_memory_type("I hate meetings") == "preference"
        assert classify_memory_type("I want a new laptop") == "preference"

    def test_person_note_keywords(self):
        assert classify_memory_type("met with John yesterday") == "person_note"
        assert classify_memory_type("spoke to Sarah about the project") == "person_note"
        assert classify_memory_type("talked to Bob on the phone") == "person_note"
        assert classify_memory_type("Alice said that it was ready") == "person_note"
        assert classify_memory_type("person: Dave — engineering lead") == "person_note"

    def test_default_observation(self):
        assert classify_memory_type("the sky is blue") == "observation"
        assert classify_memory_type("Python 3.12 was released") == "observation"
        assert classify_memory_type("") == "observation"

    def test_first_match_wins(self):
        # "todo" matches task before anything else
        assert classify_memory_type("todo: check https://example.com") == "task"
        # "idea:" matches before "http"
        assert classify_memory_type("idea: see https://example.com") == "idea"
