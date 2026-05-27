# EVE Online Fitting MCP Server — Claude Code Handoff

## Project Overview

Build a remote MCP server that allows Claude and Gemini (via their web UIs) to generate, validate, and optimize EVE Online ship fits. The server exposes five tools that combine SDE data, the eos fitting engine, and a lightweight ESI price cache to give the LLM ground truth on fitting validity, stats, and cost.

The LLM handles all EVE meta knowledge (what ships are good for what content, NPC damage types, general game knowledge). The MCP handles ground truth only — does this fit actually work, what are its real stats, what does it cost.

---

## Architecture

```
Claude/Gemini (web UI)
  └── MCP connector (HTTPS remote MCP server)
        ├── SDE (Fuzzwork SQLite — ships, modules, dogma, skills)
        ├── eos (pyfa's fitting engine — headless Python library)
        └── Price cache (ESI market orders, cached per typeID)
```

### Key dependencies

- **eos** — `github.com/pyfa-org/eos` — GPL v3 standalone fitting engine. Handles all dogma calculations, skill/bonus multipliers, stacking penalties. This is the calculation oracle for everything stat-related.
- **SDE** — Download from `https://www.fuzzwork.co.uk/dump/sqlite-latest.sqlite.bz2` — SQLite version of CCP's Static Data Export. Source of truth for all ship/module/skill data.
- **ESI** — `https://esi.evetech.net` — CCP's REST API. Used only for market price data. No auth required for market endpoints.
- **MCP Python SDK** — `https://github.com/modelcontextprotocol/python-sdk`
- **FastAPI** — HTTPS transport for the MCP server

### Important licensing note

eos and pyfa are GPL v3. This server must also be GPL v3 if distributed.

---

## The Five Tools

### 1. `get_ship_info(ship_name)`

**Purpose:** Returns a ship's slot layout, fitting stats, base resists, bonus structure, and skill requirements from the SDE. The LLM calls this to confirm its knowledge of a ship before committing to a fitting direction, and to understand which module types benefit from ship bonuses.

**Data source:** SDE only. No eos, no ESI.

**Algorithm:**
```
1. Query invTypes WHERE typeName LIKE :ship_name
   JOIN invGroups to confirm categoryID = 6 (Ships)
2. Query dgmTypeAttributes for this typeID
   → extract: cpuOutput (attr 11), powerOutput (attr 11),
     hiSlots (attr 14), medSlots (attr 13), lowSlots (attr 12),
     rigSlots (attr 1137), shieldHP, armorHP, hullHP,
     shield/armor/hull resist attributes
3. Query dgmTypeEffects + dgmEffects for bonus structure
   → what skills modify what stats by how much per level
4. Query dgmTypeAttributes for requiredSkill1/2/3 and levels
5. Return structured object
```

**MCP binding:**
```json
{
  "name": "get_ship_info",
  "description": "Look up a ship's slot layout, CPU, powergrid, base resistances, skill requirements to fly, and bonus structure from the EVE SDE. Call this before fitting a ship to confirm its capabilities and understand which module types benefit from ship bonuses. Do not rely on training knowledge for these values — they change with patches. Returns slot counts, fitting room, base HP and resists, per-level skill bonuses, and required skills.",
  "parameters": {
    "ship_name": {
      "type": "string",
      "description": "Ship name e.g. 'Condor', 'Vagabond', 'Curse'. Fuzzy matched."
    }
  }
}
```

**Example response:**
```json
{
  "name": "Condor",
  "typeID": 583,
  "slots": { "high": 3, "mid": 3, "low": 2, "rig": 3 },
  "cpu": 212,
  "pg": 46,
  "base_hp": { "shield": 400, "armor": 300, "hull": 250 },
  "base_resists": {
    "shield": { "em": 0, "thermal": 20, "kinetic": 40, "explosive": 50 },
    "armor": { "em": 50, "thermal": 35, "kinetic": 25, "explosive": 10 }
  },
  "bonuses": [
    { "skill": "Caldari Frigate", "stat": "missile_velocity", "per_level": 10 },
    { "skill": "Caldari Frigate", "stat": "missile_flight_time", "per_level": 10 }
  ],
  "required_skills": [
    { "skill": "Caldari Frigate", "level": 1 }
  ]
}
```

---

### 2. `get_modules_for_goal(ship, goal, skills, constraints)`

**Purpose:** Returns ranked module candidates for a fitting objective. Uses ship bonuses and character skills to calculate effective stats — not raw stats. Ammo and implants are factored into calculations where relevant. Filters out modules the character cannot use. This is the primary discovery tool.

**Data source:** SDE for candidates → eos for effective stat calculation → ESI price cache for cost.

**Algorithm:**
```
1. Map goal to relevant SDE module categories:
   maximize_ehp     → shield extenders, armor plates, resist mods,
                       damage controls
   maximize_dps     → weapons bonused for this ship, damage mods
   maximize_em_damage etc → weapons with that damage type + ammo
   maximize_speed   → MWDs, ABs, nanofibers, inertia stabs
   budget_fit       → all categories, price-sorted
   maximize_range   → weapon range mods, guidance computers

2. SQL pre-filter (cheap — do this first):
   SELECT modules WHERE
     categoryID IN (relevant_categories)
     AND cpu_requirement <= remaining_cpu
     AND pg_requirement <= remaining_pg
     AND metaLevel >= constraints.min_meta_level
     AND metaLevel <= constraints.max_meta_level
     AND jita_sell <= constraints.max_module_cost
     AND typeID NOT IN constraints.exclude
     AND slot_type IN available_slots

3. Skills filter:
   For each candidate check requiredSkill1/2/3 against
   provided skills dict. Remove anything character can't use.

4. eos calculation per surviving candidate:
   fit = Fit()
   fit.ship = Ship(ship_typeID)
   fit.character = Character(skills)
   fit.modules.append(Module(candidate_typeID))
   
   For weapon modules: also test with best ammo for goal
   e.g. for maximize_em_damage test Mjolnir variants,
   pick highest EM DPS ammo, include in result
   
   Extract goal-relevant stat:
   - ehp goal: fit.ehp (total effective HP across all layers)
   - dps goal: fit.dps (total with ship bonus + skill multipliers)
   - em_damage: fit.damage_stats.em
   - speed: fit.maxSpeed

5. Price lookup per typeID from cache:
   → cache hit (< 30 min old): return cached price
   → cache miss: GET /markets/10000002/orders/?type_id={typeID}
     extract min sell price, cache with timestamp

6. Post-filter:
   - Remove if total_cost would exceed constraints.max_total_cost
     (estimate based on existing fit cost + this module)
   - Remove if damage_type contribution is 0 when damage_type
     constraint is specified

7. Sort by effective goal metric descending
   Return top 20 with full context per module
```

**Constraints object — full field reference:**
```
max_total_cost      (int)    Total fit ISK cap
max_module_cost     (int)    Per-module ISK cap  
max_cpu             (int)    CPU headroom remaining — recalculate as slots fill
max_pg              (int)    PG headroom remaining — recalculate as slots fill
slot                (string) Only return modules for this slot type
exclude             (array)  typeIDs already in fit — never recommend these
min_meta_level      (int)    Filter out below this meta level (0=all, 5=T2+)
max_meta_level      (int)    Filter out above this (5=no faction/deadspace)
damage_type         (string) For DPS goals: only modules contributing this type
preserve            (array)  typeIDs to lock in place — deduct their CPU/PG/slots
                             from available fitting room before querying
```

**MCP binding:**
```json
{
  "name": "get_modules_for_goal",
  "description": "Returns ranked module candidates for a specific fitting objective on a specific ship. Effective stats are calculated using ship bonuses and character skills — not raw module stats — so rankings reflect real in-game performance. Ammo is automatically selected and factored in for weapon modules. Untrainable modules are filtered out. Use this to build a fit toward an objective. Call this once per slot type or once for the whole fit depending on the goal. Goals: maximize_ehp, maximize_dps, maximize_em_damage, maximize_thermal_damage, maximize_kinetic_damage, maximize_explosive_damage, maximize_speed, maximize_range, budget_fit.",
  "parameters": {
    "ship": { "type": "string" },
    "goal": { "type": "string" },
    "skills": {
      "type": "object",
      "description": "Character skills as {skill_name: level}. Pass an empty object to assume All 5."
    },
    "constraints": {
      "type": "object",
      "description": "Filtering constraints. Fields: max_total_cost, max_module_cost, max_cpu, max_pg, slot, exclude (array of typeIDs), min_meta_level, max_meta_level, damage_type, preserve (array of typeIDs to lock and deduct from fitting room)."
    }
  }
}
```

**Example response:**
```json
{
  "ship": "Condor",
  "goal": "maximize_dps",
  "skills_applied": true,
  "candidates": [
    {
      "name": "Rocket Launcher II",
      "typeID": 2410,
      "slot": "high",
      "cpu": 16,
      "pg": 4,
      "effective_dps": 98,
      "damage_profile": { "em": 98, "thermal": 0, "kinetic": 0, "explosive": 0 },
      "best_ammo": {
        "name": "Caldari Navy Mjolnir Rocket",
        "typeID": 24519,
        "jita_sell": 320
      },
      "jita_sell": 850000,
      "meta_level": 5,
      "required_skills": { "Rocket Specialization": 4 }
    },
    {
      "name": "Rocket Launcher I",
      "typeID": 2408,
      "slot": "high",
      "cpu": 12,
      "pg": 3,
      "effective_dps": 71,
      "damage_profile": { "em": 71, "thermal": 0, "kinetic": 0, "explosive": 0 },
      "best_ammo": {
        "name": "Mjolnir Rocket",
        "typeID": 2516,
        "jita_sell": 28
      },
      "jita_sell": 9000,
      "meta_level": 1,
      "required_skills": { "Rocket Launcher Operation": 1 }
    }
  ]
}
```

---

### 3. `get_modules_by_attribute(attribute, ship, skills, filters)`

**Purpose:** Returns modules ranked by a specific EVE dogma attribute with values calculated in ship+skills context. Use this when the request targets a specific mechanic rather than a broad role — e.g. "most EM damage", "fastest lock time", "smallest signature radius".

**Data source:** SDE for candidates → eos for effective values → price cache.

**Algorithm:**
```
1. Map attribute string to dogmaAttributeID:
   "em_damage"               → 114
   "thermal_damage"          → 118
   "velocity"                → 37
   "signature_radius"        → 552
   "lock_time"               → 556 (scan resolution)
   "cap_recharge"            → 55
   "shield_recharge"         → 479
   "tracking_speed"          → 160
   Build and maintain a mapping table for common attributes.

2. Query SDE dgmTypeAttributes WHERE attributeID = :attr_id
   JOIN invTypes to get module details
   Apply same SQL pre-filters as get_modules_for_goal
   (cpu, pg, price, meta, slot, exclude)

3. Skills filter — remove untrainable

4. eos calculation per candidate:
   Run fit with ship + skills + this module
   Extract the target attribute value from fit result
   with all multipliers applied

5. Price lookup from cache

6. Sort by effective attribute value
   (ascending for "smallest" attributes like sig radius,
    descending for "most" attributes like damage)
```

**MCP binding:**
```json
{
  "name": "get_modules_by_attribute",
  "description": "Returns modules ranked by a specific EVE attribute, with values calculated in the context of a specific ship and character skills. Use this when the user targets a specific mechanic rather than a broad goal — e.g. 'most EM damage', 'fastest lock time', 'best cap recharge'. Prefer get_modules_for_goal for broad objectives like maximize_dps or maximize_ehp. Supported attributes: em_damage, thermal_damage, kinetic_damage, explosive_damage, velocity, signature_radius, lock_time, cap_recharge, shield_recharge, tracking_speed.",
  "parameters": {
    "attribute": {
      "type": "string",
      "description": "The attribute to rank by e.g. 'em_damage', 'velocity', 'lock_time'"
    },
    "ship": { "type": "string" },
    "skills": { "type": "object" },
    "filters": {
      "type": "object",
      "description": "Same constraint fields as get_modules_for_goal: slot, max_cpu, max_pg, max_module_cost, min_meta_level, max_meta_level, exclude."
    }
  }
}
```

---

### 4. `calculate_fit(ship, modules[], skills)`

**Purpose:** The single calculation oracle. Takes a complete proposed fit and runs it through eos in one shot. Returns validity, all stats, and total cost. The LLM calls this iteratively — every time it proposes or modifies a fit — until valid is true and all constraints are met. Errors are detailed enough for the LLM to self-correct without re-querying discovery tools.

**Data source:** eos for all stats → price cache for cost. No SDE queries needed beyond typeID resolution.

**Algorithm:**
```
1. Resolve module names to typeIDs if needed
   (fuzzy match against invTypes)

2. Initialize eos:
   fit = Fit()
   fit.ship = Ship(ship_typeID)
   fit.character = Character() 
   for skill, level in skills.items():
       fit.character.setSkill(skill_typeID, level)

3. Add modules to slots:
   for module in modules:
       slot = get_slot_type(module.typeID)
       fit.modules[slot].append(Module(module.typeID))

4. eos resolves internally:
   - dogma attribute modifiers
   - skill multipliers  
   - ship bonus multipliers
   - stacking penalties
   - all derived stats

5. Extract from fit object:
   cpu_used, cpu_total, pg_used, pg_total
   shield/armor/hull EHP (HP × effective resists)
   total_ehp = sum of all layers
   dps = fit.totalDPS
   damage_profile = em/thermal/kinetic/explosive breakdown
   cap_stable = fit.capStable
   cap_depletes_at = fit.capDepleteTime (seconds)
   max_speed = fit.maxSpeed
   align_time = fit.alignTime
   slot_usage vs slot_total per type

6. Validate:
   valid = (cpu_used <= cpu_total 
            AND pg_used <= pg_total
            AND no slot overflows
            AND all module skill requirements met)

7. Build errors array if not valid:
   For each violation: type, magnitude, actionable suggestion
   e.g. cpu_overflow → excess: 12, 
        suggestion: "swap X for meta version to save 14 CPU"

8. Sum typeID prices from cache → total_cost

9. Return everything
```

**MCP binding:**
```json
{
  "name": "calculate_fit",
  "description": "Runs a complete ship fit through the eos calculation engine and returns all stats plus validity. This is your ground truth — call it every time you propose or modify a fit. Do not estimate fit validity or stats from module values alone. If valid is false, read the errors array — each error includes the type, magnitude, and a specific suggestion for how to fix it. Iterate until valid is true and all user constraints are met, then call export_eft.",
  "parameters": {
    "ship": {
      "type": "string",
      "description": "Ship name"
    },
    "modules": {
      "type": "array",
      "items": { "type": "string" },
      "description": "List of module names or typeIDs. Include duplicates for multiple of the same module e.g. three launcher slots = three entries."
    },
    "skills": {
      "type": "object",
      "description": "Character skills as {skill_name: level}. Pass empty object for All 5."
    }
  }
}
```

**Example response (invalid fit):**
```json
{
  "valid": false,
  "cpu_used": 224,
  "cpu_total": 212,
  "cpu_remaining": -12,
  "pg_used": 41,
  "pg_total": 46,
  "pg_remaining": 5,
  "slots_used": { "high": 3, "mid": 3, "low": 2, "rig": 2 },
  "slots_total": { "high": 3, "mid": 3, "low": 2, "rig": 3 },
  "ehp": 4200,
  "ehp_breakdown": {
    "shield": 2100,
    "armor": 1400,
    "hull": 700
  },
  "dps": 143,
  "damage_profile": { "em": 143, "thermal": 0, "kinetic": 0, "explosive": 0 },
  "cap_stable": false,
  "cap_depletes_at_seconds": 87,
  "max_speed": 1840,
  "align_time": 3.2,
  "total_cost": 1840000,
  "errors": [
    {
      "type": "cpu_overflow",
      "excess": 12,
      "suggestion": "Need to free 12 CPU. Options: swap Rocket Launcher II (16 CPU) for Rocket Launcher I (12 CPU) saves 4 CPU each; swap Ballistic Control System II (30 CPU) for meta BCS saves 6 CPU."
    }
  ]
}
```

---

### 5. `export_eft(ship, modules[], fit_name)`

**Purpose:** Called once, after `calculate_fit` returns `valid: true`. Formats the confirmed fit as an EFT string the user can paste directly into pyfa or EVE Online. Also returns the complete skill list required to fly the fit, generated by walking the skill requirement chains for the ship and every module.

**Data source:** SDE only. No eos, no ESI.

**Algorithm:**
```
1. Resolve all typeIDs to names if needed

2. Group modules by slot type:
   high_slots = [module for module in modules if slot == "high"]
   mid_slots  = ...etc

3. Walk skill requirement chains recursively:
   for each typeID (ship + all modules):
     requiredSkill1, requiredSkill1Level from dgmTypeAttributes
     requiredSkill2, requiredSkill2Level
     requiredSkill3, requiredSkill3Level
     for each required skill: recurse to get ITS requirements
   
   Deduplicate — take maximum required level per skill across
   all requirements

4. Format EFT string:
   [Ship Name, Fit Name]
   high slot module 1
   high slot module 2
   high slot module 3
   (empty line between slot groups)
   mid slot module 1
   ...etc
   (empty line)
   rig 1
   rig 2
   rig 3

5. Return EFT string + sorted skill list
```

**MCP binding:**
```json
{
  "name": "export_eft",
  "description": "Call this once calculate_fit has returned valid: true. Returns a correctly formatted EFT string the user can paste directly into pyfa or EVE Online, plus a complete list of all skills and levels required to fly the fit. Do not call this until the fit is confirmed valid.",
  "parameters": {
    "ship": { "type": "string" },
    "modules": {
      "type": "array",
      "items": { "type": "string" }
    },
    "fit_name": {
      "type": "string",
      "description": "Optional label shown in the EFT header. Defaults to ship name."
    }
  }
}
```

**Example response:**
```json
{
  "eft": "[Condor, Budget Ratter]\nRocket Launcher I\nRocket Launcher I\nRocket Launcher I\n\nMedium Shield Extender I\nMedium Shield Extender I\n1MN Afterburner I\n\nBallistic Control System I\nBallistic Control System I\n\nSmall Core Defense Field Extender I\nSmall Core Defense Field Extender I\nSmall Core Defense Field Extender I",
  "required_skills": [
    { "skill": "Caldari Frigate", "level": 1 },
    { "skill": "Rocket Launcher Operation", "level": 1 },
    { "skill": "Rockets", "level": 1 },
    { "skill": "Shield Operation", "level": 1 },
    { "skill": "Hull Upgrades", "level": 1 },
    { "skill": "Afterburner", "level": 1 }
  ]
}
```

---

## LLM Behavior Notes

Include this as a system prompt addendum in your MCP server:

```
You have access to an EVE Online fitting MCP server. Use these tools 
for all ship stats, module stats, fitting validation, and prices. 
Do not use training knowledge for specific numeric values — EVE data 
changes with patches and only the SDE data returned by these tools 
is accurate.

Tool call order for a typical fitting request:
1. get_ship_info — confirm ship bonuses and slot layout
2. get_modules_for_goal or get_modules_by_attribute — discover candidates
3. calculate_fit — validate and get stats, iterate until valid
4. export_eft — only once valid: true

When calculate_fit returns valid: false, read the errors array and 
make specific targeted changes. Do not restart from scratch unless 
the fit is fundamentally wrong for the goal.

When the user asks about NPC damage types, content recommendations, 
or general EVE meta — answer from your training knowledge. 
Only use tools for fitting mechanics, module stats, and prices.
```

---

## Project Structure

```
eve-fit-mcp/
├── server.py                  # MCP server entry point, tool registration
├── tools/
│   ├── ship_info.py           # get_ship_info implementation
│   ├── modules_for_goal.py    # get_modules_for_goal implementation
│   ├── modules_by_attribute.py # get_modules_by_attribute implementation
│   ├── calculate_fit.py       # calculate_fit implementation
│   └── export_eft.py          # export_eft implementation
├── engine/
│   └── eos_wrapper.py         # eos initialization and fit helpers
├── data/
│   ├── sde.py                 # SDE query helpers
│   ├── price_cache.py         # ESI price fetch + SQLite cache
│   └── sqlite-latest.sqlite   # Downloaded from Fuzzwork
├── config.py                  # Environment config
├── requirements.txt
└── pyproject.toml
```

---

## Data Setup

```bash
# Download SDE
wget https://www.fuzzwork.co.uk/dump/sqlite-latest.sqlite.bz2
bunzip2 sqlite-latest.sqlite.bz2
mv sqlite-latest.sqlite data/

# Clone eos
git clone https://github.com/pyfa-org/eos
pip install -e ./eos

# Install dependencies
pip install mcp fastapi uvicorn aiohttp
```

---

## Key SDE Tables

```
invTypes          → all items (ships, modules, ammo)
invGroups         → group definitions (categoryID 6=Ships, 7=Modules)
invCategories     → category definitions
dgmTypeAttributes → attribute values per typeID
dgmAttributes     → attribute definitions (IDs and names)
dgmTypeEffects    → effects per typeID
dgmEffects        → effect definitions
mapSolarSystems   → solar systems (for market region lookups)
```

### Key attribute IDs
```
11   → cpu (module requirement)
30   → pg (module requirement)  
48   → cpuOutput (ship total CPU)
11   → powerOutput (ship total PG) 
12   → lowSlots
13   → medSlots
14   → hiSlots
1137 → rigSlots
277  → requiredSkill1
278  → requiredSkill2
279  → requiredSkill3
280  → requiredSkill1Level
281  → requiredSkill2Level
282  → requiredSkill3Level
```

---

## Price Cache Schema

```sql
CREATE TABLE price_cache (
    typeID INTEGER PRIMARY KEY,
    jita_sell REAL,
    jita_buy REAL,
    fetched_at INTEGER  -- unix timestamp
);

-- Stale if fetched_at < now - 1800 (30 minutes)
```

ESI endpoint for price lookup:
```
GET https://esi.evetech.net/latest/markets/10000002/orders/
    ?order_type=sell&type_id={typeID}

Extract: min(price) WHERE is_buy_order = false
```

---

## Deployment

Target: any HTTPS host — Railway, Fly.io, or a VPS. Must be publicly accessible for Claude/Gemini web connectors to reach it.

The MCP connector URL gets added by users under:
- Claude: Settings → Connectors → Add custom connector
- Gemini: equivalent MCP connector settings

The server needs no auth for MVP — users paste their skill list into chat. OAuth/character linking can be added later as a second phase.
