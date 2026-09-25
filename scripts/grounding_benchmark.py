"""Run from the repository root after installation."""
import argparse,json
from ega.evaluation.grounding import make_corpus,evaluate_corpus
from ega.config import load_config
p=argparse.ArgumentParser();p.add_argument('--corpus',default='examples/grounding_templates.jsonl')
p.add_argument('--generate',action='store_true');p.add_argument('--prose-only',action='store_true')
p.add_argument('--llm-config');p.add_argument('--output',default='results/grounding')
a=p.parse_args()
if a.generate:make_corpus(a.corpus,a.prose_only)
results=evaluate_corpus(a.corpus,a.output,load_config(a.llm_config).llm if a.llm_config else None)
print(json.dumps(results,indent=2))
