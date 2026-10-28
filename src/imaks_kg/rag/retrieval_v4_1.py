"""V4.1 coverage semantics: unknown global coverage is not false evidence."""
from pathlib import Path
from .retrieval_v4 import source_packet,typed_candidates
from . import retrieval_v4 as prior, vector as v
VERSION='retrieval-v4.1-20261028'


def retrieve(question,*,use_dense=False,typed=True,call=v.api_call,dense=None):
    result=prior.retrieve(question,use_dense=use_dense,typed=typed,call=call,dense=dense)
    result['retrieval_version']=VERSION
    if not result['typed_queries']:
        result['coverage_complete']=None
        result['coverage_scope']='bounded retrieved excerpts; global completeness not established'
    else:
        result['coverage_scope']='source rows matching the logged typed query; not every fact in the corpus'
    return result


def retrieval_lock(use_dense=False):
    result=prior.retrieval_lock(use_dense)
    result['backend']=VERSION
    result['files'][str(Path(__file__).relative_to(v.REPO_ROOT))]=v.digest(Path(__file__).read_bytes())
    return result
