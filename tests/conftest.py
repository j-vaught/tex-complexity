from __future__ import annotations

import pytest
import spacy
from spacy.language import Language


@pytest.fixture(scope="session")
def nlp() -> Language:
    return spacy.load("en_core_web_sm")
