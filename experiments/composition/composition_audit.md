# Аудит композиции: что из этого работает, а что только описано

2026-10-10 · axor-core `claude/floor-labeler-independence-t4upte` (HEAD `e9c4d00`,
`c4c64a2` — его предок) · axor-eval та же ветка

Проверялись утверждения из разбора архитектуры: три уровня композиции, «локальное
восстановление разрешений», две статические находки (родительский потолок
consequence; монотонность degradation) и статус `AuthorityPolicy`/`ExecutionPlan`.

Метод — не чтение. Каждая строка ниже опирается на исполняемый репродьюсер в
`repros/`; где это имело смысл, проверка идёт **по факту вызова хендлера**, а не по
вердикту гейта. Запуск:

```
cd experiments/composition/repros
/path/to/axor-core/.venv/bin/python parent_ceiling.py      # F1, F2, F3 + 12 рабочих осей
/path/to/axor-core/.venv/bin/python spawn_ceiling_e2e.py   # F1 end-to-end
/path/to/axor-core/.venv/bin/python escalation_scope.py    # F4, F5, уровень «внутри вызова»
/path/to/axor-core/.venv/bin/python degradation_narrowing.py # F6
/path/to/axor-core/.venv/bin/python authority_model_reach.py # F7
/path/to/axor-core/.venv/bin/python auto_grant_governance.py # F8
```
(`repros/_corepath.py` — та же конвенция, что в остальных каталогах experiments:
по умолчанию берётся соседний checkout axor-core, `AXOR_CORE_REPO` переопределяет.)

---

## Сводка

| # | Утверждение | Вердикт |
|---|---|---|
| — | Композиция «между политиками» сужает полномочия ребёнка | **Работает на 12 осях из 13** |
| — | Каскад внутри вызова конъюнктивен: восстановление одной оси не снимает остальные | **Работает, проверено исполнением** |
| F1 | Потолок consequence не переносится при композиции | **Подтверждено. Живая дыра, воспроизведена end-to-end** |
| F2 | Deployment overlay присваивает потолок вместо взятия строгого | **Подтверждено. Живая дыра, противоречит собственному докстрингу** |
| F3 | `_validate_child_policy` — второй защитный слой | **Перепроверяет 5 осей из 16** |
| F4 | Escalation восстанавливает capability, которую политика запретила | **Опровергнуто: такого восстановления в коде нет вообще** |
| F5 | Один grant может закрывать две оси, поэтому «один grant = одна ось» писать нельзя | **Подтверждено, но охват уже́: единственная ось — consequence** |
| F6 | Degradation LOCKED возвращает не сужение политики | **Подтверждено как нарушение контракта; эксплуатируемости нет** |
| F7 | `AuthorityPolicy`/`ExecutionPlan` — целевая модель, рантайм на `ExecutionPolicy` | **Подтверждено: ноль путей исполнения** |
| F8 | (не из разбора, найдено по ходу) governance-гейт consequence-оси — «human/operator-authorised path» | **Опровергнуто: его проходит сам агент** |
| — | Leases — отдельный механизм оси времени | **Опровергнуто: единственный источник — тот же escalation** |

Коротко, по категориям:

* **Работает и держится под исполнением:** конъюнктивность каскада (включая
  «grant восстановил egress — floor всё равно отказал»), 12 осей родительского
  пересечения, supersession, floor.
* **Живые дыры:** F1 (повышение потолка через spawn), F2 (overlay повышает явно
  понижённый потолок), F8 (агент сам открывает себе CATASTROPHIC-сток).
* **Контракт нарушен, эксплуатации нет:** F6.
* **Пусто, как проектор:** F4 (документированное восстановление capability
  невозможно), F7 (модель authority/plan ничего не читает), leases как отдельный
  механизм.

---

## Уровень «между политиками»: работает, кроме одной оси

`PolicyComposer.apply_parent_restrictions` (`axor_core/policy/composer.py:159`)
объявлен федеративным инвариантом: «A parent cannot grant a child more than it has
itself. This is the fundamental federation invariant.»

**Положительный результат, его стоит зафиксировать так же твёрдо, как дыру.**
Проверка `P6` берёт узкого родителя и широкого ребёнка и сверяет все остальные оси:
`allow_write`, `allow_bash`, `extra_allowed`, `max_child_depth`, `export_mode`,
`context_mode`, `compression_mode`, `child_mode`, `child_context_fraction`,
`escalation_policy`, `allowed_paths`, `allow_model_switch` — **12/12 сужаются
правильно** (включая неочевидное: пустой `allowed_paths` ребёнка наследует
родительский потолок, `_restrict_allowed_paths:283-302`).

### F1 — потолок consequence не входит в пересечение

`apply_parent_restrictions` возвращает `_with_policy(child_policy, ...)` с
двенадцатью перечисленными полями (`composer.py:243-256`). `max_unattended_consequence`
среди них нет, поэтому ребёнок сохраняет свой. `_validate_child_policy`
(`axor_core/node/spawn.py:45-83`) эту ось тоже не смотрит. Потолок читается на
исполнении из политики текущего envelope (`axor_core/node/intent_loop.py:1335`).

```
[CONFIRMED] P1 apply_parent_restrictions skips the consequence ceiling:
            parent=REVERSIBLE child=CATASTROPHIC -> composed=CATASTROPHIC
[CONFIRMED] P2 the spawn validator skips it too:
            child CATASTROPHIC under a REVERSIBLE parent accepted, no error
```

**Это не только отсутствие доказательства — это исполняемая эскалация.**
`spawn_ceiling_e2e.py` даёт оператору политику с `max_unattended_consequence=REVERSIBLE`
и `allow_bash=True`. Родитель получает отказ consequence-гейта на `bash`; он
спаунит ребёнка; ребёнок исполняет `bash`. Проверка — по факту вызова хендлера:

```
      parent policy ceiling=REVERSIBLE; child envelope: ['focused_mutative ceiling=CONSEQUENTIAL']
[CONFIRMED] S1 a spawned child executes the sink its parent is forbidden to execute:
            bash handler invoked with ['echo CHILD']; parent_ran=False child_ran=True
```

Механика: политика ребёнка выбирается заново самим дочерним узлом —
`wrapper.py:640-644` вызывает `child_node.run(...)` **без** `override_policy`, так
что идут `TaskAnalyzer` + `PolicySelector`. Ни один пресет селектора
(`axor_core/policy/selector.py`) и ни один пресет в `axor_core/policy/presets.py`
не задаёт `max_unattended_consequence`, то есть ребёнок всегда садится на дефолт
`CONSEQUENTIAL` — а пересечения, которое вернуло бы его к родительскому
`REVERSIBLE`, нет.

Область достижимости (`P7`), важная для оценки серьёзности:

* Понижение потолка **профилем** (`profile="strict"` → `REVERSIBLE`) дыру
  маскирует: overlay применяется тем же композером и к политике родителя, и к
  свежему пресету ребёнка, так что оба получают одно значение. Маскирует её,
  заметим, ровно баг F2 (присваивание вместо min).
* Дыра достижима, когда более низкий потолок пришёл оттуда, чего у ребёнка нет:
  явный `policy=` на вызов или `default_policy=` сессии. Это рекомендованная
  в докстринге `GovernedSession` конфигурация для PRODUCTION
  (`axor_core/worker/session.py:88-108`), так что путь не экзотический.
* Адаптивное сужение между ходами (`session.py:667` — тот же
  `apply_parent_restrictions` по политике предыдущего хода) этой осью не
  затронуто только потому, что пресеты все равны по ней. Как только какой-нибудь
  пресет задаст потолок, ход N+1 сможет его поднять.

### F2 — deployment overlay присваивает потолок

`_apply_deployment_overlay` (`composer.py:78-104`) сам о себе говорит: «The overlay
is a CEILING: it intersects with the per-task policy, never replaces it»
(`:83-85`). Для escalation и для `allowed_paths` это правда (`_intersect_escalation`,
`intersect_allowlist`). Для потолка consequence — нет: `:87-88` присваивает.

```
[CONFIRMED] P3 the deployment overlay replaces instead of narrowing:
            per-task REVERSIBLE + overlay CATASTROPHIC -> CATASTROPHIC
[CONFIRMED] P4 shipped profiles that widen rather than narrow: policy default=CONSEQUENTIAL;
            profiles={'observe': 'CATASTROPHIC', 'balanced': 'CONSEQUENTIAL',
                      'strict': 'REVERSIBLE', 'dev': 'CATASTROPHIC'}
[CONFIRMED] P5 compose() end to end keeps the widened ceiling: parent=REVERSIBLE -> child=CATASTROPHIC
```

То есть `profile="dev"` или `profile="observe"` **поднимает** потолок, который
оператор понизил явной политикой. Направление ошибки — в опасную сторону, и оно
живое на поставляемых профилях, а не гипотетическое.

Починка — одна строка (`min` по `ConsequenceClass`, он уже упорядочен: сравнения
`>` используются в `policy/consequence.py`). Но она **меняет поведение профилей
`dev`/`observe`**: их смысл сейчас — «ничего не гейтить», и после правки они
перестанут поднимать потолок там, где политика ниже. Это операторское решение, а
не чистый багфикс, поэтому в код я без отдельного согласия не лезу.

### F3 — второй защитный слой тоньше, чем выглядит

`wrapper.py:231-237` вызывает `_validate_child_policy` отдельно от композера,
«so any regression is caught immediately rather than silently producing an
over-privileged child». Фактически он перепроверяет 5 расширений из 16:

```
      validator re-checks 5/16 axes: ['tool_policy.allow_write', 'tool_policy.allow_bash',
                                      'tool_policy.allow_spawn', 'tool_policy.extra_allowed',
                                      'export_mode']
      not re-checked: ['tool_policy.allow_read', 'tool_policy.allow_search', 'max_child_depth',
                       'allowed_paths', 'escalation_policy', 'context_mode', 'compression_mode',
                       'child_mode', 'max_unattended_consequence',
                       'allowed_passthrough_commands', 'allow_model_switch']
```

Остальные 11 держатся только композером. Для статьи это значит: «ребёнок не
превосходит родителя» подпирается одним пересечением, а не двумя независимыми
проверками; `allowed_paths` и `escalation_policy` — оси с прямыми последствиями —
во второй проверке отсутствуют.

---

## Уровень «внутри вызова»: конъюнктивность реальна

Порядок в `_resolve_tool_intent` (`axor_core/node/intent_loop.py`): capability
(`:572`) → budget (`:597`) → роли (STRICT) → consequence (`:684`) → value policies (`:703`) → degradation (`:733`) → SSRF → positional (`:814`) → carrier (`:822`) →
taint/floor (`:844`) → advisory adjudicator → и только потом `pending_consumption.commit()`
(`:878`) и исполнение. Ни одна ветка не возвращает «approved» досрочно: решение
escalation — это APPROVE **капабилити-ветки**, после которого каскад продолжается.

Проверено исполнением, а не чтением (`escalation_scope.py`, E3+E4): grant на
egress-сток снимает consequence-отказ, а после объявленного sensitive-чтения тот же
самый grant floor не снимает.

```
[CONFIRMED] E3 the grant clears the consequence ceiling, and only a policy-allowed tool:
            before=False ("consequence gate: sink 'bash' is CONSEQUENTIAL, exceeding ")
            grant=True after=True
[CONFIRMED] E4 the grant does not clear the floor: grant=True egress_before_read=True
            floor=True egress_after_read=False
            ("taint enforcement (per-value): the driving argument of 'send")
```

Та же картина у supersession: `integrity_superseded` гасит **только**
`integrity_risk` (`axor_core/policy/gates.py:318`), а `conf_risk` считается
независимо через `confidentiality_risk` (`:326`). Это уже закреплено тестами —
`tests/adversarial/test_supersession_implies_covers.py`,
`tests/kernel/test_floor_labeler_independence.py`,
`tests/policy/test_floor_arming_dependencies.py` (126 passed на этом HEAD).

---

## Уровень «во времени»: здесь описание расходится с кодом сильнее всего

### F4 — escalation не восстанавливает запрещённую capability. Вообще

Это главная находка аудита, и она противоположна тому, на чём предполагалось
строить эксперимент «безопасное восстановление после отказа».

`preset:readonly` (`axor_core/policy/presets.py:20-21`) описывает сценарий прямо:
«agent may request write access mid-execution (e.g., found a bug while reviewing
and wants to apply a targeted fix)» — и несёт `allow_write=False` вместе с
`grantable_tools=("write",)`.

Но grant сохраняется только если под него создалась `CapabilityLease`
(`axor_core/node/escalation.py:241-256`: «Create the CapabilityLease first — if it
fails the grant is not stored»), а создание lease ограничено **разрешённым набором
инструментов родительской политики** (`lease_validator.py:60-83`, вызов на `:124`).
Этот набор считает `CapabilityResolver._resolve_builtin_tools`
(`axor_core/capability/resolver.py:68-86`) из `tool_policy` + `extra_allowed` и
**никогда не читает** `escalation_policy.grantable_tools`.

Два списка проверяются друг против друга так, что документированный случай
невозможен:

```
[CONFIRMED] E1 a lease cannot name a tool the policy denies: lease for 'write' against
            preset:readonly (whose own grantable_tools=('write',))
            -> err="lease grants tools outside parent ceiling: frozenset({'write'})"
[CONFIRMED] E2 escalation cannot restore a denied capability:
            result={'error': 'escalation_denied', 'reason': "escalation rejected: lease
            creation failed (lease grants tools outside parent ceiling: frozenset({'bash'}))"}
```

Следствия:

1. Фраза «mid-execution capability escalation» (`contracts/policy.py:194`,
   докстринги пресетов, README-пример в `session.py:88-108` с
   `grantable_tools=("write","bash")`) описывает поведение, которого нет.
   `escalation_policy.grantable_tools` работает как **фильтр** того, что уже
   разрешено, а не как список того, что может быть выдано.
2. Экспериментального сюжета «узкая политика → отказ → восстановление → полезная
   работа доведена» на текущем коде **не существует** по капабилити-оси. Без правки
   `arm`-а восстановления мерить нечего: utility-эффект будет нулевым по
   построению, а не по результату.
3. Это ровно та категория, что проектор: словарь (`grantable_tools`,
   `max_escalations`, `max_ops_per_grant`, approver-коллбэк, flood guard) поверх
   пути, который не может сработать в заявленном случае. Разница в том, что здесь
   есть работающий побочный эффект — см. F5.

Какая правка сделала бы механизм настоящим — одна из двух, и это операторское
решение, а не багфикс:

* считать потолком lease не `resolve(policy).allowed_tools`, а
  `resolve(policy).allowed_tools ∪ policy.escalation_policy.grantable_tools` — тогда
  grantable становится списком выдаваемого (и тогда же нужно, чтобы
  `apply_parent_restrictions` пересекал `grantable_tools`, что он уже делает,
  `composer.py:353-366`);
* либо признать нынешнее поведение намеренным и выправить документацию и пресеты
  (убрать `grantable_tools=("write",)` из `readonly`, где он не может сработать).

### F5 — что escalation реально делает: это ключ к consequence-гейту

`EscalationManager.covers` (`escalation.py:92-98`) читается в `_check_consequence`
(`intent_loop.py:1339`) как «есть ли governance-гейт для этого инструмента».
Именно это и работает (E3): инструмент, разрешённый политикой, но превышающий
потолок, после grant проходит.

Так что утверждение «нельзя заранее написать, что каждый grant относится ровно к
одной оси» **подтверждается по форме** (один объект обслуживает и ветку capability,
и consequence-гейт), но фактический охват у́же, чем звучит: по capability-оси grant
не добавляет ничего, что политика уже не разрешила (F4), так что единственная ось,
которую он действительно меняет, — consequence. `W(a)` для escalation = {consequence}.

### Leases — не отдельный механизм оси времени

`create_lease` вызывается из одного места — `EscalationManager.grant_from_intent`
(`escalation.py:241`), и `_capability_leases[...]` заполняется только там (`:258`).
Оператор не может вручить сессии lease: публичного API нет. Поэтому «leases» в
таблице трёх уровней — не третий механизм оси времени, а внутренняя деталь
escalation, с тем же потолком F4.

### F6 — degradation: контракт нарушен, эксплуатации нет

`apply_to_policy` обещает «Return a narrowed ExecutionPolicy»
(`axor_core/degradation/engine.py:327-334`). На LOCKED/TERMINAL (`:372-390`) он
собирает новый `ToolPolicy` с `allow_read=True` и `extra_allowed=('escalate',
'escalate_policy')`, не глядя на вход:

```
[CONFIRMED] G1 LOCKED turns allow_read on: base allow_read=False -> locked allow_read=True
[CONFIRMED] G2 LOCKED adds tool names the base never granted: base extra=() -> locked
            extra=('escalate_policy', 'escalate')
[CONFIRMED] G3 the resolved capability set is not a subset of the input's:
            base=[] locked=['escalate', 'escalate_policy', 'read'] added=[...]
```

Но это **не живая дыра**, и формулировать надо аккуратно:

```
[CONFIRMED] G4 one call site, and the LOCKED branch never reads the result
[CONFIRMED] G5 so the widening is inert end to end: read approved=False
            handler_called=False ("tool 'read' is not in capabilities for policy 'no-read'")
```

Единственный вызов — `intent_loop.py:1418`; его LOCKED-ветка сверяет имя
инструмента со `_LOCKED_ALLOWED_TOOLS` и расширенную политику не читает вовсе
(`effective` используется только в RESTRICTED-ветке), а капабилити-гейт работает
против `envelope.capabilities`, посчитанных из исходной политики. Так что точная
формулировка — «возвращаемая „суженная“ политика не является сужением; защиту
держит вызывающий код» — верна, и её же надо держать в статье: любой новый
потребитель `apply_to_policy`, доверившийся докстрингу, получит расширение.
Одновременно это ответ на «монотонность уровня degradation ≠ монотонность
полномочий»: по факту исполнения монотонность полномочий тут держится, просто не
тем механизмом, которым заявлено.

---

## F7 — `AuthorityPolicy`/`ExecutionPlan` ничего не читают

`contracts/authority.py:17-19` сам это и говорит: «During the migration window the
legacy ExecutionPolicy ... remains the runtime object». Измерено (AST, не grep —
упоминания в докстрингах не считаются использованием):

```
[CONFIRMED] A1 no module outside the contracts and the converter reads the new types: none
[CONFIRMED] A2 the converter has no runtime caller: none; exercised only by
            tests/contracts/test_authority_plan_split.py (round-trip)
[CONFIRMED] A3 the import boundary is pinned even though the model is unused:
            ['authority-plan-separation', 'planning-non-authoritative']
      for scale: ExecutionPolicy is referenced in 25 modules under axor_core/
```

Что из этого можно заявлять: **границу импорта** (import-linter её держит, planning
не может стать authority) и **конвертер с round-trip тестом**. Чего заявлять нельзя:
что разделение planning/authority реализовано — ни один гейт не читает
`AuthorityPolicy`, рантайм целиком на смешанном `ExecutionPolicy` в 25 модулях.

---

## F8 — governance-гейт consequence-оси проходит сам агент

Не входило в разбор; найдено при проверке F5 и относится к той же точке кода.

`_check_consequence` (`intent_loop.py:1320-1346`) описывает своё исключение так:
«The governance gate is satisfied by an active escalation grant or capability
lease for the tool (a **human/operator-authorised path**)». Фактическая проверка —
`EscalationManager.covers(tool_name)`, то есть **наличие** grant'а; кто его
одобрил, не спрашивается. При `require_human=False` grant выписывается из
собственного `escalate_policy`-интента модели и несёт
`LeaseAuthorityType.AUTOMATED_POLICY` (`escalation.py:240-247`).

```
[CONFIRMED] X1 an agent-issued, auto-approved grant lifts the CATASTROPHIC ceiling:
            before=False ("consequence gate: sink 'shutdown' is CATASTROPHIC, e")
            grant=True after=True handler_called=True
```

`shutdown` — CATASTROPHIC по встроенной таблице, то есть единственный класс,
который гейтится из коробки. Модель просит grant, approver не настроен и не
опрашивается, сток исполняется (проверка по хендлеру).

Оговорка, важная для честности: оператор сам поставил `require_human=False` и сам
внёс `shutdown` в `grantable_tools`. Это не обход его конфигурации — это **две его
настройки, противоречащие друг другу** (`max_unattended_consequence` говорит «этому
классу нужен гейт», `require_human=False` говорит «grant'ам человек не нужен»), и
разрешается противоречие молча в пользу разрешающего. Поэтому в плане правок это
не «баг», а требование сделать противоречие явным: consequence-гейт должен
принимать только lease с человеческой/операторской authority, либо оператор должен
объявить обратное отдельным полем.

---

## Что это значит для предложенного эксперимента

Сюжет «отказ → ограниченное восстановление → сохранение остальных обязанностей»
распадается на две неравные половины.

**Половина «сохранение остальных обязанностей» готова.** Каскад конъюнктивен,
проверено исполнением (E4), supersession и floor независимы и уже закреплены
тестами. Но именно поэтому её одной мало: это отрицательный результат ожидаемого
знака, та же форма, что «floor переживает ошибку labeler'а».

**Половина «восстановление» на текущем коде почти пуста.** По capability-оси
восстановления нет (F4), leases — не отдельный механизм, degradation
полномочий не возвращает. Единственное работающее восстановление — снятие
consequence-потолка через grant (F5), одна ось и один тип отказа. На этом можно
построить микроэксперимент, но не «положительную функцию системы»: utility-дельта
будет измеряться на одном виде отказа (сток превышает потолок при уже разрешённом
инструменте), а не на «узкая политика мешает работать».

Отсюда три варианта, и выбор твой:

1. **Сначала починить arm восстановления** (F4, вариант с
   `∪ grantable_tools`), потом мерить. Тогда появляется настоящая utility-ось и
   три конфигурации (strict без восстановления / с восстановлением / с чрезмерно
   широким восстановлением) становятся осмысленными. Цена: это изменение
   семантики, которое надо защищать отдельно, плюс миграция ожиданий пресетов.
2. **Мерить то, что есть**: одна ось (consequence), сюжет «оператор понизил потолок
   → легитимный сток заблокирован → grant → работа доведена → floor/integrity
   по-прежнему держат». Честно, дёшево, но вклад маленький.
3. **Сменить предмет на F1/F2**: не «восстановление», а **потеря ограничения при
   локально разумном преобразовании политики**. Здесь есть исполняемая эскалация
   (S1), поставляемые профили, двигающие потолок в опасную сторону (P4), и
   измеримая разница между «12 осей пересекаются» и «13-я нет». Это ближе всего к
   тому, что в системе действительно есть, и единственная из трёх линий, где уже
   есть воспроизведённый положительный факт, а не ожидание.

Моя оценка: (3) как результат и (1) как инженерная предпосылка для (2). Линию
«escalation как восстановление» нельзя описывать как существующий механизм Axor,
пока F4 не починен.

---

## Что я не проверял

* Не чинил ничего в коде. F1, F2, F4 — изменения семантики (чей потолок главный,
  что значит `grantable_tools`), это операторские решения, а не багфиксы.
* Не считал, сколько конфигураций в `examples/` сломает исправление F2.
* Не проверял federation-путь (`FederationGateway`) на тех же осях — спаун как
  федерация идёт тем же `apply_parent_restrictions`, но межпроцессный peer-путь
  отдельного аудита не получал.
* Не трогал `axor-wrap`/`axor-sentinel`/`axor-control-plane`: утверждения касались
  axor-core.
* Репродьюсеры **не закреплены как тесты** в axor-core. Четыре из них фиксируют
  поведение, которое, вероятно, будет меняться (F1, F2, F4, F6); превращать их в
  pinned-тесты (как `tests/taint/test_task_trust_is_mention_based.py`) имеет смысл
  после того, как решено, что из этого — баг, а что — намеренная семантика.
