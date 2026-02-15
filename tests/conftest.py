from pathlib import Path
import pytest

from core.rdf_loader import load_rdf_file
from core.nx_builder import rdf_to_networkx

DATA_DIR = Path("data")


@pytest.fixture(scope="session")
def rdf_graph():
    return load_rdf_file(
        DATA_DIR / "shopify_ontology.ttl",
        DATA_DIR / "synthetic_instances.ttl",
    )


@pytest.fixture(scope="session")
def nx_build(rdf_graph):
    return rdf_to_networkx(rdf_graph)


@pytest.fixture(scope="session")
def nx_graph(nx_build):
    return nx_build.nx_graph
