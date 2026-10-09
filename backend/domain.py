import hashlib
import json
import re
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, model_validator

PROMPT_VERSION = '2'
SCHEMA_VERSION = '1'
EXTRACTION_CONTRACT = 'grounded-obligations-v2-ledger'
GENERAL_EXTRACTION_CONTRACT = 'grounded-general-mail-v2-recipient-obligations'
MailCategory = Literal['sales','work','personal','support','notification','promotion','spam','unknown']
ConversationState = Literal['active','closed','informational']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Message(StrictModel):
    id: str
    sender: str
    recipients: list[str] | None = None
    direction: Literal['inbound', 'outbound', 'internal']
    body: str = Field(min_length=1, max_length=20000)
    sent_at: AwareDatetime
    attachments: list[str] = Field(default_factory=list)
    simulated: bool = False
    authored_at: AwareDatetime | None = None
    # Gmail source metadata stays out of semantic prompts and extraction hashes.
    gmail_label_ids: list[str] | None = Field(default=None,exclude=True)

    def model_dump(self, **kwargs):
        # Preserve hashes and authentic replay for legacy messages without new metadata.
        result=super().model_dump(**kwargs)
        if self.authored_at is None:result.pop('authored_at',None)
        if self.recipients is None:result.pop('recipients',None)
        return result


class DatePhrase(StrictModel):
    expression: str = Field(min_length=1)
    message_id: str


class EvidenceQuote(StrictModel):
    message_id: str
    quote: str = Field(min_length=1, max_length=1500)


class OpenItem(StrictModel):
    description: str
    kind: Literal['ask', 'commitment']
    owner: Literal['us', 'prospect']
    important: bool
    material: bool
    urgent: bool
    evidence_message_ids: list[str] = Field(min_length=1)
    deadline: DatePhrase | None
    action_evidence: EvidenceQuote | None = None
    ownership_evidence: EvidenceQuote | None = None
    urgency_evidence: EvidenceQuote | None = None

    @model_validator(mode='after')
    def derive_citation_index(self):
        # IDs are deterministic metadata. Preserve all supplied IDs so invalid
        # references still fail validation; add only explicitly cited sources.
        sources=[getattr(self,field,None) for field in ['action_evidence','ownership_evidence','urgency_evidence','resolution_evidence','deadline']]
        self.evidence_message_ids=list(dict.fromkeys([*self.evidence_message_ids,*[source.message_id for source in sources if source is not None]]))
        return self

    @property
    def obligation_id(self) -> str | None:
        if not self.action_evidence: return None
        # One sentence can request several distinct actions. IDs are local ledger
        # identifiers; changes to the model wording can change them across runs.
        value=self.action_evidence.message_id+'|'+self.action_evidence.quote.casefold()+'|'+' '.join(self.description.casefold().split())
        return hashlib.sha256(value.encode()).hexdigest()[:16]


class GroundedItem(OpenItem):
    action_evidence: EvidenceQuote
    ownership_evidence: EvidenceQuote
    urgency_evidence: EvidenceQuote | None


class ResolvedItem(GroundedItem):
    resolution_status: Literal['fulfilled','cancelled']
    resolution_evidence: EvidenceQuote


class Recommendation(StrictModel):
    description: str
    evidence_message_ids: list[str] = Field(min_length=1)


class LedgerObligation(GroundedItem):
    status: Literal['open','fulfilled','cancelled']
    resolution_evidence: EvidenceQuote | None

    @model_validator(mode='after')
    def resolution_matches_status(self):
        if self.status=='open' and self.resolution_evidence is not None:
            raise ValueError('An open obligation cannot also have resolution evidence.')
        if self.status!='open' and self.resolution_evidence is None:
            raise ValueError('A resolved obligation requires resolution evidence.')
        return self


class Assessment(StrictModel):
    is_sales_related: bool
    lifecycle: Literal['open','won','lost','deferred','unknown']
    buyer_intent: Literal['high','medium','low','unknown']
    summary: str
    reason: str | None = None
    blockers: list[str]
    open_items: list[OpenItem]
    recommendations: list[Recommendation]
    ambiguity_notes: list[str]
    non_substantive_message_ids: list[str]
    proposal_message_id: str | None
    deferral: DatePhrase | None
    resolved_items: list[ResolvedItem] = Field(default_factory=list)
    obligations: list[LedgerObligation] | None = None
    category: MailCategory | None = None
    conversation_state: ConversationState | None = None

    @model_validator(mode='before')
    @classmethod
    def derive_obligation_views(cls,value):
        if not isinstance(value,dict) or value.get('obligations') is None:return value
        value=dict(value);opened=[];resolved=[]
        for source in value['obligations']:
            entry=LedgerObligation.model_validate(source)
            fields=entry.model_dump(exclude={'status','resolution_evidence'})
            if entry.status=='open':opened.append(fields)
            else:resolved.append({**fields,'resolution_status':entry.status,'resolution_evidence':entry.resolution_evidence.model_dump()})
        for key,model,expected in [('open_items',OpenItem,opened),('resolved_items',ResolvedItem,resolved)]:
            if key in value and [model.model_validate(i).model_dump() for i in value[key]]!=expected:
                raise ValueError('Derived obligation views must match the original ledger.')
            value[key]=expected
        return value


class ExtractionAssessment(StrictModel):
    is_sales_related: bool
    lifecycle: Literal['open','won','lost','deferred','unknown']
    buyer_intent: Literal['high','medium','low','unknown']
    summary: str
    reason: str | None = None
    blockers: list[str]
    obligations: list[LedgerObligation]
    recommendations: list[Recommendation]
    ambiguity_notes: list[str]
    non_substantive_message_ids: list[str]
    proposal_message_id: str | None
    deferral: DatePhrase | None

    def assessment(self):return Assessment.model_validate(self.model_dump())


class GeneralExtractionAssessment(ExtractionAssessment):
    category: MailCategory
    conversation_state: ConversationState


def visible_messages(messages: list[Message], as_of: datetime) -> list[Message]:
    return sorted((m for m in messages if m.sent_at <= as_of), key=lambda m: (m.sent_at, m.id))


def content_hash(messages: list[Message], provider: str, model: str, context: dict) -> str:
    value = {'messages': [m.model_dump(mode='json') for m in messages], 'provider': provider,
             'model': model, 'context': context, 'prompt': PROMPT_VERSION, 'schema': SCHEMA_VERSION}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def evidence_text(text: str) -> str:
    """Ignore whitespace and smart-quote typography; preserve words and other punctuation."""
    quotes=str.maketrans({'\u2018':"'",'\u2019':"'",'\u201c':'"','\u201d':'"'})
    return ' '.join(text.translate(quotes).casefold().split())


def validate_evidence(data: Assessment, messages: list[Message], *, require_grounded=False) -> None:
    known = {m.id: m for m in messages}
    def check(ids):
        if any(mid not in known for mid in ids):
            raise ValueError('Unknown evidence message ID in model response.')
    def check_date(phrase):
        if phrase is None: return
        check([phrase.message_id])
        if not evidence_text(phrase.expression) or evidence_text(phrase.expression) not in evidence_text(known[phrase.message_id].body):
            raise ValueError(f'Date expression {phrase.expression!r} must be verbatim in message {phrase.message_id}; calculated dates or wrong source IDs are rejected.')
    for entry in [*data.open_items, *data.resolved_items, *data.recommendations]:
        check(entry.evidence_message_ids)
    seen=set()
    def check_quote(quote, entry):
        if quote is None: return
        check([quote.message_id])
        if not evidence_text(quote.quote) or evidence_text(quote.quote) not in evidence_text(known[quote.message_id].body):
            raise ValueError('Evidence quote must match its source message wording (whitespace and smart-quote differences are allowed).')
        if quote.message_id not in entry.evidence_message_ids:
            raise ValueError('Evidence quote must reference the obligation evidence IDs.')
    for entry in [*data.open_items,*data.resolved_items]:
        check_date(entry.deadline)
        if require_grounded and (entry.action_evidence is None or entry.ownership_evidence is None):
            raise ValueError('Obligation grounding requires action and ownership evidence.')
        if require_grounded and entry.urgent and entry.urgency_evidence is None:
            raise ValueError('Explicit urgency requires urgency evidence.')
        for quote in [entry.action_evidence,entry.ownership_evidence,entry.urgency_evidence]: check_quote(quote,entry)
        if require_grounded and entry.ownership_evidence:
            q=entry.ownership_evidence
            author=known[q.message_id].direction
            # Only direct, first-person future promises establish the sender as performer.
            # Requests, reported speech, and ambiguous ownership remain semantic judgments.
            first_person=re.match(r"^(?:i|we)(?: will|['']ll| promise| commit| am going to| are going to)\b",' '.join(q.quote.split()).replace(chr(8217), "'"),re.I)
            if first_person and author in ['inbound','outbound']:
                expected='us' if author=='outbound' else 'prospect'
                if entry.owner!=expected: raise ValueError('Direct first-person ownership evidence contradicts message direction.')
        oid=entry.obligation_id
        if oid and oid in seen: raise ValueError('An obligation cannot appear twice or be both open and resolved.')
        if oid: seen.add(oid)
        if isinstance(entry,ResolvedItem):
            check([entry.resolution_evidence.message_id])
            if not evidence_text(entry.resolution_evidence.quote) or evidence_text(entry.resolution_evidence.quote) not in evidence_text(known[entry.resolution_evidence.message_id].body):
                raise ValueError('Resolution quote must match its source message wording (whitespace and smart-quote differences are allowed).')
            if known[entry.resolution_evidence.message_id].sent_at < known[entry.action_evidence.message_id].sent_at:
                raise ValueError('An obligation cannot be resolved before it was created.')
    check_date(data.deferral)
    if data.proposal_message_id:
        check([data.proposal_message_id])
        if known[data.proposal_message_id].direction != 'outbound':
            raise ValueError('Proposal evidence must be an outbound message.')
    check(data.non_substantive_message_ids)
    # Direction is authoritative metadata. An outbound acknowledgement annotation
    # has no effect on the inbound reset logic, so it cannot invalidate an otherwise valid extraction.


def validate_history(previous: Assessment, current: Assessment, messages: list[Message]) -> None:
    known={m.id for m in messages}
    prior=[i.action_evidence for i in [*previous.open_items,*previous.resolved_items]
           if i.action_evidence and i.action_evidence.message_id in known]
    now=[i.action_evidence for i in [*current.open_items,*current.resolved_items] if i.action_evidence]
    candidates=[[j for j,q in enumerate(now) if q.message_id==origin.message_id and
                 (evidence_text(q.quote) in evidence_text(origin.quote) or evidence_text(origin.quote) in evidence_text(q.quote))]
                for origin in prior]
    # A current row may retain only one earlier obligation, even if it quotes
    # a whole sentence containing several asks. Find a one-to-one correspondence.
    matched={}
    def assign(index,seen):
        for target in candidates[index]:
            if target in seen:continue
            seen.add(target)
            if target not in matched or assign(matched[target],seen):
                matched[target]=index;return True
        return False
    for index in range(len(prior)):
        if not assign(index,set()):
            raise ValueError('A previously evidenced obligation disappeared without individually retained history or resolution evidence. Review or retry extraction.')
