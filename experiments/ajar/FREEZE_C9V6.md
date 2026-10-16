# c9v6 frozen (c9v5 + sender_from_typed)

| item | value |
|---|---|
| kernel | axor-core claude/model-m1 **cad07bc** (= 618c4a9 + the `sender_from_typed` flag; the flag is the only governance change, default off) |
| config banking | config_m1_c9v6/banking.yaml sha256 816bfa24aff58494 |
| config slack | config_m1_c9v6/slack.yaml sha256 b013f1316f2625b8 |
| config travel | config_m1_c9v6/travel.yaml sha256 232de4d81885915a |
| config workspace | config_m1_c9v6/workspace.yaml sha256 ed7eb40c6c9e0d4c |

c9v6 = c9v5 + `sender_from_typed: true`: the record sender is taken from the tool's TYPED return
field (slack `Message.sender`, workspace/travel `Email.sender`, banking `Transaction.sender`;
`CalendarEvent` has no sender field) supplied by the integration, instead of parsing `sender:`/`from:`
out of the rendered text; the text SENDER_IN_* path is disabled, and a tool with no declared sender
field yields no named_sender.

Behaviour-equivalent to c9v5 on every real tool output: a differential (old text-mint vs new
typed-mint named_sender set) over **7462** recorded tool outputs — replay 1887 (6853), Ajar
reference plans (305), live (304) — shows **0 discrepancies** (results/sender_from_typed_diff_c9v6.json).
Coverage: 8707 executed calls; 1245 carried no object (error or None return) and mint no named_sender
either way, so 7462 entered. Regression flag-on (replay 1887, M3, item_senders from re-execution):
landed 7 — identical to c9v5. The frozen c9v5 config hashes are unchanged (banking 4ed005685fbc6828,
slack 45564b9f656b1e47, travel 695459e1dbbb2ec8, workspace 23abdaeed0979f35); the live paid runs were
on c9v5.
