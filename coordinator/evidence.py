"""Interpret structured statement values without treating labels as proof."""


def supports_predicate(fact):
    value = fact.get('value')
    if not isinstance(value, dict):
        return False
    predicate = fact['predicate']
    if predicate == 'SUBMITTED':
        return value.get('submitted') is True
    if predicate == 'NOT_RECEIVED':
        return value.get('found') is False
    if predicate == 'RECEIVED':
        return value.get('found') is True or value.get('received') is True
    if predicate == 'DESTINATION':
        return isinstance(value.get('destination'), str) and bool(value['destination'].strip())
    return True
