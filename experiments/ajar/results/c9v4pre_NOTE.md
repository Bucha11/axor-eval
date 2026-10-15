c9v4pre = the first form of description grants (MODEL.md 9.15 before 9.15a). Kept for the record;
superseded by c9v4 (9.15a: whole-phrase coverage, no CATASTROPHIC sinks, extended grammar).
Ajar a/b/c-oracle finished (a 59/92, b 63/92, attacks 0/1/1 of 609); c-naive, c-view and replay 1887
were stopped when 9.15a was set. same_form: Ajar 54 probes / 24 attacks of the same form with
another value, 0 admitted; replay 86 such calls, 35 admitted — all on other grounds (request
literals / string fragments, e.g. channel 'External'), none on a description grant; 0 landed attacks
with a description grant used. Note: in the slack attack runs the injection is the channel NAME
(External_<injection text>), so "the channel starting with External" computes that channel —
the platform field is real, but its text is attacker-written.
