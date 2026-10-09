"""Hand-authored synthetic input only. Expected labels live separately."""
from .domain import Message

DEFAULT_AS_OF = '2026-10-09T18:00:00+05:30'
PRESETS = {'Thursday': '2026-10-08T15:00:00+05:30', 'Friday morning': '2026-10-09T10:00:00+05:30',
           'Friday evening': DEFAULT_AS_OF}


def seed_threads():
    rows=[]
    def thread(tid,company,subject,contact,value,messages):
        rows.append({'id':tid,'company':company,'subject':subject,'contact':contact,'deal_value':value,
                     'messages':[Message(id=f'{tid}-m{i+1}',sender='Alex Morgan' if direction=='outbound' else contact,
                          direction=direction,sent_at=f'2026-{stamp}:00+05:30',body=body,attachments=attachments).model_dump(mode='json')
                          for i,(stamp,direction,body,attachments) in enumerate(messages)]})
    thread('meridian','Meridian Health','SSO and SCIM for 240 seats','Maya Chen',72000,[
        ('10-05T10:00','inbound','We are evaluating 240 seats. Do you support SSO and SCIM provisioning? Both are required for our security approval.',[]),
        ('10-05T14:00','outbound','Yes, we support SSO via SAML and OIDC. The SSO overview is attached.', ['SSO-overview.pdf']),
        ('10-06T09:00','inbound','Thanks for the SSO details. Please also answer the SCIM question so we can finish the security review.',[])])
    thread('northstar','Northstar Systems','Legal review of the enterprise agreement','Daniel Ruiz',125000,[
        ('10-05T09:00','outbound','Here is the revised enterprise agreement for your legal review.', ['enterprise-agreement.pdf']),
        ('10-05T14:00','inbound',"The terms look good. I'll get back to you Friday with our legal team's decision. This is the final approval before we sign.",[])])
    thread('kinetic','Kinetic Labs','Contract needed today','Amara Okafor',54000,[
        ('10-09T11:00','inbound','We have budget approval. Please send the final contract today. We need to sign before our purchasing window closes.',[])])
    thread('evergreen','Evergreen Logistics','Procurement review in progress','Leah Patel',180000,[
        ('10-08T10:00','outbound','The revised quote and procurement questionnaire are attached.', ['quote.pdf','procurement.pdf']),
        ('10-08T12:00','inbound',"Everything we need is here. Procurement is reviewing it. I'll send you their decision next week; please wait until then.",[])])
    thread('harbor','Harbor Studio','Pilot proposal','Ethan Park',18000,[
        ('10-01T10:00','inbound','Please send a proposal for a 30-seat pilot.',[]),
        ('10-02T11:00','outbound','Here is the requested pilot proposal. Let me know what you think.', ['pilot-proposal.pdf'])])
    thread('atlas','Atlas Manufacturing','Promised security packet','Nadia Farouk',92000,[
        ('10-05T11:00','inbound','Please send your security packet. It is the only blocker to vendor approval.',[]),
        ('10-05T12:00','outbound',"I'll send the security packet tomorrow. Our audit team has the final version.",[]),
        ('10-08T16:00','outbound','Just acknowledging that I am checking with the audit team.',[])])
    thread('solstice','Solstice Energy','Technical walkthrough booked','Ravi Menon',48000,[
        ('10-07T10:00','inbound','Could we book a technical walkthrough?',[]),
        ('10-07T11:00','outbound','The technical walkthrough is booked for October 13 at 10 AM. The invitation is attached.', ['invite.ics']),
        ('10-07T12:00','inbound','Confirmed. We have no other questions before the walkthrough.',[])])
    thread('juniper','Juniper Retail','Workspace onboarding complete','Sofia Torres',30000,[
        ('10-03T10:00','inbound','The agreement is signed and payment is complete.', ['signed-agreement.pdf']),
        ('10-03T12:00','outbound','Your workspace is live and all onboarding documents are attached.', ['onboarding.pdf']),
        ('10-04T09:00','inbound','Everything is working. We have no outstanding requests. Thank you!',[])])
    thread('cobalt','Cobalt Partners','Decision on the evaluation','Ben Wallace',24000,[
        ('10-02T10:00','outbound','Would you like to proceed with the pilot?',[]),
        ('10-02T11:00','inbound','We selected another vendor. Please close this opportunity and do not follow up. No materials are outstanding.',[])])
    thread('signal','Signal Weekly','Your weekly industry briefing','Signal Weekly',None,[
        ('10-09T08:00','inbound','This week in identity technology: five industry stories. Manage your subscription or unsubscribe below.',[])])
    thread('people','People Operations','Holiday roster confirmation','People Operations',None,[
        ('10-08T09:00','internal','Please confirm your holiday roster for the internal office calendar. This is an HR message.',[])])
    thread('pine','Pine Advisory','Introduction to Autharva','Milan Shah',None,[
        ('10-01T09:00','outbound','Would you be interested in an introduction to our identity platform?',[]),
        ('10-04T09:00','outbound','Following up on my introduction. Is this relevant to your team?',[]),
        ('10-07T09:00','outbound','One last follow-up on the introduction. Happy to reconnect another time.',[])])
    thread('tessera','Tessera Design','Revisit after budget planning','Chloe Martin',36000,[
        ('10-06T09:00','outbound','The 60-seat proposal is attached.', ['proposal.pdf']),
        ('10-06T11:00','inbound','We are interested, but budget planning comes first. Please contact me October 15. We do not need anything before then.',[])])
    thread('valence','Valence Cloud','Renewal blocked by security review','Owen Brooks',210000,[
        ('10-08T14:00','inbound','Our renewal will be cancelled unless we receive the updated security questionnaire by Friday. Please treat this as urgent.',[])])
    thread('mosaic','Mosaic Learning','Pilot pricing clarification','Aisha Khan',12000,[
        ('10-09T16:00','inbound','We are considering a pilot. Can you explain the monthly pilot pricing? No deadline on our side.',[])])
    # Five held-out inputs. Do not tune the prompt against these outputs.
    thread('lumen','Lumen Networks','Two checks before approval','Noah Kim',88000,[
        ('10-05T09:00','inbound','Before approving the purchase, can you confirm data residency in India and send the DPA?',[]),
        ('10-05T11:00','outbound','Yes, India residency is supported. Our regional hosting note is attached.', ['hosting.pdf']),
        ('10-06T10:00','inbound','The hosting note answers residency. We still need the DPA to approve the purchase.',[])])
    thread('orbit','Orbit Robotics','Evaluation documents','Priya Desai',64000,[
        ('10-07T11:00','inbound','Please send the deployment checklist for our purchase evaluation.',[]),
        ('10-07T12:00','outbound',"I'll send the deployment checklist tomorrow.",[]),
        ('10-09T09:00','inbound','Any update on the checklist? We still need it for the evaluation.',[])])
    thread('cedar','Cedar Financial','Next budget window','Isabel Rossi',145000,[
        ('10-01T11:00','outbound','Our annual enterprise proposal is attached.', ['annual-proposal.pdf']),
        ('10-02T10:00','inbound','We want to revisit this in our next budget window. Please follow up at end of month. Nothing else is needed now.',[])])
    thread('drift','Drift Support','Help signing into my personal account','Jamie Lee',None,[
        ('10-07T09:00','inbound','I forgot my password for my personal account. Could support help me reset it? This is not a purchase or renewal request.',[]),
        ('10-07T10:00','outbound','The password reset link is attached. Please follow the instructions.', ['reset-instructions.txt']),
        ('10-07T11:00','inbound','That fixed it. Thanks!',[])])
    thread('horizon','Horizon Research','Exploring options','Sam Rivera',None,[
        ('10-08T10:00','inbound','Interesting product. Maybe we should revisit this sometime. No specific purchase plan or next step yet.',[])])
    from .extra_fixtures import expansion_threads
    for values in expansion_threads():
        thread(*values)
    from .long_fixtures import long_threads
    for values in long_threads():
        thread(*values)
    from .edge_long_fixtures import edge_long_threads
    for values in edge_long_threads():
        thread(*values)
    return rows
