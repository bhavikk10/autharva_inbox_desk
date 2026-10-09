"""Fictional account-to-account examples; never Gmail imports or model responses."""
from datetime import datetime,timedelta
from pathlib import Path
import re

BUYER='bhavikmalik100706@gmail.com'
SELLER='bhavikmalik1007@gmail.com'

# These are email INPUTS only. No tiers, model responses, or claimed Gmail IDs.
EXTRA_CONVERSATIONS=[
('invoice','Maple Studio','Invoice correction before payment',[
('inbound','We are ready to pay for the annual subscription, but the invoice has our old billing address. Please replace it with the address in the purchase order before finance releases payment. The subscription details are otherwise correct.'),
('outbound','Thanks for pointing out the billing mismatch. The subscription quantity and annual price match the purchase order. I have asked our accounts team to check the address, and I am keeping this conversation open until they respond.'),
('inbound','The purchase order already contains the updated address, so you should have everything needed for the correction. Finance has reserved the payment slot for tomorrow. We cannot use an invoice that lists the old registered office.'),
('outbound','I checked the purchase order and can see the new registered office details clearly. Accounts has the document now. I have not received the corrected invoice yet, so I am unable to confirm that the change is complete.'),
('inbound','Our finance reviewer confirmed the amount and tax details are fine. The billing address remains the only issue. Please send the corrected invoice urgently so that we can complete the payment in the slot already reserved.'),
('outbound','I understand that the invoice correction is blocking payment. The request is still with our accounts team, and I have not received a replacement document. I will share their response when available rather than send the incorrect invoice again.')]),
('dpa','Aster Labs','Signed agreement with DPA still outstanding',[
('inbound','The legal reviewer has approved the subscription agreement. Before our security team can activate the tenant, we also need the data processing agreement for the same legal entity. Could you send that document for their records?'),
('outbound','The subscription agreement now reflects the approved legal entity and the agreed start date. I will send the data processing agreement by Friday. Security needs that document before activation, so I understand its importance to your rollout.'),
('inbound','That timing works for us. I have signed the subscription agreement and returned it through the signing portal. The security reviewer is holding the activation request until the data processing agreement arrives for the same entity.'),
('outbound','Thank you for completing the subscription signature. I can confirm receipt of that signed agreement. The onboarding contact and tenant region are already recorded correctly. I am still waiting for our legal team to provide the separate processing document.'),
('inbound','The onboarding team has accepted the implementation schedule and confirmed the internal contact. We still have not received the data processing agreement. Please keep that separate document on the list because activation depends on having it.'),
('outbound','The signed subscription agreement is safely recorded and onboarding has the approved schedule. Legal is reviewing the processing document, but it has not been sent yet. The Friday delivery commitment remains outstanding, and I understand activation is waiting.')]),
('partial','Beacon Freight','Export format answered, retention still open',[
('inbound','We are preparing an internal review of the reporting tool. Could you confirm whether exports include a CSV option and how long audit events remain available? Both answers are required before our compliance lead approves the pilot.'),
('outbound','Reports can be exported as CSV directly from the reporting screen. The exported file includes the visible columns and respects the current filters. Administrators do not need an additional subscription or a separate integration to use that export option.'),
('inbound','Thanks, that settles the export format. The compliance lead still needs the audit retention period for the standard plan. We are close to approving the pilot, so please clarify that remaining point before we issue the purchase order.'),
('outbound','I have verified the CSV export behaviour with our reporting team and the details above are correct. I am checking the audit retention period separately because the compliance lead needs an accurate answer for the standard plan.'),
('inbound','The reporting team has tested the sample CSV and it meets our requirements. Audit retention remains the only unresolved product question. Please confirm it urgently, since the compliance reviewer cannot approve the pilot without the stated retention period.'),
('outbound','Understood, the CSV requirement is complete and there is no need to revisit it. The retention question is still being checked with product. I have not yet received their confirmation, so I cannot give you the final period today.'),
('outbound','Audit events remain available for ninety days on the standard plan. That includes administrator activity and provisioning changes. This confirms the remaining retention question from your compliance reviewer; the CSV export answer provided earlier is unchanged.')]),
('reschedule','Cedar Works','Meeting moved without a missing recap',[
('inbound','Our team can join the product walkthrough on Friday at 11:00 IST. We would like to focus on account administration and the reporting screen. The existing overview already answers our pricing questions, so there are no documents needed beforehand.'),
('outbound','Friday at 11:00 IST is suitable for our product specialist. The meeting invitation includes the video link and both agenda items you mentioned. We can use the session to walk through administration and reporting with your team.'),
('inbound','A planning meeting has now been scheduled over that slot. Could we move the walkthrough to Monday October 12 at 14:00 IST instead? The attendees and agenda are unchanged, and we do not need any additional preparation material.'),
('outbound','Monday October 12 at 14:00 IST works for us. I have updated the meeting invitation and removed the Friday slot. The video link is unchanged, and the product specialist has accepted the revised date and agenda.'),
('inbound','The updated invitation has arrived and everyone on our side has accepted it. Monday at 14:00 IST is now the agreed slot. We have everything needed for the walkthrough and will bring any questions to that session.'),
('outbound','Thank you for confirming the revised invitation. Our specialist has the same agenda and attendee list. We will use the Monday session for the walkthrough as agreed; the previous Friday appointment is no longer part of the schedule.')]),
('deadline','Delta Foods','Questionnaire deadline changed by agreement',[
('inbound','The security reviewer needs the completed supplier questionnaire before approving our purchase. Could you return it by Thursday? The attached form contains all the questions, and our procurement contact can clarify anything that does not apply to your service.'),
('outbound','I have received the supplier questionnaire and shared it with our security team. We will return the completed form by Thursday. I understand that the reviewer needs it before the purchase can be approved on your side.'),
('inbound','Procurement has moved its review meeting to next week. There is no longer a need for Thursday delivery. Please return the questionnaire on Monday October 12 instead; that revised date leaves enough time before the security approval meeting.'),
('outbound','Thanks for the updated procurement schedule. Monday October 12 is now the agreed delivery date for the completed questionnaire, replacing Thursday. Security has the revised timetable and the same form, so no additional input is needed from your reviewer.'),
('inbound','Confirmed, Monday October 12 is the date we will use for the supplier questionnaire. Please disregard the earlier Thursday request. The scope of the review has not changed, and our procurement contact remains available for any clarification.'),
('outbound','The security team is working through the questionnaire against the revised Monday deadline. I have not sent the completed document yet, but the change from Thursday is recorded. We are following the updated date agreed in this conversation.')]),
('conditional','Elm Studio','Conditional quote without an agreed order',[
('inbound','We may expand the subscription if the board approves the hiring plan. Could you send a price for fifty additional users? This is only a planning exercise at present, and I cannot confirm when the board will discuss the proposal.'),
('outbound','Fifty additional users would cost Rs 90,000 annually at the current plan rate. This estimate includes the existing support arrangement and can be used in your planning document. It does not change the quantity or billing on your current subscription.'),
('inbound','Thank you, that provides the number we needed for the planning exercise. The board has not scheduled its discussion yet. We have no purchase approval or activation date, so please treat this as an estimate rather than an order.'),
('outbound','Understood, the figure is an estimate for planning and no subscription change has been requested. Your existing quantity and billing remain in place. There is no activation scheduled for the additional users while the hiring proposal awaits board discussion.'),
('inbound','The planning document now contains the estimate and support details. We still do not have a board meeting date or a decision on hiring. There are no further questions at this stage; the commercial scope depends on that decision.'),
('outbound','Thanks for the update on the planning document. The estimate remains available as a reference, and we have not treated it as an approved order. Our account record reflects the existing subscription while the board decision remains unknown.')]),
('owner','Fern Media','Owner changes for a security review',[
('inbound','Our IT lead raised a question about administrator permissions in the pilot. Could you explain whether we can restrict user invitations to designated administrators? We need a clear answer before giving the pilot account access to our department leads.'),
('outbound','User invitations can be restricted to designated administrators through the workspace permission settings. Standard members will then be unable to invite additional users. Your IT lead can select the administrators before the department leads receive access to the pilot workspace.'),
('inbound','That answers the invitation question. Our internal IT lead will configure the administrator list tomorrow and then distribute pilot access. This is an action on our side, and we do not need any further changes or documentation from your team.'),
('outbound','Thanks for confirming the internal setup owner. The invitation restriction described above is already available on your pilot plan. Your IT lead can make the administrator selection in the workspace settings, and no additional provisioning work is needed from us.'),
('inbound','The IT lead has completed the administrator list and distributed pilot access to the department leads. The invitation restriction behaves as expected in our checks. There are no remaining setup questions or tasks needed from your team for this pilot.'),
('outbound','Thank you for confirming that the administrator setup and access distribution are complete. The pilot can now proceed with the restricted invitation permissions you tested. We have recorded the completed setup and there is no outstanding configuration request in this exchange.')]),
('timezone','Grove Finance','Approval promised in an explicit foreign timezone',[
('outbound','The revised annual offer contains the user quantity, onboarding allowance and export terms we discussed. All requested commercial points are covered in the summary below. Please let us know how your finance review progresses once the proposal reaches the approver.'),
('inbound','The revised offer answers our commercial questions. I will send the final purchase approval on Friday October 9 at 16:00 UTC. Finance requires that approval before issuing the purchase order, and this is the final step on our side.'),
('outbound','Thank you for specifying the approval time in UTC. The offer remains aligned with the quantity and onboarding allowance already agreed. We have recorded the promised Friday October 9 at 16:00 UTC response and are waiting for the finance decision.'),
('inbound','Legal has reviewed the export terms and does not need any changes. Finance is still completing its budget check. The promised approval time remains Friday October 9 at 16:00 UTC, and there is no additional action required from your team.'),
('outbound','Thanks for clarifying that legal is finished and finance is continuing its review. The annual offer and onboarding allowance are unchanged. We are still waiting for the final purchase approval at the explicitly agreed UTC time rather than a local business-day cutoff.'),
('inbound','The finance approver has the complete budget pack and the revised annual offer. I have not received their final approval yet, but the agreed response time is unchanged. I will send that decision at Friday October 9 at 16:00 UTC.')]),
('promo','Harbor Shop','Optional product announcement without an obligation',[
('inbound','We have published a new set of workspace themes for the reporting dashboard. Existing account settings and subscriptions are unchanged. You can browse the examples if you are interested, but there is no migration, required action or response needed for this announcement.'),
('outbound','Thanks for sending the theme announcement. We may browse the examples when we next review the dashboard appearance. Our current reporting setup is working well, so we are not requesting any changes, demonstrations or additional information at this time.'),
('inbound','That is completely fine. The theme options will remain available in the appearance menu whenever they are useful. Your current dashboard is supported as it stands, and the announcement does not change your plan, billing or administration responsibilities.'),
('outbound','Understood, we will keep the existing appearance for now. The current dashboard meets our reporting needs, and there is no internal request to evaluate the new themes. Thanks for confirming that the announcement does not require a change on our side.'),
('inbound','Thank you for the clear update. We have recorded that no theme change or evaluation is requested. The examples remain optional, and we will not schedule a demonstration or treat the announcement as an outstanding request for a response.'),
('outbound','Thanks for confirming that. We have no questions or actions arising from the announcement and are continuing with the existing dashboard appearance. This exchange is complete from our side, with no requested theme change or demonstration to arrange.')]),
('attachment','Iris Learning','Attachment acknowledged but contents not confirmed',[
('inbound','Our procurement team needs the completed accessibility checklist before approving the annual subscription. Could you send the checklist for the current product release? The approval reviewer needs the answers in the document rather than a general marketing overview of the platform.'),
('outbound','I have received the accessibility checklist request and located the form procurement supplied. Our product specialist is working through the questions for the current release. I do not have the completed answers yet, so I am not confirming delivery at this point.'),
('inbound','I can see a file named accessibility-checklist.pdf in your latest message, but it opens as a blank form. We still need the completed answers for approval. Please do not treat receipt of the filename as confirmation that the required information has arrived.'),
('outbound','Thanks for checking the file contents and explaining the problem. The blank form was included for reference and does not contain the completed product answers. I have passed that distinction to the specialist, and the accessibility checklist request remains outstanding.'),
('inbound','The procurement reviewer has confirmed that the blank form cannot be used for approval. There is no other product question outstanding, but the completed checklist is still required. Please provide it urgently so that the annual subscription can move through the approval step.'),
('outbound','I understand that the completed checklist is blocking procurement approval. The specialist has not yet returned the finished answers, so I cannot confirm that the request has been fulfilled. The earlier blank attachment should remain separate from the completed document you need.')])
]


def account_sample_threads():
    guide=(Path(__file__).resolve().parents[1]/'data'/'account-pilot-inputs.md').read_text(encoding='utf-8')
    sections=list(re.finditer(r'^## ([1-5])\. (.+)$',guide,re.M))
    conversations=[]
    for index,match in enumerate(sections):
        block=guide[match.end():sections[index+1].start() if index+1<len(sections) else guide.find('## What to record',match.end())]
        headings=list(re.finditer(r'^### (?:Optional )?[Ee]mail (\d+) - (Buyer|Seller)\s*$',block,re.M))
        messages=[]
        for n,h in enumerate(headings):
            part=block[h.end():headings[n+1].start() if n+1<len(headings) else len(block)].strip()
            body=part.split('\n\n',1)[0].replace('\n',' ')
            messages.append(('inbound' if h.group(2)=='Buyer' else 'outbound',body))
        conversations.append(('pilot-'+match.group(1),match.group(2).split(' - ')[0],match.group(2),messages))
    conversations.extend(EXTRA_CONVERSATIONS)
    rows=[]
    for slug,company,subject,exchange in conversations:
        tid='sample-'+slug;messages=[]
        start=datetime.fromisoformat('2026-10-05T09:00:00+05:30')
        for n,(direction,body) in enumerate(exchange):
            # Fictional timestamps are part of the synthetic scenario, never claimed as Gmail metadata.
            sent=start+timedelta(hours=n*14)
            if slug=='pilot-1' and n==6:sent=datetime.fromisoformat('2026-10-09T11:00:00+05:30')
            messages.append({'id':tid+'-m'+str(n+1),'sender':BUYER if direction=='inbound' else SELLER,
                'recipients':[SELLER if direction=='inbound' else BUYER],'direction':direction,'body':body,
                'sent_at':sent.isoformat(),'attachments':[],'simulated':True})
        rows.append({'id':tid,'company':company,'subject':subject,'contact':BUYER,'deal_value':None,'messages':messages})
    return rows
