"""Pantry to Plan - Streamlit UI (app.py, Person 4).

A thin view layer over app_services.py. This file only manages session state,
renders widgets, and calls the service functions; all parsing, persistence,
retrieval, and planning logic lives in app_services (and the P3 pipeline it
wraps). Session state holds only UI state and confirmed typed schema objects.

Run it with:  .venv/bin/streamlit run app.py
"""

import time

import streamlit as st
from pydantic import ValidationError

import app_services as svc

# Confirm-step table columns, in display order. Mirrors the standalone vision UI
# so the wizard's human-in-the-loop review shows the same rich signals.
EDITOR_COLUMNS = [
    "include",
    "display_name",
    "ingredient_id",
    "quantity_g",
    "confidence",
    "source_text",
    "normalization_status",
    "recipe_supported",
]

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
        "editor_rows": None,    # confirm-step table rows (list[dict])
        "editor_version": 0,    # bumped to re-seed the editor after a manual add
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
    for key in ("parse_result", "editor_rows", "pantry", "plan", "source"):
        st.session_state[key] = None
    st.session_state.day_index = 0
    st.session_state.editor_version += 1
    go_to(1)


def _seed_parse_result(result, source: str) -> None:
    """Store a fresh parse and (re)seed the confirm-step editor rows from it."""
    st.session_state.parse_result = result
    st.session_state.editor_rows = svc.rows_from_parse_result(result)
    st.session_state.editor_version += 1
    st.session_state.source = source
    go_to(2)


# ---------------------------------------------------------------- chrome
def _reachable_steps() -> dict[int, bool]:
    """Which steps the user may jump to. A step opens once its input exists, so
    you can always backtrack to a completed step (and to any later step whose
    prerequisite is already satisfied)."""
    return {
        1: True,
        2: st.session_state.parse_result is not None,
        3: st.session_state.pantry is not None,
        4: st.session_state.plan is not None,
    }


def render_chrome(active: int) -> None:
    st.markdown(
        "<div class='pp-brand'>"
        "<div class='pp-brand-name'>🍅 Pantry to Plan<span class='pp-dot'>.</span></div>"
        "<div class='pp-tagline'>from shelf to supper</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    # Clickable step pills: jump back to any completed step, or restart.
    reachable = _reachable_steps()
    cols = st.columns([1, 1, 1, 1, 0.9])
    for i, label in enumerate(STEPS, start=1):
        with cols[i - 1]:
            if st.button(
                f"{i}. {label}",
                key=f"nav_{i}",
                type="primary" if i == active else "secondary",
                use_container_width=True,
                disabled=(i != active and not reachable[i]),
            ):
                go_to(i)
    with cols[-1]:
        if st.button("↺ Restart", key="nav_restart", use_container_width=True):
            reset_all()
    st.markdown("<div style='margin-bottom: 1.2rem;'></div>", unsafe_allow_html=True)


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
        try:
            with st.spinner("Reading your pantry photo: scanning the shelves and naming ingredients..."):
                result = svc.parse_pantry_image(uploaded.getvalue())
        except svc.VisionError as exc:
            issue = getattr(exc, "issue", None)
            st.error(getattr(issue, "message", str(exc)))
            hint = getattr(issue, "suggested_action", None)
            if hint:
                st.caption(hint)
        else:
            _seed_parse_result(result, "photo")
    if demo:
        _seed_parse_result(svc.load_demo_parse_result(), "demo")


def step_confirm() -> None:
    parse_result = st.session_state.parse_result
    if parse_result is None:
        go_to(1)
        return
    if st.session_state.editor_rows is None:
        st.session_state.editor_rows = svc.rows_from_parse_result(parse_result)

    # The review table has eight columns and, for a full pantry, many rows. Widen
    # this step past the wizard's default reading column so nothing clips on the
    # right, and size the editor to its row count below so the page (not a tiny
    # inner scrollbar) handles a long pantry.
    st.markdown(
        "<style>.block-container { max-width: 1180px; }</style>",
        unsafe_allow_html=True,
    )

    st.subheader("Confirm your pantry")
    if st.session_state.source == "photo":
        st.caption(
            "This is what we read from your photo. Uncheck anything you don't want "
            "in the plan, fix a label or quantity, or add items by hand."
        )
    else:
        st.caption(
            "Uncheck anything you don't want in the plan, adjust quantities, or "
            "add items by hand, then confirm."
        )

    for warning in parse_result.warnings:
        st.warning(warning)
    if parse_result.issues:
        with st.expander(f"Review notes ({len(parse_result.issues)})", expanded=True):
            for issue in parse_result.issues:
                st.warning(f"**{issue.code}** - {issue.message}")

    # Size the editor to its rows (header + one dynamic add-row line + a hair) so
    # every item shows and the page scrolls, instead of clipping inside a fixed
    # ~10-row box. Capped so a huge pantry doesn't push everything else offscreen.
    row_count = len(st.session_state.editor_rows)
    editor_height = min(int((row_count + 2) * 35 + 3), 900)

    edited = st.data_editor(
        st.session_state.editor_rows,
        key=f"pantry_editor_{st.session_state.editor_version}",
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        height=editor_height,
        column_order=EDITOR_COLUMNS,
        column_config={
            "include": st.column_config.CheckboxColumn(
                "Include", default=True, width="small", help="Only checked items go into the plan."
            ),
            "display_name": st.column_config.TextColumn("Ingredient", required=True, width="medium"),
            "ingredient_id": st.column_config.TextColumn(
                "Canonical ID", required=True, width="medium", help="Lowercase snake_case."
            ),
            "quantity_g": st.column_config.NumberColumn(
                "Quantity (g)", min_value=0.0, step=1.0, format="%d g", width="small"
            ),
            "confidence": st.column_config.ProgressColumn(
                "Confidence", min_value=0.0, max_value=1.0, format="%.2f", width="small"
            ),
            "source_text": st.column_config.TextColumn("Detected label", width="medium"),
            "normalization_status": st.column_config.TextColumn("Mapping", width="small"),
            "recipe_supported": st.column_config.CheckboxColumn("Used by recipes", width="small"),
        },
        disabled=("confidence", "source_text", "normalization_status", "recipe_supported"),
    )

    flagged = svc.flagged_rows(list(edited))
    if flagged:
        st.warning(f"Please double-check these before continuing: {', '.join(flagged)}")
    else:
        st.success("Everything looks clear. Tweak anything you like, then confirm.")

    st.caption(
        "Only checked rows are planned. Edit names and canonical IDs or remove "
        "rows; a canonical ID must use lowercase snake_case."
    )

    with st.expander("Add an ingredient manually"):
        manual_name = st.text_input("Ingredient name", key="manual_ingredient_name")
        if st.button("Add ingredient", use_container_width=True):
            if not manual_name.strip():
                st.warning("Enter an ingredient name first.")
            else:
                st.session_state.editor_rows = list(edited) + [
                    svc.manual_ingredient_row(manual_name)
                ]
                st.session_state.editor_version += 1
                st.rerun()

    back, forward = st.columns(2)
    if back.button("Back", use_container_width=True):
        st.session_state.editor_rows = list(edited)
        go_to(1)
    if forward.button("Confirm pantry", type="primary", use_container_width=True):
        try:
            pantry = svc.pantry_from_rows(list(edited))
        except (ValidationError, ValueError, TypeError) as exc:
            st.error(f"Please fix the table before confirming: {exc}")
        else:
            if not pantry.items:
                st.warning("Include at least one ingredient to build a plan.")
            else:
                st.session_state.editor_rows = list(edited)
                st.session_state.pantry = pantry
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
        value=advisor_available,
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


def _day_row(day_plan) -> None:
    """One compact card per day: title, cuisine/flag badges, calories, cook time,
    and how much is already on hand. The recipe's ingredients live in a collapsed
    expander so the whole week reads at a glance."""
    recipe = day_plan.recipe
    with st.container(border=True):
        head, meta = st.columns([3, 1])
        with head:
            st.markdown(
                f"<span class='pp-daykicker'>Day {day_plan.day}</span>"
                f"<div class='pp-daytitle'>{recipe.title}</div>"
                f"<div>{_badges_html(recipe.cuisine_tags, day_plan.flags)}</div>",
                unsafe_allow_html=True,
            )
        with meta:
            st.markdown(
                f"<div style='text-align:right'>"
                f"<span class='pp-shop-qty'>{recipe.calories_per_serving} kcal</span><br>"
                f"<span class='pp-shop-src'>{recipe.cook_time_min} min · "
                f"{round(day_plan.pantry_coverage * 100)}% on hand</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        with st.expander("Ingredients"):
            chips = [
                f"<span class='pp-chip'>"
                f"{ing.display_name or ing.ingredient_id.replace('_', ' ').title()} · "
                f"{int(ing.quantity_g)} g</span>"
                for ing in recipe.ingredients
            ]
            st.markdown(f"<div>{''.join(chips)}</div>", unsafe_allow_html=True)


def _shopping_list(plan) -> None:
    n_days = len(plan.day_plans)
    st.markdown("### Shopping list")
    st.caption(
        f"One combined list for all {n_days} dinners, with shared ingredients "
        "merged and anything already in your pantry subtracted."
    )
    if not plan.shopping_list:
        st.success("Nothing to buy: your pantry already covers the whole plan!")
        return

    titles = {d.recipe.recipe_id: d.recipe.title for d in plan.day_plans}
    for item in plan.shopping_list:
        name = item.display_name or item.ingredient_id.replace("_", " ").title()
        recipes = ", ".join(
            titles.get(r, r.replace("_", " ").title()) for r in item.contributing_recipe_ids
        )
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
        return

    st.subheader("Your dinner plan")

    shown = set()
    for code in plan.warnings:
        if code in shown:
            continue
        shown.add(code)
        st.warning(svc.describe_warning(code))

    n_days = len(plan.day_plans)
    if n_days == 0:
        st.error("No plan could be built from this pantry and these preferences.")
        if st.button("Start over", type="primary"):
            reset_all()
        return

    if n_days < plan.requested_days:
        st.info(f"Showing {n_days} of {plan.requested_days} requested days.")

    for day_plan in plan.day_plans:
        _day_row(day_plan)

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
