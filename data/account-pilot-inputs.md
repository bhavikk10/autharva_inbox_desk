# Gmail pilot conversations

Connect the Gmail address playing **Seller**. Use a second address as **Buyer**. Start each subject as a separate conversation, then always use Reply; keep the same subject. All companies and product claims below are fictional. Paste each body without the role/number labels. Gmail supplies real timestamps, reply headers, signatures, and quoted history.

Label these five conversations `autharva-test` in the connected Seller mailbox, import that label with a limit of five, and inspect the normalized messages before analysis. Importing itself makes no model call. Analysis sends the visible text to the configured GLM service at Z.ai.

Send the six messages in each thread in the listed order. You can compress them into one session to test extraction; this does not reproduce real communication cadence or 48 hours of waiting. For the outreach case, spacing follow-ups over different days makes the test more realistic. Never alter the email timestamps to make a test pass.

These expectations were written before any model runs on these new threads. Review them before opening the model result. This is a new synthetic Gmail ingestion pilot, not held-out or real-customer accuracy.

Use **Now** first. Then try the specified clock changes. If you send the Friday case after October 9, 2026, update Friday to an explicit future date and revise its expected times before analyzing. Source timestamps anchor all relative expressions.


## 1. Meridian rollout - security questions

**Expected:** T1 after email 6; T3 after the optional answer.

Checks partial resolution, explicit urgency, and whether acknowledgements falsely clear an ask.

### Email 1 - Buyer

My team is comparing options for an eighty-person rollout. Could you confirm where customer data is hosted and whether SCIM provisioning is available on the standard plan? Those are the two points our security reviewer needs.

### Email 2 - Seller

Customer data for your tenant can stay in our Mumbai region, including backups. Your existing account administrators can choose that region during tenant setup. This gives your reviewer the regional hosting arrangement needed for the security checklist.

### Email 3 - Buyer

Thanks, the Mumbai hosting arrangement works for us. I still need the SCIM answer before security can clear the rollout. We are at the approval stage, so please confirm that urgently rather than sending another general overview.

### Email 4 - Seller

I have checked the hosting settings with our infrastructure team and the Mumbai option is available. I am checking the provisioning detail with product because I do not want to give your reviewer an incomplete answer.

### Email 5 - Buyer

The reviewer has cleared the location requirement. What remains is whether employee accounts can be provisioned and deactivated through SCIM on the plan you quoted. We cannot approve the purchase until that point is answered.

### Email 6 - Seller

I understand why that matters for your approval. Product has seen the question, but I have not received their confirmation yet. The regional hosting details are unchanged, and I will pass along the provisioning answer when available.

### Optional email 7 - Seller

SCIM provisioning and deactivation are included in the standard plan we discussed. Your identity provider can create, update, and disable accounts through SCIM without an additional subscription. That completes the two security questions you raised.

Analyze after email 6 first. Then send email 7, re-import, and analyze again at Now. SCIM should disappear from unresolved items; the residency question must remain resolved.

## 2. Northstar annual subscription - final approval

**Expected:** T3 before Friday October 9 at 09:00 IST; T2 from 09:00; T1 from 17:00, if approval remains outstanding.

Checks buyer ownership, a material explicit commitment, relative Friday anchoring, and clock changes.

### Email 1 - Seller

Here is the offer for 120 users: Rs 240,000 annually, including onboarding and standard support. The implementation window is two weeks after purchase. This reflects the scope we discussed with your operations team during the walkthrough.

### Email 2 - Buyer

Thanks for the offer. Before I take it to finance, could you confirm whether the quoted amount is paid annually upfront and how long our data remains available after cancellation? Legal asked me to clarify both points.

### Email 3 - Seller

The quoted amount is payable annually upfront, with no separate onboarding fee. After cancellation, your administrators have thirty days to export tenant data before deletion. Those terms apply to the standard subscription included in this offer.

### Email 4 - Buyer

That answers the finance and legal questions. I will send our final purchase approval on Friday. Procurement cannot issue the purchase order without that sign-off, so this is the last internal step before we can proceed.

### Email 5 - Seller

Great, the offer already includes the onboarding allowance and support level we reviewed. The annual payment and export terms are reflected in the subscription summary above. Thanks for keeping us updated on the remaining internal approval.

### Email 6 - Buyer

Legal has finished reviewing the terms and is comfortable with them. Finance still needs to sign off on the budget, and I will send the final approval on Friday as agreed. There is nothing else they need from you.

## 3. Cedar planning - revisit the annual offer

**Expected:** T3 before October 13 at 09:00 IST; T2 from 09:00 when the explicit contact pause ends, with the separate unresolved seller action still outstanding.

Checks a not-before contact date: the pause ending must not become an overdue commercial deliverable.

### Email 1 - Buyer

We are putting together next quarter's budget and may need identity management for twenty-five staff. Could you send an annual price with onboarding included? I would like an initial number before we compare it with our current arrangement.

### Email 2 - Seller

For twenty-five staff, the annual subscription is Rs 60,000, including standard onboarding and email support. It covers the account administration features discussed previously. You can use this figure for planning while your team reviews the available budget.

### Email 3 - Buyer

The quote has what we need for planning. Our budget discussions are still underway, so please hold off until October 13 before contacting us again. There is no additional document or product answer needed at this point.

### Email 4 - Seller

Understood, October 13 is noted as the point when discussions can resume. The quote remains available for your planning team. Thanks for explaining the budget timetable; that helps us avoid interrupting your review with unnecessary reminders.

### Email 5 - Buyer

A quick update from our side: the budget timetable is unchanged, and the annual quote is already with the planning team. We are still comparing the available options, so the October 13 date remains appropriate for resuming discussions.

### Email 6 - Seller

Thanks for the update. The proposed scope remains twenty-five staff with standard onboarding and support included. There has been no change to the annual price, so your team can continue using the same figure during its planning discussions.

## 4. Harbor pilot proposal

**Expected:** T3 after the last three unanswered follow-ups, including when you move the clock five or more days past the proposal.

Checks saturation without an urgent obligation. Emails 4-6 are deliberately three consecutive seller follow-ups.

### Email 1 - Buyer

Our operations team would like to compare a small pilot with our current identity setup. Could you send pricing for forty users and the proposed evaluation period? We need something concrete to share with the department leads.

### Email 2 - Seller

For forty users, the pilot costs Rs 12,000 for thirty days, including initial setup and standard support. That gives the department leads time to review account administration and provisioning. These are the complete commercial terms for the evaluation.

### Email 3 - Buyer

Thanks, the offer came through. I have forwarded the pricing and evaluation period to the department leads so they can take a look. I do not have any comments from them yet, but wanted to acknowledge receipt.

### Email 4 - Seller

I wanted to check whether the department leads have had a chance to look at the pilot offer. If a short clarification would help their review, feel free to send the questions through when convenient for your team.

### Email 5 - Seller

Following up on the forty-user pilot offer. The pricing and evaluation period are still the same as in my earlier message. If the team has any initial feedback, I would be interested to hear it when available.

### Email 6 - Seller

One more note on the pilot proposal, in case it slipped behind other priorities. The offer remains available for your team to review. If this is no longer relevant, a brief update would help me understand where things stand.

## 5. Lumen renewal comparison

**Expected:** T4 after the explicit rejection; no future commercial obligation.

Checks closure: a substantial opportunity does not remain urgent after the buyer clearly rejects it.

### Email 1 - Buyer

We are comparing identity platforms before renewing for two hundred staff. Can you confirm your annual price and whether Mumbai hosting is available? Those two points will help our procurement team compare your offer with the existing supplier.

### Email 2 - Seller

For two hundred staff, the annual price is Rs 360,000 with onboarding and standard support included. Mumbai hosting is available for the tenant and backups. This is the scope and regional arrangement we discussed during your evaluation.

### Email 3 - Buyer

Thanks for explaining both points. Procurement has decided to renew with our existing supplier, and the renewal agreement has been signed. Your offer was useful for the comparison, but we are not moving forward with a switch.

### Email 4 - Seller

Thanks for letting us know. For completeness, our regional hosting option and quoted onboarding allowance remain part of the offer we discussed. I understand the renewal decision is already made, and appreciate the time your team spent evaluating us.

### Email 5 - Buyer

We appreciate the information, but the signed renewal settles this evaluation. We will stay with the current supplier for the next two years. Please close the opportunity on your side; we are not pursuing another proposal or discussion.

### Email 6 - Seller

Understood, and thanks for the clear update. It was useful learning about your requirements during the comparison. Best wishes with the renewed platform and the upcoming rollout across your teams. Thank you again for considering our offer.

## What to record before and after analysis

For each thread, write down the action actually owed, its performer, supporting email, raw date wording, and expected attention at your selected time. Then compare those with the result. Note false obligations, wrong owners, premature resolution, duplicate items, missing urgency, incorrect closure, malformed output, and API failures separately.

For Northstar, final approval is owed by Buyer, not Seller. Its two mentions should produce one commitment, and Thursday/Friday clock changes should reuse the same extraction when no new message becomes visible. For Meridian, the hosting answer and SCIM answer must resolve separately. For Cedar, permission to resume contact is not a missed deadline. For Harbor, the acknowledgement is not a buying decision. For Lumen, an advisory suggestion must not reopen a rejected opportunity.

The app resolves date-only delivery promises at 17:00 and contact-not-before dates at 09:00 in the stated zone (IST by default). These are exposed conventions, not factual times stated in the email. Explicit unambiguous time zones are supported; ambiguous zones need clarification. Attachment contents are outside this pilot. Keep unexpected outcomes rather than changing the expectations to match GLM.
