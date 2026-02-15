from pathlib import Path
from rdflib import Graph

def load_rdf_file(*ttl_paths: str | Path) -> Graph:
    """Load RDF data from one or more Turtle files into a single RDF graph.
    Args:
        *ttl_paths: One or more paths to Turtle (.ttl) files containing RDF data."""
    graph = Graph()
    for ttl_path in ttl_paths:
        ttl_path = Path(ttl_path)
        if not ttl_path.exists():
            raise FileNotFoundError(f"RDF file not found: {ttl_path}")
        graph.parse(ttl_path, format='turtle')
    return graph