"""Shared bounded saved-dialogue contract for the host and isolated evaluator."""
import json


def validate_payload(data):
    if not isinstance(data,dict) or set(data)!={'messages','success','criteria'}:
        raise ValueError('Saved conversation, success and criteria required')
    messages=data['messages'];criteria=data['criteria']
    if (not isinstance(messages,list) or not 2<=len(messages)<=40
        or not isinstance(criteria,dict) or not 1<=len(criteria)<=12
        or not isinstance(data['success'],str) or not 0<len(data['success'])<=2000):
        raise ValueError('Bounded saved dialogue required')
    if any(not isinstance(m,dict) or set(m)!={'role','content'} or m['role'] not in {'user','assistant'}
           or not isinstance(m['content'],str) or not 0<len(m['content'])<=4000 for m in messages):
        raise ValueError('Plain conversation messages required')
    if any(not isinstance(k,str) or not 0<len(k)<=100 or not isinstance(v,str) or not 0<len(v)<=2000 for k,v in criteria.items()):
        raise ValueError('Bounded named criteria required')
    if len(json.dumps(data).encode())>22000:raise ValueError('Saved conversation exceeds evaluation budget')
    return data
