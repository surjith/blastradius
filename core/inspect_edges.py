from pathlib import Path

from core.shopify_graph import ShopifyGraph

ONTO = Path("data/shopify_ontology.ttl")
INST = Path("data/synthetic_instances.ttl")

src = "https://example.com/shopify-inst#prod_mug"
dst = "https://example.com/shopify-inst#mf_prod_mug_campaign"

sg = ShopifyGraph.from_ttl(ONTO, INST)
G = sg.nx_graph

print("Edges src -> dst:")
found = False
for s, t, k, d in G.out_edges(src, keys=True, data=True):
    if t == dst:
        found = True
        print(
            f"{s} -[{d.get('relation')} / {d.get('predicate_uri')} | key={k}]-> {t}"
        )
        print("  full edge data:", d)

print("FOUND" if found else "NOT FOUND")

print("\nAll OUT edges from src:")
for s, t, k, d in G.out_edges(src, keys=True, data=True):
    print(f"{s} -[{d.get('relation')} / {d.get('predicate_uri')} | key={k}]-> {t}")
