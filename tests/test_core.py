from datetime import datetime
import pytest


def at(value):
    return datetime.fromisoformat(value + '+05:30')


def message(mid='m1', direction='inbound', body="I'll get back to you Friday.", sent='2026-10-05T14:00:00'):
    from backend.domain import Message
    return Message(id=mid, sender='Maya Chen', direction=direction, body=body, sent_at=at(sent), attachments=[])


def assessment(items=None, **kwargs):
    from backend.domain import Assessment
    return Assessment(is_sales_related=True, lifecycle='open', buyer_intent='high', summary='Enterprise evaluation.',
                      blockers=[], open_items=items or [], recommendations=[], ambiguity_notes=[],
                      non_substantive_message_ids=[], proposal_message_id=None, deferral=None, **kwargs)


def item(**kwargs):
    from backend.domain import OpenItem
    fields = dict(description='Return legal review', kind='commitment', owner='prospect', important=True,
                  material=True, urgent=False, evidence_message_ids=['m1'], deadline={'expression':'Friday','message_id':'m1'})
    fields.update(kwargs)
    return OpenItem(**fields)


@pytest.mark.parametrize('expression,expected', [
    ('tomorrow','2026-10-06T17:00:00'), ('Friday','2026-10-09T17:00:00'),
    ('next week','2026-10-12T17:00:00'), ('end of month','2026-10-31T17:00:00'),
    ('October 15','2026-10-15T17:00:00'), ('2026-10-09 at 15:30','2026-10-09T15:30:00'),
    ('Friday at 10 AM','2026-10-09T10:00:00'), ('in a week','2026-10-12T17:00:00'),
])
def test_date_resolution_uses_message_timestamp(expression, expected):
    from backend.dates import resolve_date
    result = resolve_date(expression, at('2026-10-05T14:00:00'))
    assert result.due_at == at(expected)


def test_ambiguous_date_is_not_invented():
    from backend.dates import resolve_date
    result = resolve_date('after our meeting', at('2026-10-05T14:00:00'))
    assert result.due_at is None and result.note


@pytest.mark.parametrize('expression',['after our demo Friday','Friday at 10 AM CST'])
def test_conditional_or_foreign_zone_dates_need_clarification(expression):
    from backend.dates import resolve_date
    assert resolve_date(expression,at('2026-10-05T14:00:00')).due_at is None


def test_ambiguous_explicit_window_does_not_become_a_fabricated_overdue_ask():
    from backend.policy import evaluate
    data=assessment([item(kind='ask',owner='us',material=False,deadline={'expression':'after our meeting','message_id':'m1'})])
    result=evaluate(data,[message(body='Send the details after our meeting.')],at('2026-10-09T18:00:00'))
    assert result['tier']=='T2'
    assert result['notes']


@pytest.mark.parametrize('clock,tier', [('2026-10-08T15:00:00','T3'),('2026-10-09T08:59:00','T3'),
    ('2026-10-09T09:00:00','T2'),('2026-10-09T16:59:00','T2'),('2026-10-09T17:00:00','T1')])
def test_friday_boundaries(clock, tier):
    from backend.policy import evaluate
    result = evaluate(assessment([item()]), [message()], at(clock))
    assert result['tier'] == tier
    if tier == 'T2': assert 'expected today' in result['next_action'].lower()
    if tier == 'T1': assert 'follow up' in result['next_action'].lower()


def test_saturation_is_direction_count_and_acknowledgement_is_semantic():
    from backend.policy import count_unanswered_outbound
    messages = [message('a','outbound'),message('b','outbound'),message('c','inbound'),message('d','outbound')]
    assert count_unanswered_outbound(messages, []) == 1
    assert count_unanswered_outbound(messages, ['c']) == 3


def test_saturation_does_not_hide_material_commitment():
    from backend.policy import evaluate
    messages = [message(),message('m2','outbound'),message('m3','outbound'),message('m4','outbound')]
    result = evaluate(assessment([item()]), messages, at('2026-10-09T18:00:00'))
    assert result['saturated'] and result['tier'] == 'T1'


def test_advisory_does_not_raise_tier():
    from backend.policy import evaluate
    data = assessment()
    data.recommendations = [{'description':'Offer a demo', 'evidence_message_ids':['m1']}]
    assert evaluate(data, [message()], at('2026-10-09T18:00:00'))['tier'] == 'T3'


def test_closed_with_unresolved_obligation_is_not_suppressed():
    from backend.policy import evaluate
    data = assessment([item(owner='us',kind='ask',deadline=None,urgent=True)])
    data.lifecycle = 'won'
    assert evaluate(data, [message()], at('2026-10-09T18:00:00'))['tier'] == 'T1'


def test_unknown_evidence_and_invented_date_are_rejected():
    from backend.domain import validate_evidence
    data = assessment([item(evidence_message_ids=['missing'])])
    with pytest.raises(ValueError, match='evidence'): validate_evidence(data, [message()])
    data = assessment([item(deadline={'expression':'2026-10-09','message_id':'m1'})])
    with pytest.raises(ValueError, match='verbatim'): validate_evidence(data, [message()])


def test_future_messages_and_time_independent_hash():
    from backend.domain import visible_messages, content_hash
    messages = [message(),message('future',sent='2026-10-10T12:00:00')]
    visible = visible_messages(messages, at('2026-10-09T18:00:00'))
    assert len(visible) == 1
    assert content_hash(visible, 'ollama', 'qwen', {}) == content_hash(visible, 'ollama', 'qwen', {})
    assert content_hash(visible, 'ollama', 'qwen', {}) != content_hash(messages, 'ollama', 'qwen', {})


def test_important_ask_age_uses_ask_timestamp_not_recent_acknowledgement():
    from backend.policy import evaluate
    data = assessment([item(kind='ask',owner='us',deadline=None)])
    messages = [message(),message('m2','outbound',sent='2026-10-09T17:00:00')]
    assert evaluate(data,messages,at('2026-10-09T18:00:00'))['tier'] == 'T1'


def test_deferral_suppresses_stale_proposal():
    from backend.policy import evaluate
    data = assessment()
    data.proposal_message_id = 'm1'
    data.deferral = {'expression':'next week','message_id':'m2'}
    messages = [message(direction='outbound', sent='2026-10-01T12:00:00'),
                message('m2',body='Please contact me next week.',sent='2026-10-08T12:00:00')]
    assert evaluate(data,messages,at('2026-10-09T18:00:00'))['tier'] == 'T3'


def test_material_flag_on_prospect_ask_does_not_invent_a_missed_commitment():
    from backend.policy import evaluate
    data=assessment([item(kind='ask',owner='prospect',important=True,material=True)])
    result=evaluate(data,[message(body='Please review this Friday.')],at('2026-10-09T18:00:00'))
    assert result['tier']=='T2'


def test_contact_date_starts_at_nine_while_delivery_is_due_at_seventeen():
    from backend.dates import resolve_date
    assert resolve_date('October 13',at('2026-10-07T12:00:00'),purpose='not_before').due_at==at('2026-10-13T09:00:00')
    assert resolve_date('October 13',at('2026-10-07T12:00:00')).due_at==at('2026-10-13T17:00:00')


@pytest.mark.parametrize('expression,source,expected',[
    ('Friday at 5 pm PST','2026-10-07T12:00:00','2026-10-10T06:30:00'),
    ('tomorrow at 10 AM PDT','2026-10-08T06:00:00','2026-10-08T22:30:00'),
    ('October 9 at 09:30 UTC+02:00','2026-10-07T12:00:00','2026-10-09T13:00:00'),
    ('October 9 at 9 AM America/New_York','2026-10-07T12:00:00','2026-10-09T18:30:00'),
])
def test_explicit_zone_anchoring(expression,source,expected):
    from backend.dates import resolve_date
    assert resolve_date(expression,at(source)).due_at==at(expected)


@pytest.mark.parametrize('expression',['November 1 at 1:30 AM America/New_York','March 8 at 2:30 AM America/New_York','Friday at 13 pm','Friday at 10 AM CST'])
def test_invalid_or_ambiguous_local_times_stay_unresolved(expression):
    from backend.dates import resolve_date
    r=resolve_date(expression,at('2026-01-01T12:00:00'))
    assert r.due_at is None and r.note


@pytest.mark.parametrize('phrase,expected',[
    ('Friday UTC+05:30','2026-10-09T17:00:00'),
    ('in 2 days at 3pm','2026-10-09T15:00:00'),
    ('tomorrow UTC+02:00 at 3pm','2026-10-08T18:30:00'),
])
@pytest.mark.parametrize('purpose',['due_by','not_before'])
def test_timezone_offset_is_not_a_delivery_clock(phrase,expected,purpose):
    from backend.dates import resolve_date
    if purpose=='not_before' and phrase=='Friday UTC+05:30':expected='2026-10-09T09:00:00'
    assert resolve_date(phrase,at('2026-10-07T12:00:00'),purpose=purpose).due_at==at(expected)
