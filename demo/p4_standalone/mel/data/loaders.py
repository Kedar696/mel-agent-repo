"""P1 - loaders, validation, junk reasons. Owner: P1."""
import json, pandas as pd
REQUIRED = ['insight_id','farmer_id','created_at','conversation_language','resolution_type','verification','asset']
def load_insights(path): return [json.loads(l) for l in open(path, encoding='utf-8')]
def load_farmers(path): return {r.farmer_id: r._asdict() for r in pd.read_csv(path).itertuples(index=False)}
def junk_reason(i):
    """TODO(P1, H+12): return a reason code for junk rows instead of just True/False."""
    if i.get('quality_flag') == 'junk': return 'flagged_junk'
    missing = [k for k in REQUIRED if i.get(k) in (None, '')]
    return ('missing:' + ','.join(missing)) if missing else None
def validate(obj, schema_name):
    """TODO(P1, H+4): load json/schemas/<schema_name>.schema.json (not in our upload yet) and use jsonschema."""
    return []
