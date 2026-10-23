# Metrics

Contact counts are a full count of stored rows and can be zero. Membership counts are missing when the bot is not configured and no events have been stored. After events exist, a zero in a date window means no matching event was recorded. It does not mean Telegram confirmed that nobody joined.

| Metric | Numerator | Denominator | Source |
| --- | --- | --- | --- |
| Imported and unique contacts | Stored contacts in the time window | None. Uniqueness is the phone HMAC. | contacts |
| Eligible | Contacts currently marked ELIGIBLE | None | contacts |
| Pending consent | Summary consent status pending | None | contacts |
| Suppressed | Active suppression | None | contacts |
| Invitations attempted | attempted, accepted, delivered, or failed | None | invitations |
| Accepted by provider | accepted or delivery confirmed | None | invitations |
| Delivery confirmations | delivery confirmed only | None | invitations |
| Attributed joins | join events with a campaign | None | membership_events |
| Unattributed joins | join events without a campaign | None | membership_events |
| Verified departures | leave events | None | membership_events |
| Net growth | recorded joins minus recorded leaves | None | membership_events |
| Conversion rate | attributed joins | invitations attempted | both |
| Cost per attributed join | sum of actual campaign cost | attributed joins | campaigns and events |
| Provider failure rate | failed invitations | invitations attempted | invitations |

Conversion and cost use the state `zero_denominator` when the divisor is zero, and `missing` when the underlying events or costs were never collected.

Retention cohorts exist only when join events include a Telegram user id. A missing leave overstates retention. The API returns that caveat with the cohorts.
