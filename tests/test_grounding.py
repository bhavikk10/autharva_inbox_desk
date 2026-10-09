import pytest
from test_core import assessment,item,message,at


def grounded_item(**changes):
    from backend.domain import GroundedItem
    fields=item(kind='ask',owner='us',material=False,urgent=True,deadline=None).model_dump()
    fields.update(action_evidence={'message_id':'m1','quote':'Please confirm SCIM urgently.'},
                  ownership_evidence={'message_id':'m1','quote':'Please confirm SCIM urgently.'},
                  urgency_evidence={'message_id':'m1','quote':'urgently'})
    fields.update(changes)
    return GroundedItem(**fields)


def test_grounded_quotes_and_resolution_chronology():
    from backend.domain import ResolvedItem,validate_evidence
    m=message(body='Please confirm SCIM urgently.')
    done=message('m2','outbound','SCIM is included.',sent='2026-10-06T14:00:00')
    g=grounded_item()
    r=ResolvedItem(**g.model_dump(),resolution_evidence={'message_id':'m2','quote':'SCIM is included.'},resolution_status='fulfilled')
    data=assessment();data.resolved_items=[r]
    validate_evidence(data,[m,done],require_grounded=True)
    assert r.obligation_id==g.obligation_id
    with pytest.raises(ValueError,match='quote'):
        data.resolved_items=[r.model_copy(update={'resolution_evidence':r.resolution_evidence.model_copy(update={'quote':'Invented answer'})})]
        validate_evidence(data,[m,done],require_grounded=True)
    data.resolved_items=[r]
    with pytest.raises(ValueError,match='before'):
        validate_evidence(data,[m,done.model_copy(update={'sent_at':at('2026-10-04T12:00:00')})],require_grounded=True)


def test_citation_index_is_derived_from_explicit_source_references_without_rewriting_raw():
    import json
    from backend.domain import ExtractionAssessment,Assessment,validate_evidence
    ask=message(body='Please confirm SCIM urgently.')
    promise=message('m2','outbound','I will confirm SCIM tomorrow.',sent='2026-10-06T14:00:00')
    g=grounded_item(ownership_evidence={'message_id':'m2','quote':'I will confirm SCIM tomorrow.'},
        deadline={'expression':'tomorrow','message_id':'m2'})
    source=g.model_dump(mode='json');source['evidence_message_ids']=['m1'];source.update(status='open',resolution_evidence=None)
    payload=assessment().model_dump(mode='json',exclude={'open_items','resolved_items','obligations','category','conversation_state'})
    payload['obligations']=[source]
    raw=json.dumps(payload)
    parsed=ExtractionAssessment.model_validate_json(raw).assessment()
    assert parsed.open_items[0].evidence_message_ids==['m1','m2']
    validate_evidence(parsed,[ask,promise],require_grounded=True)
    assert json.loads(raw)['obligations'][0]['evidence_message_ids']==['m1']
    assert Assessment.model_validate_json(raw)==parsed
    payload['obligations'][0]['ownership_evidence']['message_id']='missing'
    invalid=ExtractionAssessment.model_validate(payload).assessment()
    with pytest.raises(ValueError,match='Unknown evidence'):validate_evidence(invalid,[ask,promise],require_grounded=True)


def test_grounding_rejects_missing_or_unrelated_support():
    from backend.domain import validate_evidence
    m=message(body='Please confirm SCIM urgently.')
    data=assessment([grounded_item()]);validate_evidence(data,[m],require_grounded=True)
    data.open_items=[grounded_item(urgency_evidence=None)]
    with pytest.raises(ValueError,match='urgency'):validate_evidence(data,[m],require_grounded=True)
    data.open_items=[grounded_item(ownership_evidence={'message_id':'m1','quote':'I promise a discount'})]
    with pytest.raises(ValueError,match='quote'):validate_evidence(data,[m],require_grounded=True)
    data.open_items=[item(deadline=None)]
    with pytest.raises(ValueError,match='grounding'):validate_evidence(data,[m],require_grounded=True)


def test_resolved_item_cannot_also_be_open():
    from backend.domain import ResolvedItem,validate_evidence
    g=grounded_item()
    data=assessment([g]);data.resolved_items=[ResolvedItem(**g.model_dump(),resolution_status='fulfilled',resolution_evidence={'message_id':'m2','quote':'SCIM is included.'})]
    with pytest.raises(ValueError,match='both'):validate_evidence(data,[message(body='Please confirm SCIM urgently.'),message('m2','outbound','SCIM is included.',sent='2026-10-06T14:00:00')],require_grounded=True)


def test_first_person_promise_owner_must_match_message_direction():
    from backend.domain import validate_evidence,GroundedItem
    m=message(body='I will send our approval Friday.')
    g=GroundedItem(**item(owner='us').model_dump(exclude={'action_evidence','ownership_evidence','urgency_evidence'}),action_evidence={'message_id':'m1','quote':'I will send our approval Friday.'},ownership_evidence={'message_id':'m1','quote':'I will send our approval Friday.'},urgency_evidence=None)
    with pytest.raises(ValueError,match='ownership'):validate_evidence(assessment([g]),[m],require_grounded=True)


def test_prior_obligation_cannot_silently_disappear():
    from backend.domain import validate_history
    g=grounded_item();m=message(body='Please confirm SCIM urgently.')
    with pytest.raises(ValueError,match='disappeared'):validate_history(assessment([g]),assessment(),[m])


def test_single_ledger_derives_closed_views_and_cannot_be_tampered():
    from backend.domain import Assessment,LedgerObligation
    from backend.policy import evaluate
    g=grounded_item()
    row=LedgerObligation(**g.model_dump(),status='fulfilled',resolution_evidence={'message_id':'m2','quote':'SCIM is included.'})
    payload=assessment().model_dump(exclude={'open_items','resolved_items','obligations'})
    payload['obligations']=[row.model_dump()]
    data=Assessment.model_validate(payload)
    assert data.open_items==[] and len(data.resolved_items)==1
    assert evaluate(data,[message(body='Please confirm SCIM urgently.'),message('m2','outbound','SCIM is included.',sent='2026-10-06T14:00:00')],at('2026-10-09T18:00:00'))['tier']=='T3'
    payload['open_items']=[g.model_dump()]
    with pytest.raises(ValueError,match='match the original ledger'):Assessment.model_validate(payload)


def test_two_distinct_actions_may_share_a_source_sentence():
    from backend.domain import validate_evidence
    body='Please send the contract and the price list urgently.'
    a=grounded_item(description='Send contract',action_evidence={'message_id':'m1','quote':body},ownership_evidence={'message_id':'m1','quote':body})
    b=a.model_copy(update={'description':'Send price list'})
    validate_evidence(assessment([a,b]),[message(body=body)],require_grounded=True)
    assert a.obligation_id!=b.obligation_id


def test_history_does_not_merge_two_prior_actions_into_one():
    from backend.domain import validate_history
    body='Please send the contract. Please send the price list.'
    a=grounded_item(description='Contract',urgent=False,action_evidence={'message_id':'m1','quote':'Please send the contract.'})
    b=grounded_item(description='Price list',urgent=False,action_evidence={'message_id':'m1','quote':'Please send the price list.'})
    merged=a.model_copy(update={'action_evidence':a.action_evidence.model_copy(update={'quote':body})})
    with pytest.raises(ValueError,match='disappeared'):
        validate_history(assessment([a,b]),assessment([merged]),[message(body=body)])


def test_grounding_accepts_only_whitespace_changes_to_real_quotes():
    from backend.domain import ResolvedItem,validate_evidence
    g=grounded_item()
    m=message(body='Please confirm\r\n  SCIM\u00a0urgently.')
    done=message('m2','outbound','SCIM is\n included.',sent='2026-10-06T14:00:00')
    data=assessment([g]);validate_evidence(data,[m],require_grounded=True)
    data.open_items=[]
    data.resolved_items=[ResolvedItem(**g.model_dump(),resolution_status='fulfilled',resolution_evidence={'message_id':'m2','quote':'SCIM is included.'})]
    validate_evidence(data,[m,done],require_grounded=True)
    data.resolved_items=[]
    data.open_items=[g.model_copy(update={'action_evidence':g.action_evidence.model_copy(update={'quote':'Please confirm SSO urgently.'})})]
    with pytest.raises(ValueError,match='quote'):validate_evidence(data,[m],require_grounded=True)


def test_history_matches_wrapped_quotes_without_merging_actions():
    from backend.domain import validate_history
    g=grounded_item();current=g.model_copy(update={'action_evidence':g.action_evidence.model_copy(update={'quote':'Please confirm\n SCIM urgently.'})})
    validate_history(assessment([g]),assessment([current]),[message(body='Please confirm SCIM urgently.')])


@pytest.mark.parametrize('field',['action_evidence','resolution_evidence'])
def test_whitespace_only_quotes_never_count_as_evidence(field):
    from backend.domain import ResolvedItem,validate_evidence
    g=grounded_item();m=message(body='Please confirm SCIM urgently.')
    if field=='action_evidence':
        data=assessment([g.model_copy(update={'action_evidence':g.action_evidence.model_copy(update={'quote':' \n\t '})})]);messages=[m]
    else:
        r=ResolvedItem(**g.model_dump(),resolution_status='fulfilled',resolution_evidence={'message_id':'m2','quote':' \n\t '})
        data=assessment();data.resolved_items=[r];messages=[m,message('m2','outbound','SCIM is included.',sent='2026-10-06T14:00:00')]
    with pytest.raises(ValueError,match='quote'):validate_evidence(data,messages,require_grounded=True)
