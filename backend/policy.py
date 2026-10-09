from datetime import datetime, timedelta
from .domain import Assessment, DatePhrase, Message
from .dates import resolve_date, TZ
from zoneinfo import ZoneInfo
from .timezones import validate_timezone


def count_unanswered_outbound(messages: list[Message], non_substantive: list[str]) -> int:
    count = 0
    for message in sorted(messages, key=lambda m: (m.sent_at,m.id)):
        if message.direction == 'outbound': count += 1
        elif message.direction == 'inbound' and message.id not in non_substantive: count = 0
    return count


def evaluate(data: Assessment, messages: list[Message], as_of: datetime, *, profile='sales', timezone='Asia/Kolkata') -> dict:
    zone=ZoneInfo(validate_timezone(timezone))
    now = as_of.astimezone(zone)
    by_id = {m.id:m for m in messages}
    notes = list(data.ambiguity_notes)
    def resolve(phrase,purpose="due_by"):
        if not phrase: return None
        if isinstance(phrase,dict): phrase = DatePhrase(**phrase)
        source=by_id[phrase.message_id]
        timestamp=source.authored_at or source.sent_at
        source_zone=source.authored_at.tzinfo if source.authored_at else source.sent_at.tzinfo if profile=='sales' else None
        result = resolve_date(phrase.expression,timestamp,purpose=purpose,default_timezone=timezone,source_zone=source_zone)
        if result.note: notes.append(result.note)
        if source.authored_at:notes.append('Relative dates use the original email Date-header timezone; explicit deadline zones take precedence.')
        elif profile=='general':notes.append(f'No sender timezone metadata: relative dates use the selected fallback {timezone}.')
        return result
    due_items = []
    for item in data.open_items:
        resolved=resolve(item.deadline)
        due_at=resolved.due_at if resolved else None
        age = now - (by_id[item.action_evidence.message_id].sent_at if item.action_evidence else min(by_id[mid].sent_at for mid in item.evidence_message_ids))
        overdue = due_at is not None and now >= due_at
        due_today = bool(resolved and resolved.attention_start and resolved.day_end and resolved.attention_start<=now<resolved.day_end)
        due_items.append({**item.model_dump(mode='json'), 'obligation_id':item.obligation_id,'due_at':due_at.isoformat() if due_at else None,
                          'overdue':overdue,'due_today':due_today,'age_hours':round(age.total_seconds()/3600,1)})
    count = count_unanswered_outbound(messages,data.non_substantive_message_ids)
    saturated = count >= 3
    deferral=resolve(data.deferral,"not_before")
    defer_at=deferral.due_at if deferral else None
    reasons, evidence, tier = [], [], 'T3'
    next_action = 'No action needed now. Monitor for a substantive reply.'

    if profile=='general' and (data.category in ['promotion','spam'] or (not due_items and not data.deferral and data.conversation_state in ['closed','informational'])):
        tier='T4';reasons=['Promotional or spam mail has no required personal action.' if data.category in ['promotion','spam'] else 'Informational or completed conversation with no remaining obligation.']
        next_action='No action needed.'
    elif profile=='sales' and (not data.is_sales_related or (data.lifecycle in ['won','lost'] and not due_items)):
        tier='T4'; reasons=['Not commercially relevant.' if not data.is_sales_related else 'Conversation is closed with no remaining obligation.']
        next_action='No sales follow-up needed.'
    else:
        critical, routine = [], []
        for item in due_items:
            # material explicitly means a material commitment in the extraction contract.
            if item['overdue'] and ((item['kind']=='commitment' and item['material']) or (item['owner']=='us' and item['important'])):
                critical.append((item,'A material commitment or important obligation is overdue.'))
            elif item['owner']=='us' and item['urgent'] and (not item['due_at'] or item['due_today'] or item['overdue']):
                critical.append((item,'An explicit urgent action is required from us.'))
            elif item['owner']=='us' and item['kind']=='ask' and item['important'] and item['age_hours']>=48 and item['deadline'] is None:
                critical.append((item,'An important request has been unanswered for at least 48 hours.' if profile=='general' else 'An important buyer question has been unanswered for at least 48 hours.'))
            elif item['due_today'] or item['overdue']:
                routine.append((item,'A response or deliverable is expected today.' if not item['overdue'] else 'A routine obligation is overdue.'))
            elif item['owner']=='us' and not item['due_at']:
                routine.append((item,'An unresolved request needs our response.' if profile=='general' else 'An unresolved buyer request needs our response.'))
        chosen = critical or routine
        if chosen:
            tier='T1' if critical else 'T2'
            reasons=[f"{reason} {i['description']}" for i,reason in chosen]
            evidence=list(dict.fromkeys(mid for i,_ in chosen for mid in i['evidence_message_ids']))
            overdue = next((i for i,_ in chosen if i['overdue']),None)
            if overdue:
                next_action = ('Follow up: ' if overdue['owner']=='prospect' else 'Deliver or update the commitment: ') + overdue['description']
            elif chosen[0][0]['due_today'] and chosen[0][0]['owner']=='prospect':
                next_action='Expected today. Monitor and be prepared to follow up: '+chosen[0][0]['description']
            else: next_action=chosen[0][0]['description']
        elif data.deferral and (defer_at is None or now < defer_at):
            reasons=['The other party requested a later follow-up. Respect the agreed waiting period.' if profile=='general' else 'The prospect requested a later follow-up. Respect the agreed waiting period.']
            next_action='Wait until the agreed follow-up date.' if defer_at else 'Clarify the follow-up date before chasing.'
        elif data.deferral and defer_at and now >= defer_at:
            tier='T2'; reasons=['The agreed follow-up date has arrived.']; next_action='Reconnect at the agreed time.'
            evidence=[data.deferral.message_id] if isinstance(data.deferral,DatePhrase) else [data.deferral['message_id']]
        elif saturated:
            reasons=[f'{count} outbound messages have gone unanswered.']; next_action='Pause follow-ups until a substantive reply.' if profile=='general' else 'Pause outreach. Consider nurture rather than another reminder.'
        elif any(i['due_at'] and datetime.fromisoformat(i['due_at'])>now for i in due_items):
            reasons=['An explicit commitment is still in its agreed response window.']; next_action='Wait for the agreed commitment.'
        elif data.proposal_message_id:
            proposal=by_id[data.proposal_message_id]
            if now-proposal.sent_at >= timedelta(days=5):
                tier='T2'; reasons=['A proposal has awaited a substantive response for at least five days.']
                evidence=[proposal.id]; next_action='Send a concise follow-up on the proposal.'
            else: reasons=['The proposal is within its normal response window.']
        else: reasons=['No overdue obligation or immediate action is evident.' if profile=='general' else 'No overdue obligation or immediate sales action is evident.']
    return {'tier':tier,'reasons':reasons,'evidence_message_ids':evidence,'next_action':next_action,
            'open_items':due_items,'saturated':saturated,'unanswered_outbound_count':count,
            'notes':list(dict.fromkeys(notes)),'deferral_due_at':defer_at.isoformat() if defer_at else None,'profile':profile,'timezone':timezone}
