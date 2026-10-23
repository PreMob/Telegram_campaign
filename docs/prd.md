# Product requirements

Harbor helps an operator run a public Telegram channel without treating a phone list as a list of Telegram accounts.

Operators can:

- Sign in with a role: super admin, campaign manager, analyst, or read-only.
- Import CSV or XLSX contacts, map columns, and review invalid and duplicate rows.
- Record channel-specific consent and withdraw it. Withdrawal suppresses the contact. A later import does not undo that.
- Build a campaign, preview who would be eligible, require approval, and require a second confirmation to launch.
- Create a Telegram invite link through the Bot API and store the association with the campaign.
- Record joins and leaves from Telegram updates, including duplicate delivery of the same update only once.
- See dashboard and analytics figures calculated from the database, with missing data distinguished from zero.
- Pause, resume, or cancel a campaign. Cancellation stops queued work.
- Export contacts only with an authorized role, with an audit entry.
- Erase a contact's phone number and name.

The product refuses:

- Phone-number lookup against Telegram.
- Unsolicited bulk messaging from a user account.
- Marking imported rows as consented by default.
- Classifying unknown membership as a confirmed non-join.
- Claiming a message was delivered because a provider accepted the API call.

Default eligibility requires consent for the selected channel, no active suppression, no verified membership, a frequency cap, and the campaign window. Campaigns aimed at confirmed non-members exclude unknown membership. No job messages the whole database merely because the rows exist.
