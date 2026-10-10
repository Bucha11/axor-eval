# План правок: сделать композицию такой, как она описана

2026-10-10 · спутник `composition_audit.md` (находки F1–F8) · правки — в
**axor-core**, ветка `claude/floor-labeler-independence-t4upte`

Задача плана — закрыть разрыв между тем, что в axor-core написано про композицию,
и тем, что он делает. Порядок шагов определён зависимостями, а не серьёзностью:
шаг 1 — та инфраструктура, из-за отсутствия которой F1 вообще стал возможен, и без
неё остальные правки снова разъедутся.

**Критерий приёмки у каждого шага один и тот же:** соответствующая проверка в
`experiments/composition/repros/` переворачивается с CONFIRMED на REFUTED, и это
закрепляется тестом в axor-core. Репродьюсеры уже написаны и сейчас все
CONFIRMED — то есть они готовая регрессионная сетка, читаемая в обратную сторону.

Оценки — в агенто-часах (мои, не человеческие), включая тесты и прогон полного
`pytest` + `lint-imports` + `tools/check_docs.py`.

---

## Сводка шагов

| шаг | что | закрывает | оценка | решение оператора нужно |
|---|---|---|---|---|
| 1 | одна таблица порядка политик | причину F1, F3 | 3–4 ч | нет |
| 2 | пересечение потолка consequence + полная валидация ребёнка | **F1**, **F3** | 1–2 ч | нет |
| 3 | overlay сужает, а не присваивает | **F2** | 2–3 ч | **да** (профиль `dev`) |
| 4 | escalation действительно восстанавливает capability | **F4** | 4–6 ч | **да** (семантика `grantable_tools`) |
| 5 | governance-гейт требует человеческой authority | **F8**, уточняет F5 | 2–3 ч | **да** (fail-closed по умолчанию) |
| 6 | degradation возвращает настоящее сужение | **F6** | 1 ч | нет |
| 7 | закрепить репродьюсеры тестами, поправить документацию | все | 2–3 ч | нет |
| 8 | *опционально* — authority/plan доходит до одного гейта | **F7** | 8–12 ч | **да** (нужно ли это статье) |
| 9 | *опционально* — операторский API выдачи lease | «leases» | 2–3 ч | **да** (нужен ли механизм) |

Итого обязательная часть (1–7): **≈15–22 агенто-часа**. Три решения, которые я не
могу принять за оператора, собраны в конце отдельным списком.

---

## Шаг 1 — одна таблица порядка политик

**Зачем.** F1 возник не потому, что кто-то забыл одно поле, а потому, что порядок
`P' ⪯ P` записан трижды и в трёх разных формах: как список из 12 присваиваний в
`composer.py:243-256`, как пять `if`-ов в `spawn.py:56-83` и как три частных
функции `_most_restrictive_*`. Любое новое поле `ExecutionPolicy` по умолчанию
оказывается вне всех трёх. Пока это так, F1 воспроизведётся на следующем поле.

**Что делать.** Новый модуль `axor_core/policy/ordering.py` — единственный
источник истины:

```python
@dataclass(frozen=True)
class Axis:
    field: str
    narrower: Callable[[Any, Any], Any]   # (child_value, parent_value) -> narrower
    label: str                            # для текста ошибки

AUTHORITY_AXES: tuple[Axis, ...]   # поля, несущие полномочие
PLANNING_AXES:  tuple[Axis, ...]   # поля, несущие только форму исполнения
IDENTITY_FIELDS: frozenset[str]    # name, derived_from

def narrow(child: ExecutionPolicy, parent: ExecutionPolicy) -> ExecutionPolicy
def widenings(child, parent) -> tuple[str, ...]   # оси, где ребёнок шире родителя
```

Классификация полей (13 осей + 2 идентификационных):

| поле | группа |
|---|---|
| `tool_policy` (`allow_*`, `extra_allowed`, `extra_denied`) | authority |
| `allowed_paths` | authority |
| `export_mode` | authority |
| `child_mode`, `max_child_depth` | authority |
| `max_unattended_consequence` | authority ← **сейчас отсутствует везде** |
| `escalation_policy` | authority |
| `allowed_passthrough_commands` | authority |
| `allow_model_switch` | authority |
| `context_mode`, `compression_mode`, `child_context_fraction` | planning |
| `name`, `derived_from` | identity |

`narrower` для каждой оси — ровно то, что уже написано в композере (`and`, `min`,
`_most_restrictive_*`, `intersect_allowlist`, `_restrict_escalation`), перенесённое
без изменения семантики. Поведение на 12 рабочих осях обязано остаться
побайтово тем же — это проверяет шаг 7.

**Структурная гарантия (главное в шаге).** Тест
`tests/policy/test_ordering_covers_policy.py`:

```python
assert {f.name for f in fields(ExecutionPolicy)} == (
    {a.field for a in AUTHORITY_AXES} | {a.field for a in PLANNING_AXES} | IDENTITY_FIELDS
)
```

Новое поле политики не компилируется мимо классификации. Это то, чего сейчас нет
ни в каком виде, и это же — единственное, что позволит в статье написать «порядок
вычисляется из одной таблицы, и тест утверждает, что таблица покрывает тип
политики целиком», вместо «мы просмотрели поля глазами».

**Побочная польза для F7.** Разделение authority/planning появляется в том
объекте, который реально исполняется (`ExecutionPolicy`), а не только в
неиспользуемом `AuthorityPolicy`. Это дешёвая часть того, что шаг 8 делает дорого.

**Риск.** Низкий, но правка затрагивает горячий путь композиции: `compose()`
вызывается на каждом `run()` и на каждом спауне. Переносить функции `narrower`
копией, не «улучшая» их по ходу.

---

## Шаг 2 — F1 и F3: потолок пересекается, ребёнок валидируется целиком

Зависит от шага 1.

1. `apply_parent_restrictions` → `return narrow(child_policy, parent_policy)`
   (плюс отдельная поправка `max_child_depth` на бюджет глубины:
   `min(child, max(0, parent - 1))` — это не «пересечение значений», а расход
   бюджета, он остаётся специальным случаем и должен быть помечен комментарием).
2. `_validate_child_policy` → `widenings(child, parent)` по `AUTHORITY_AXES`;
   непустой результат → `SpawnValidationError` с перечислением осей. Проверка
   глубины (`child_depth > parent.max_child_depth`) остаётся как есть: это
   аргумент вызова, а не поле политики.
3. Планировочные оси при валидации не фатальны (композер их сужает, но ребёнок,
   собранный вручную в тесте, не должен падать из-за `context_mode`).

**Приёмка:**
- `parent_ceiling.py`: `P1`, `P2` → REFUTED; `P6` остаётся 12/12; строка
  «validator re-checks» становится 16/16 (`max_child_depth` считается через
  бюджет, остальные — через таблицу).
- `spawn_ceiling_e2e.py`: `S1` → REFUTED, то есть **`bash` ребёнка теперь
  запрещён**. Это и есть цена исправления: задача, которую ребёнок выполнял, теперь
  не выполняется. Ровно эта дельта — то, что эксперимент «восстановление»
  измеряет, и её надо зафиксировать до правки (сейчас) и после.
- Новый тест в axor-core: `tests/policy/test_parent_ceiling_consequence.py` —
  потолок пересекается; `tests/node/test_spawn_validation.py` — дополнить
  случаями по каждой authority-оси.

---

## Шаг 3 — F2: overlay сужает

**Проблема.** `_apply_deployment_overlay` присваивает потолок (`composer.py:87-88`)
при собственном обещании пересекать (`:83-85`). Профили `dev` и `observe` несут
`CATASTROPHIC`, то есть **поднимают** явно понижённый оператором потолок.

**Но у `observe` на это есть законная причина**, и это та деталь, из-за которой
правка не одна строка: `ExecutionMode.OBSERVE` — режим измерения, «deny/lock
actions are not applied — the agent proceeds unblocked so measurement is not
contaminated by enforcement» (`contracts/mode.py:15-18`). Для него поднятый потолок
и есть смысл. При этом сегодня OBSERVE учитывает только
`DegradationEngine(observe=True)`; остальные гейты в OBSERVE отказывают как
обычно, и подавление consequence-гейта реализовано именно через потолок профиля.

**Что делать** — развести два разных намерения в двух полях `Profile`:

```python
consequence_ceiling: ConsequenceClass | None            # потолок: только сужает (min)
consequence_ceiling_override: ConsequenceClass | None    # «профиль назначает потолок»
```

* `_apply_deployment_overlay` для `consequence_ceiling` берёт
  `min(policy.max_unattended_consequence, overlay)` через тот же `narrower` из шага 1.
* `consequence_ceiling_override` присваивает — и логирует на WARNING, когда реально
  поднимает (`session_id`, было → стало). Остаётся он только у `observe`, с
  комментарием, что это подавление enforcement'а ради чистоты измерения.
* `strict` (`REVERSIBLE`) не меняется: он и так сужает.
* `balanced` (`CONSEQUENTIAL`) не меняется: равен дефолту.
* **`dev` — решение оператора.** Рекомендую `consequence_ceiling=None`: в LIBRARY
  mode CATASTROPHIC-сток начнёт требовать grant'а. Альтернатива (нулевое изменение
  поведения) — перевести `dev` на `consequence_ceiling_override=CATASTROPHIC`, но
  тогда у явно понижённой политики под `dev` потолок по-прежнему поднимется.

**Приёмка:** `parent_ceiling.py` `P3` → REFUTED; `P4` → REFUTED (ни один профиль не
расширяет через `consequence_ceiling`); `P5`, `P7` переформулировать на новую
семантику. Ломается один существующий тест — `tests/test_profiles.py:43`
(`_composer._consequence_ceiling == CATASTROPHIC` для `dev`), его надо обновить, и
это **изменение конфигурации, которое я не делаю молча**.

---

## Шаг 4 — F4: escalation действительно восстанавливает capability

Самая содержательная правка: сейчас документированный сценарий невозможен в
принципе (`E1`, `E2`), и без него у линии «безопасное восстановление» нет
положительной половины.

**Корень.** Потолок lease — это `resolve(policy).allowed_tools`
(`lease_validator.py:70`), который считается из `tool_policy` + `extra_allowed`
(`resolver.py:68-86`) и **никогда** не читает `escalation_policy.grantable_tools`.
Два списка проверяются друг против друга так, что пересечение всегда пусто для
интересного случая.

**Что делать.**

1. Новая функция `escalation_ceiling(policy) -> frozenset[str]` рядом с
   резолвером:
   ```python
   base = resolve(policy).allowed_tools
   if not policy.escalation_policy.allow_escalation:
       return base
   return (base | set(policy.escalation_policy.grantable_tools)) - set(policy.tool_policy.extra_denied)
   ```
   `extra_denied` вычитается последним — явный deny в резолвере уже «always wins»
   (`resolver.py:126-128`), и grant не должен быть исключением.
2. `LeaseValidator.validate_against_policy_ceiling` сверяется с
   `escalation_ceiling(parent_policy)` вместо `resolve(...).allowed_tools`.
3. **Отдельно и обязательно: исполнение.** `CapabilityExecutor.execute`
   независимо проверяет `tool_name not in capabilities.allowed_tools`
   (`capability/executor.py:96`), а `IntentLoop` передаёт ему
   `envelope.capabilities` (`intent_loop.py:931`). Без этой части grant всё равно
   упрётся в исполнителя. Нужен эффективный набор на момент вызова:
   ```python
   granted = self._escalation.granted_tools()          # новый метод
   caps = envelope.capabilities if not granted else dataclasses.replace(
       envelope.capabilities,
       allowed_tools=envelope.capabilities.allowed_tools | granted,
   )
   result = await self._executor.execute(effective_intent, caps)
   ```
   Расширение строится в одном месте, из активных grant'ов, и живёт только на
   время вызова — политика в envelope не меняется.
4. Тот же эффективный набор нужен daemon-пути:
   `capability/daemon_client.py:125` минтит grant из
   `capabilities.allowed_tools`; иначе демон откажет там, где in-process
   разрешает, и два пути разъедутся.
5. Инварианты, которые надо закрепить тестами, чтобы правка не превратилась в
   дыру:
   - инструмент **не** из `grantable_tools` по-прежнему отказывается;
   - `extra_denied` бьёт `grantable_tools`;
   - `allowed_paths` политики по-прежнему применяется к новому инструменту;
   - `grantable_tools` по-прежнему пересекается родитель→ребёнок
     (`composer.py:353-366` это делает, шаг 2 это ещё и валидирует);
   - все последующие гейты держатся на восстановленном инструменте — это уже
     показано `E4` (floor отказывает после sensitive-чтения), и тест надо
     перенести в axor-core как постоянный.

**Приёмка:** `escalation_scope.py` `E1`, `E2` → REFUTED; новый e2e-тест:
`preset:readonly` + grant → `write` **исполняется** (проверка по хендлеру);
`E4` остаётся CONFIRMED.

**Решение оператора.** Это изменение семантики: `grantable_tools` перестаёт быть
фильтром уже разрешённого и становится списком выдаваемого. Альтернатива — признать
нынешнее поведение намеренным и вычистить документацию: убрать
`grantable_tools=("write",)` из `preset:readonly`, снять фразу «agent may request
write access mid-execution» (`presets.py:20-21`), поправить
`contracts/policy.py:194` и README-пример (`session.py:88-108`). Это дешевле (≈1 ч)
и честно, но тогда линии «восстановление после отказа» в статье не будет вообще.

---

## Шаг 5 — F8: governance-гейт требует человеческой authority

Зависит от шага 4 (там же меняется форма `covers`).

**Проблема.** `_check_consequence` называет свой обходной путь
«a human/operator-authorised path» (`intent_loop.py:1330-1332`), а проверяет
наличие grant'а (`EscalationManager.covers`, `escalation.py:92-98`). При
`require_human=False` grant выписан по интенту самой модели и несёт
`AUTOMATED_POLICY` — и CATASTROPHIC-сток исполняется (`X1`).

**Что делать.**

1. Разделить два вопроса в `EscalationManager`:
   - `covers_capability(tool) -> bool` — есть активный grant (ветка capability,
     шаг 4);
   - `governance_gate(tool) -> bool` — есть активный lease с
     `authority_type is LeaseAuthorityType.HUMAN_OPERATOR`.
2. `_check_consequence` вызывает `governance_gate`.
3. Новое поле `EscalationPolicy.auto_grant_lifts_ceiling: bool = False` — явный
   opt-in для оператора, которому нужно прежнее поведение. По умолчанию
   fail-closed.
4. Поправить докстринг гейта: он должен называть ровно то, что проверяет.

**Что это даёт по существу, а не только по гигиене.** После шагов 4+5 охват
основания становится объявленным и разным по осям: один и тот же grant
восстанавливает capability, но потолок consequence поднимает только с человеческой
authority. Это и есть `W(a)` из формализации — не как желаемое свойство, а как
две разные функции в коде, с тестом на каждую.

**Приёмка:** `auto_grant_governance.py` `X1` → REFUTED; новые тесты:
`require_human=True` + approver → CATASTROPHIC-сток проходит;
`require_human=False` → capability восстановлена, consequence-гейт по-прежнему
отказывает; `auto_grant_lifts_ceiling=True` → прежнее поведение.

---

## Шаг 6 — F6: degradation возвращает настоящее сужение

Независим от остальных, самый дешёвый.

`apply_to_policy` на LOCKED/TERMINAL (`degradation/engine.py:372-390`) собирает
`ToolPolicy` с `allow_read=True` и `extra_allowed=('escalate','escalate_policy')`,
не глядя на вход. Заменить на пересечение:

```python
locked_tool = _dc_replace(
    base_policy.tool_policy,
    allow_read=base_policy.tool_policy.allow_read,   # НЕ True
    allow_write=False, allow_bash=False, allow_search=False, allow_spawn=False,
    extra_allowed=tuple(set(base_policy.tool_policy.extra_allowed) & _LOCKED_ALLOWED_TOOLS),
    extra_denied=tuple(
        t for t in (base_policy.tool_policy.extra_allowed or ())
        if t not in _LOCKED_ALLOWED_TOOLS
    ),
)
```

**Проверено, что это ничего не ломает:** `escalate_policy` перехватывается в
`_run_inner` (`intent_loop.py:375-376`) **до** капабилити-гейта, то есть
возможность попросить клиренс на LOCKED не зависит от `extra_allowed`; а
enforcement на LOCKED сверяет имя инструмента со `_LOCKED_ALLOWED_TOOLS`
(`intent_loop.py:1421-1427`) и расширенную политику не читает вовсе. Так что
правка восстанавливает контракт и не меняет ни одного наблюдаемого решения.

**Приёмка:** `degradation_narrowing.py` `G1`, `G2`, `G3` → REFUTED; `G5` остаётся
CONFIRMED (инертность сохраняется — просто теперь нечему быть инертным).
Добавить тест-инвариант: для любого уровня
`resolve(apply_to_policy(p, src)).allowed_tools ⊆ resolve(p).allowed_tools`.

---

## Шаг 7 — закрепить и переписать документацию

1. Перенести шесть репродьюсеров в axor-core как постоянные тесты (в
   `tests/policy/`, `tests/node/`, `tests/adversarial/`) с **перевёрнутыми**
   утверждениями. Шаблон — `tests/taint/test_task_trust_is_mention_based.py`:
   докстринг объясняет, что именно закреплено и почему.
2. Поведенческий диф до/после зафиксировать в `composition_audit.md` третьей
   колонкой («после правки»), чтобы отчёт не превратился в описание прошлого.
3. Документация, где текст сейчас опережает код:
   - `composer.py:83-85` — обещание пересечения (станет правдой на шаге 3);
   - `presets.py:20-21`, `contracts/policy.py:194`, `session.py:88-108` — про
     mid-execution escalation (станет правдой на шаге 4, либо будет убрано);
   - `intent_loop.py:1330-1332` — про «human/operator-authorised path» (шаг 5);
   - `degradation/engine.py:327-334` — про «narrowed policy» (шаг 6);
   - `docs/governance-model.md` и `docs/enforcement-model.md` — добавить порядок
     политик как одну таблицу и явное `W(a)` по каждому основанию
     (supersession → {integrity}, escalation → {capability} ∪ {consequence при
     человеческой authority}).
4. Прогон: полный `pytest`, `lint-imports`, `tools/check_docs.py`, и запись в
   `CHANGELOG.md`.

---

## Шаг 8 — *опционально* — F7: довести authority/plan до одного гейта

Сейчас `AuthorityPolicy`/`ExecutionPlan` не читает ни один модуль вне контрактов и
конвертера, а у конвертера ноль рантайм-вызовов (`A1`, `A2`). Заявлять
реализованное разделение planning/authority нельзя.

Два варианта, и это решение про статью, а не про код:

* **(a) Сузить утверждение (≈1 ч).** В `docs/` и в тексте писать то, что есть:
  граница импорта закреплена import-linter'ом, конвертер есть и покрыт round-trip
  тестом, рантайм — смешанный `ExecutionPolicy`. Плюс шаг 1 даёт разделение
  authority/planning *внутри* исполняемого объекта, и на него можно ссылаться.
* **(b) Довести до одного enforcement-пути (≈8–12 ч).** `EnvelopeBuilder` строит
  `AuthorityPolicy` через `split_legacy_policy` и кладёт в envelope рядом с
  политикой; consequence- и capability-гейты читают его, а не `envelope.policy`.
  Риск: два источника истины на время миграции; нужен тест, что они не расходятся
  ни на одном поле, иначе это новый F1.

Рекомендую (a) сейчас и (b) только если в статье нужна строка «разделение
реализовано», а не «граница закреплена».

---

## Шаг 9 — *опционально* — leases как настоящий механизм

`create_lease` вызывается из одного места — `grant_from_intent`
(`escalation.py:241`), публичного API нет, так что «leases» в описании трёх
уровней композиции — внутренняя деталь escalation, а не отдельный механизм оси
времени. Если механизм нужен (например, для сюжета «оператор выдал клиренс на
10 минут»), добавить `GovernedSession.grant_lease(...)`, требующий
`GovernanceAuthority` — по образцу `DegradationEngine.clear_by_governance`
(`degradation/engine.py:410-432`), где authority валидируется, а не принимается на
слово. Без этого в статье «leases» лучше не называть отдельным уровнем.

---

## Что должен решить оператор (я это не решаю)

1. **`dev`-профиль (шаг 3).** `consequence_ceiling=None` (CATASTROPHIC-сток в dev
   начнёт требовать grant'а, ломается один тест) или
   `consequence_ceiling_override` (нулевое изменение поведения, но явно понижённая
   политика под `dev` по-прежнему будет поднята)?
2. **Семантика `grantable_tools` (шаг 4).** Список выдаваемого (правка на 4–6 ч,
   появляется линия «восстановление») или фильтр уже разрешённого (правка на 1 ч,
   чистим документацию, линии в статье нет)?
3. **`auto_grant_lifts_ceiling` (шаг 5).** Default `False` (fail-closed; прежнее
   поведение требует явного opt-in) — подтвердить, что ломать его можно.
4. **Шаги 8 и 9** — нужны ли вообще.

До ответа по (2) шаги 4 и 5 не начинаю: в варианте «фильтр» их содержание другое.
Шаги 1, 2, 6, 7 от этих решений не зависят и могут идти сразу.

---

## Чего этот план не делает

* Не меняет ни один гейт данных: floor, integrity, supersession, carrier,
  positional, value-policy остаются как есть. Аудит показал, что каскад
  конъюнктивен и держится под исполнением; трогать его незачем.
* Не трогает проекторный слой (`CodomainKind`/`ConsumptionMode`/
  `validate_value_policies`) — это отдельная тема с отдельным вердиктом.
* Не считает миграционную стоимость по девяти таксономиям в `examples/` —
  шаг 3 профильные потолки меняет, а не таксономии, но прогон примеров перед
  коммитом нужен.
* Не чинит F7 по существу (шаг 8 — опция, и его честный вариант — сузить
  утверждение).
