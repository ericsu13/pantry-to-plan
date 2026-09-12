"""Pantry to Plan - Streamlit UI (app.py, Person 4).

A thin view layer over app_services.py. This file only manages session state,
renders widgets, and calls the service functions; all parsing, persistence,
retrieval, and planning logic lives in app_services (and the P3 pipeline it
wraps). Session state holds only UI state and confirmed typed schema objects.

Run it with:  .venv/bin/streamlit run app.py
"""

import time

import streamlit as st

import app_services as svc

# ------------------------------------------------------------------- brand
PALETTE = {
    "cream": "#fbfaf6",
    "green": "#2f8f5b",
    "green_deep": "#1f6b45",
    "tomato": "#e2603b",
    "ink": "#1f2a24",
    "muted": "#6b7770",
    "border": "#ece7db",
}
STEPS = ["Upload", "Pantry", "Preferences", "Plan"]

st.set_page_config(page_title="Pantry to Plan", page_icon="🍅", layout="centered")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@500;600;700&family=Inter:wght@400;500;600&display=swap');

/* trim default chrome for a cleaner canvas */
#MainMenu, footer, header [data-testid="stToolbar"] { visibility: hidden; }
[data-testid="stHeader"] { background: transparent; }
.block-container { max-width: 760px; padding-top: 2.2rem; padding-bottom: 4rem; }

html, body, [class*="css"] { font-family: 'Inter', sans-serif; color: #1f2a24; }
h1, h2, h3, h4, .pp-brand-name { font-family: 'Poppins', sans-serif; color: #1f2a24; }

/* brand header */
.pp-brand { text-align: center; margin-bottom: 0.4rem; }
.pp-brand-name { font-size: 2.1rem; font-weight: 700; letter-spacing: -0.5px; }
.pp-brand-name .pp-dot { color: #2f8f5b; }
.pp-tagline { color: #6b7770; font-size: 0.98rem; margin-top: -0.35rem; }

/* step pills */
.pp-steps { display: flex; justify-content: center; gap: 0.4rem; margin: 1.1rem 0 1.8rem; flex-wrap: wrap; }
.pp-step { font-size: 0.82rem; font-weight: 600; padding: 0.32rem 0.85rem; border-radius: 999px;
           border: 1px solid #ece7db; color: #6b7770; background: #ffffff; }
.pp-step.active { background: #2f8f5b; color: #ffffff; border-color: #2f8f5b; }
.pp-step.done { background: #eaf4ee; color: #1f6b45; border-color: #cfe6d8; }

/* cards */
.pp-card { background: #ffffff; border: 1px solid #ece7db; border-radius: 16px;
           padding: 1.3rem 1.4rem; box-shadow: 0 6px 22px rgba(31,42,36,0.06); margin-bottom: 1rem; }
.pp-daytitle { font-family: 'Poppins', sans-serif; font-size: 1.4rem; font-weight: 700; margin: 0.1rem 0 0.15rem; }
.pp-daykicker { color: #6b7770; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }
.pp-daycount { text-align: center; color: #6b7770; font-weight: 600; padding-top: 0.45rem; }

/* badges + chips */
.pp-badge { display: inline-block; font-size: 0.76rem; font-weight: 600; padding: 0.18rem 0.6rem;
            border-radius: 999px; margin: 0.15rem 0.3rem 0.15rem 0; background: #eaf4ee; color: #1f6b45; }
.pp-badge.alt { background: #fbe7df; color: #b8461f; }
.pp-chip { display: inline-block; font-size: 0.82rem; padding: 0.28rem 0.65rem; border-radius: 10px;
           margin: 0.16rem 0.3rem 0.16rem 0; background: #f4f1e8; color: #3c463f; border: 1px solid #ece7db; }

/* shopping list rows */
.pp-shop-row { display: flex; justify-content: space-between; align-items: baseline;
               padding: 0.5rem 0; border-bottom: 1px solid #f0ece1; }
.pp-shop-name { font-weight: 600; }
.pp-shop-qty { color: #2f8f5b; font-weight: 700; }
.pp-shop-src { color: #9aa39c; font-size: 0.78rem; }

/* buttons */
.stButton > button { border-radius: 11px; font-weight: 600; padding: 0.5rem 1rem; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ------------------------------------------------------------- session state
def _init_state() -> None:
    defaults = {
        "step": 1,
        "parse_result": None,   # PantryParseResult
        "pantry": None,         # confirmed PantryState
        "prefs": None,          # preferences dict
        "use_advisor": False,   # UI toggle
        "plan": None,           # PlanResult
        "day_index": 0,
        "source": None,         # "photo" | "demo"
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def go_to(step: int) -> None:
    st.session_state.step = step
    st.rerun()


def reset_all() -> None:
    for key in ("parse_result", "pantry", "plan", "source"):
        st.session_state[key] = None
    st.session_state.day_index = 0
    go_to(1)


# ---------------------------------------------------------------- chrome
def render_chrome(active: int) -> None:
    st.markdown(
        "<div class='pp-brand'>"
        "<div class='pp-brand-name'>🍅 Pantry to Plan<span class='pp-dot'>.</span></div>"
        "<div class='pp-tagline'>from shelf to supper</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    pills = []
    for i, label in enumerate(STEPS, start=1):
        cls = "active" if i == active else ("done" if i < active else "")
        pills.append(f"<span class='pp-step {cls}'>{i}. {label}</span>")
    st.markdown(f"<div class='pp-steps'>{''.join(pills)}</div>", unsafe_allow_html=True)


# ------------------------------------------------------------------- steps
def step_upload() -> None:
    st.subheader("Snap your pantry")
    st.caption("Upload a photo of your shelves or fridge. No photo handy? Use our demo pantry.")

    uploaded = st.file_uploader(
        "Pantry photo", type=["png", "jpg", "jpeg"], label_visibility="collapsed"
    )
    if uploaded is not None:
        st.image(uploaded, caption="Your pantry", use_container_width=True)

    left, right = st.columns(2)
    with left:
        read = st.button(
            "Read my pantry", type="primary", use_container_width=True, disabled=uploaded is None
        )
    with right:
        demo = st.button("Use the demo pantry", use_container_width=True)

    if read and uploaded is not None:
        st.session_state.parse_result = svc.parse_pantry_image(uploaded.getvalue())
        st.session_state.source = "photo"
        go_to(2)
    if demo:
        st.session_state.parse_result = svc.load_demo_parse_result()
        st.session_state.source = "demo"
        go_to(2)


def step_confirm() -> None:
    parse_result = st.session_state.parse_result
    if parse_result is None:
        go_to(1)

    st.subheader("Confirm your pantry")
    if st.session_state.source == "photo":
        st.caption(
            "This is a preview parse (the vision model is not wired in yet). "
            "Adjust anything below, then confirm."
        )
    else:
        st.caption("Adjust quantities, add or remove items, then confirm.")

    for warning in parse_result.warnings:
        st.warning(warning)

    flagged = svc.flagged_items(parse_result)
    if flagged:
        names = ", ".join(it.display_name for it in flagged)
        st.warning(f"Please double-check these before continuing: {names}")
    else:
        st.success("Everything looks clear. Tweak anything you like, then confirm.")

    rows = [
        {
            "ingredient_id": it.ingredient_id,
            "display_name": it.display_name,
            "quantity_g": it.quantity_g,
            "confidence": round(it.confidence, 2) if it.confidence is not None else None,
        }
        for it in parse_result.items
    ]
    edited = st.data_editor(
        rows,
        num_rows="dynamic",
        use_container_width=True,
        key="pantry_editor",
        column_config={
            "ingredient_id": st.column_config.TextColumn("Ingredient id", required=True),
            "display_name": st.column_config.TextColumn("Name"),
            "quantity_g": st.column_config.NumberColumn("Grams", min_value=0, format="%d g"),
            "confidence": st.column_config.NumberColumn(
                "Confidence", min_value=0.0, max_value=1.0, format="%.2f"
            ),
        },
    )

    back, forward = st.columns(2)
    if back.button("Back", use_container_width=True):
        go_to(1)
    if forward.button("Confirm pantry", type="primary", use_container_width=True):
        st.session_state.pantry = svc.build_pantry_state(list(edited))
        go_to(3)


def step_preferences() -> None:
    if st.session_state.prefs is None:
        st.session_state.prefs = svc.load_preferences()
    prefs = st.session_state.prefs

    st.subheader("Your preferences")
    st.caption("Defaults are loaded from file. Changes are saved for next time.")

    cuisines = st.multiselect(
        "Cuisines",
        options=svc.CUISINES,
        default=[c for c in prefs.get("cuisines", []) if c in svc.CUISINES],
        format_func=str.title,
    )
    col_a, col_b = st.columns(2)
    with col_a:
        days = st.slider("Days to plan", min_value=3, max_value=5, value=int(prefs.get("days", 3)))
    with col_b:
        target = st.slider(
            "Dinner calorie target",
            min_value=300,
            max_value=1000,
            step=25,
            value=int(prefs.get("dinner_calorie_target", 600)),
        )
    col_c, col_d = st.columns(2)
    with col_c:
        goal_default = prefs.get("goal", "general")
        goal = st.selectbox(
            "Goal",
            options=svc.GOALS,
            index=svc.GOALS.index(goal_default) if goal_default in svc.GOALS else 0,
            format_func=str.title,
        )
    with col_d:
        vegetarian = st.toggle(
            "Vegetarian only", value=bool(prefs.get("vegetarian_required", False))
        )

    advisor_available, advisor_reason = svc.advisor_status()
    use_advisor = st.toggle(
        "Smart planning (agentic)",
        value=False,
        disabled=not advisor_available,
        help="Let a model shape the whole week and repair days that can't be filled. "
        "The deterministic core still enforces every constraint.",
    )
    if not advisor_available:
        st.caption(advisor_reason)

    if not cuisines:
        st.warning("Pick at least one cuisine to build a plan.")

    back, forward = st.columns(2)
    if back.button("Back", use_container_width=True):
        go_to(2)
    build = forward.button(
        "Build my plan", type="primary", use_container_width=True, disabled=not cuisines
    )
    if not build:
        return

    new_prefs = {
        "cuisines": cuisines,
        "dinner_calorie_target": int(target),
        "days": int(days),
        "vegetarian_required": bool(vegetarian),
        "goal": goal,
    }
    svc.save_preferences(new_prefs)
    st.session_state.prefs = new_prefs
    st.session_state.use_advisor = bool(use_advisor and advisor_available)

    request = svc.build_request(new_prefs)
    advisor = svc.build_advisor() if st.session_state.use_advisor else None

    with st.status("Cooking up your plan...", expanded=True) as status:
        def progress(msg: str) -> None:
            st.write(msg)
            time.sleep(0.35)

        try:
            plan = svc.run_plan(st.session_state.pantry, request, advisor=advisor, progress=progress)
        except Exception:  # noqa: BLE001 - agentic path can fail on a live call; degrade gracefully
            if advisor is not None:
                st.write("Smart planning hit a snag; using the standard planner instead.")
                plan = svc.run_plan(st.session_state.pantry, request, advisor=None, progress=progress)
            else:
                raise
        status.update(label="Your plan is ready!", state="complete")

    st.session_state.plan = plan
    st.session_state.day_index = 0
    go_to(4)


def _badges_html(cuisine_tags, flags) -> str:
    parts = [f"<span class='pp-badge'>{t.title()}</span>" for t in cuisine_tags]
    for flag in flags:
        label = svc.FLAG_LABELS.get(flag, flag.replace("_", " ").title())
        parts.append(f"<span class='pp-badge alt'>{label}</span>")
    return "".join(parts)


def _day_card(day_plan) -> None:
    recipe = day_plan.recipe
    st.markdown(
        f"<div class='pp-card'>"
        f"<div class='pp-daykicker'>Day {day_plan.day}</div>"
        f"<div class='pp-daytitle'>{recipe.title}</div>"
        f"<div>{_badges_html(recipe.cuisine_tags, day_plan.flags)}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    m1, m2, m3 = st.columns(3)
    m1.metric(
        "Calories",
        f"{recipe.calories_per_serving} kcal",
        delta=f"{day_plan.calorie_delta:+d} vs target",
        delta_color="inverse",
    )
    m2.metric("Already on hand", f"{round(day_plan.pantry_coverage * 100)}%")
    m3.metric("Cuisine", "Match" if day_plan.cuisine_match else "Cross")

    chips = []
    for ing in recipe.ingredients:
        name = ing.display_name or ing.ingredient_id.replace("_", " ").title()
        chips.append(f"<span class='pp-chip'>{name} · {int(ing.quantity_g)} g</span>")
    st.markdown("**Ingredients**")
    st.markdown(f"<div>{''.join(chips)}</div>", unsafe_allow_html=True)


def _shopping_list(plan) -> None:
    st.markdown("### Shopping list")
    if not plan.shopping_list:
        st.success("Nothing to buy - your pantry already covers the whole plan!")
        return
    for item in plan.shopping_list:
        name = item.display_name or item.ingredient_id.replace("_", " ").title()
        recipes = ", ".join(r.replace("_", " ").title() for r in item.contributing_recipe_ids)
        st.markdown(
            f"<div class='pp-shop-row'>"
            f"<span class='pp-shop-name'>{name}<br><span class='pp-shop-src'>for {recipes}</span></span>"
            f"<span class='pp-shop-qty'>{int(item.quantity_g)} g</span>"
            f"</div>",
            unsafe_allow_html=True,
        )


def step_results() -> None:
    plan = st.session_state.plan
    if plan is None:
        go_to(1)

    st.subheader("Your dinner plan")

    shown = set()
    for code in plan.warnings:
        if code in shown:
            continue
        shown.add(code)
        st.warning(svc.describe_warning(code))

    n_days = len(plan.day_plans)
    if n_days < plan.requested_days:
        st.info(f"Showing {n_days} of {plan.requested_days} requested days.")

    if n_days == 0:
        st.error("No plan could be built from this pantry and these preferences.")
        if st.button("Start over", type="primary"):
            reset_all()
        return

    idx = min(st.session_state.day_index, n_days - 1)

    # jump-to-day buttons
    day_cols = st.columns(n_days)
    for i, col in enumerate(day_cols):
        if col.button(
            f"Day {i + 1}",
            key=f"jump_{i}",
            type="primary" if i == idx else "secondary",
            use_container_width=True,
        ):
            st.session_state.day_index = i
            st.rerun()

    _day_card(plan.day_plans[idx])

    prev_col, mid_col, next_col = st.columns([1, 2, 1])
    if prev_col.button("< Prev", use_container_width=True, disabled=idx == 0):
        st.session_state.day_index = idx - 1
        st.rerun()
    mid_col.markdown(f"<div class='pp-daycount'>Day {idx + 1} of {n_days}</div>", unsafe_allow_html=True)
    if next_col.button("Next >", use_container_width=True, disabled=idx == n_days - 1):
        st.session_state.day_index = idx + 1
        st.rerun()

    st.divider()
    _shopping_list(plan)

    st.divider()
    if st.button("Start over", use_container_width=True):
        reset_all()


# ------------------------------------------------------------------- main
def main() -> None:
    _init_state()
    render_chrome(st.session_state.step)
    {
        1: step_upload,
        2: step_confirm,
        3: step_preferences,
        4: step_results,
    }[st.session_state.step]()


main()
