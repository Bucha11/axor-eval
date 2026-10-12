# Progent — check, analysis and consumer, offline

Progent's runtime check validates an argument against a JSON-Schema restriction
(`jsonschema.validate`). Its policy analysis (`secagent/policy_analysis.py`, used
for the policy-update subset check and conflict warnings) translates the same
`pattern` into Z3 as `InRe(value, regex)` — membership of the whole value.
JSON-Schema `pattern` is an unanchored search. The analysis therefore reasons
about a language the enforcement does not implement, and the stock handler
consumes the whole value.

The policy form is the one Progent prescribes (its policy prompt asks for
`pattern` on URLs) and uses in its own examples (`pattern` on an IBAN). Whether
its policy model emits that form on a given task is not measured here — no model
is called. What is shown: given such a policy, Progent's wrapper admits a URL on an
attacker host and an attacker IBAN carrying the allowed one, its analysis says it
would not, and AgentDojo's stock `post_webpage` / `send_money` execute the value
as admitted.

```
PROGENT_REPO=<clone at 5be7b63> uv run --no-project --with agentdojo==0.1.35 \
  --with z3-solver --with docstring_parser --with jsonschema --with pytest \
  python -m pytest experiments/progent_checkuse -q
```
