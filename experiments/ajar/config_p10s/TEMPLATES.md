# Revision 10 — generated state before any run (derive_p10.py; kernel claude/proven-polarity)

Unattended ceiling REVERSIBLE. L3/L4-only (CATASTROPHIC): banking update_password; slack
remove_user_from_slack; travel cancel_calendar_event; workspace cancel_calendar_event,
delete_email, delete_file.

Tuple L2 templates (components: O<n> = O-set, R = request literal):

| suite | sink | template | kind |
|---|---|---|---|
| banking | send_money | recipient:O4, amount:R, date:R | mixed |
| banking | schedule_transaction | recipient:O4, amount:R, date:R, recurring:R | mixed |
| banking | update_scheduled_transaction | recipient:O4, amount:R, date:R, id:R, recurring:R | mixed |
| slack | send_direct_message | recipient:O4 | all-O |
| slack | send_channel_message | channel:O3 | all-O |
| slack | add_user_to_channel | channel:O3, user:O4 | all-O |
| workspace | append_to_file | file_id:O13 | all-O |
| workspace | send_email | recipients/cc/bcc:O35, attachments:R | mixed |
| workspace | share_file | email:O35, file_id:O13, permission:R | mixed |
| workspace | create_calendar_event | participants:O35, location:R, start_time:R, end_time:R | mixed |
| workspace | add_calendar_event_participants | participants:O35, event_id:R | mixed |

travel: no template (O = ∅). Revision-9 templates on delete_file and remove_user_from_slack
are gone (CATASTROPHIC: L3/L4 only); banking's are mixed now (amount/date are driving).
