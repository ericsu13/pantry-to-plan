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

:root {
  --pp-cream: #fbf8f0;
  --pp-cream-deep: #f4eee1;
  --pp-green: #2f8f5b;
  --pp-green-deep: #1f6b45;
  --pp-green-soft: #e7f3eb;
  --pp-tomato: #e2603b;
  --pp-tomato-soft: #fbe9e2;
  --pp-ink: #1f2a24;
  --pp-muted: #6b7770;
  --pp-border: #e6dfd1;
  --pp-white: #fffefa;
  --pp-shadow: 0 14px 40px rgba(53, 65, 56, 0.075);
}

/* Warm, restrained application canvas. */
#MainMenu, footer, header [data-testid="stToolbar"] { visibility: hidden; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(circle at 8% 5%, rgba(226, 96, 59, 0.08), transparent 24rem),
    radial-gradient(circle at 92% 18%, rgba(47, 143, 91, 0.07), transparent 28rem),
    var(--pp-cream);
}
.block-container { max-width: 900px; padding-top: 1.7rem; padding-bottom: 5rem; }

html, body, [class*="css"] { font-family: 'Inter', sans-serif; color: var(--pp-ink); }
h1, h2, h3, h4, .pp-brand-name, .pp-page-title {
  font-family: 'Poppins', sans-serif;
  color: var(--pp-ink);
  letter-spacing: -0.035em;
}
p { line-height: 1.62; }

/* Brand and step navigation. */
.pp-brand { text-align: center; margin: 0 auto 1.15rem; }
.pp-brand-mark {
  display: inline-flex; align-items: center; justify-content: center; gap: 0.42rem;
  padding: 0.3rem 0.78rem; margin-bottom: 0.3rem; border-radius: 999px;
  background: rgba(255, 254, 250, 0.7); border: 1px solid rgba(230, 223, 209, 0.9);
}
.pp-brand-name { font-size: 2rem; font-weight: 700; line-height: 1.2; }
.pp-brand-name .pp-dot { color: var(--pp-green); }
.pp-tagline { color: var(--pp-muted); font-size: 0.9rem; letter-spacing: 0.08em; }
.pp-nav-label {
  color: #8a938d; font-size: 0.69rem; font-weight: 700; letter-spacing: 0.12em;
  text-align: center; text-transform: uppercase; margin: 0 0 0.45rem;
}

/* Page headings. */
.pp-page-intro { max-width: 690px; margin: 0 auto 1.45rem; text-align: center; }
.pp-eyebrow {
  color: var(--pp-tomato); font-size: 0.74rem; font-weight: 700; letter-spacing: 0.13em;
  text-transform: uppercase; margin-bottom: 0.38rem;
}
.pp-page-title { font-size: clamp(1.9rem, 5vw, 2.75rem); font-weight: 700; line-height: 1.12; }
.pp-page-copy { color: var(--pp-muted); font-size: 1rem; margin: 0.55rem auto 0; max-width: 610px; }
.pp-section-label {
  color: var(--pp-green-deep); font-size: 0.75rem; font-weight: 700;
  letter-spacing: 0.11em; text-transform: uppercase; margin-bottom: 0.15rem;
}
.pp-upload-icon {
  width: 3.2rem; height: 3.2rem; display: grid; place-items: center; margin: 0 auto 0.25rem;
  border-radius: 50%; color: var(--pp-green-deep); background: var(--pp-green-soft); font-size: 1.55rem;
}

/* Native Streamlit surfaces restyled as the shared card system. */
[data-testid="stVerticalBlockBorderWrapper"] {
  background: rgba(255, 254, 250, 0.96) !important;
  border: 1px solid var(--pp-border) !important;
  border-radius: 18px !important;
  box-shadow: var(--pp-shadow);
  padding: 0.45rem 0.45rem 0.55rem;
}
[data-testid="stFileUploader"] {
  padding: 1rem; border: 1.5px dashed #b9cdbf; border-radius: 15px;
  background: #f8fbf8;
}
[data-testid="stFileUploaderDropzone"] { background: transparent; border: 0; }
[data-testid="stDataFrame"] { border: 1px solid var(--pp-border); border-radius: 14px; overflow: hidden; }
[data-testid="stExpander"] {
  background: rgba(255, 254, 250, 0.72); border-color: var(--pp-border); border-radius: 13px;
}
[data-testid="stAlert"] { border-radius: 13px; }
hr { border-color: var(--pp-border) !important; }

/* Buttons retain their native handlers and types. */
.stButton > button {
  min-height: 2.75rem; border-radius: 12px; font-weight: 700; padding: 0.55rem 1rem;
  border-color: var(--pp-border); transition: transform 140ms ease, box-shadow 140ms ease, background 140ms ease;
}
.stButton > button:hover { transform: translateY(-1px); box-shadow: 0 7px 18px rgba(31,42,36,0.09); }
.stButton > button[kind="primary"] {
  background: var(--pp-green); border-color: var(--pp-green); color: white;
}
.stButton > button[kind="primary"]:hover { background: var(--pp-green-deep); border-color: var(--pp-green-deep); }
.stButton > button[kind="secondary"] { background: rgba(255,254,250,0.88); color: var(--pp-ink); }
.stButton > button:disabled { transform: none; box-shadow: none; }
[data-testid="stBaseButton-primary"] { background: var(--pp-green); }

/* Inputs and controls. */
[data-baseweb="select"] > div, [data-baseweb="input"] > div, .stNumberInput input {
  border-radius: 11px !important; border-color: var(--pp-border) !important;
}
[data-testid="stSlider"] [role="slider"] { background: var(--pp-green); }
[data-testid="stToggle"] { padding-top: 0.15rem; }

/* Explanatory tiles and metrics. */
.pp-how-card { text-align: center; padding: 1rem 0.7rem 0.7rem; }
.pp-how-number {
  display: inline-grid; place-items: center; width: 2rem; height: 2rem; border-radius: 50%;
  color: white; background: var(--pp-tomato); font-weight: 700; font-size: 0.78rem; margin-bottom: 0.6rem;
}
.pp-how-title { font-family: 'Poppins', sans-serif; font-weight: 700; color: var(--pp-ink); }
.pp-how-copy { color: var(--pp-muted); font-size: 0.82rem; margin-top: 0.15rem; }
.pp-count-pill {
  display: inline-block; padding: 0.33rem 0.72rem; border-radius: 999px;
  color: var(--pp-green-deep); background: var(--pp-green-soft); font-size: 0.8rem; font-weight: 700;
}
[data-testid="stMetric"] {
  background: rgba(255, 254, 250, 0.94); border: 1px solid var(--pp-border);
  border-radius: 15px; padding: 0.85rem 1rem; box-shadow: 0 7px 20px rgba(53,65,56,0.05);
}
[data-testid="stMetricValue"] { color: var(--pp-green-deep); font-family: 'Poppins', sans-serif; }

/* Meal cards, badges, ingredient chips, and shopping rows. */
.pp-daytitle { font-family: 'Poppins', sans-serif; font-size: 1.35rem; font-weight: 700; margin: 0.12rem 0 0.22rem; }
.pp-daykicker { color: var(--pp-tomato); font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.13em; font-weight: 700; }
.pp-badge {
  display: inline-block; font-size: 0.74rem; font-weight: 700; padding: 0.22rem 0.62rem;
  border-radius: 999px; margin: 0.15rem 0.3rem 0.15rem 0; background: var(--pp-green-soft); color: var(--pp-green-deep);
}
.pp-badge.alt { background: var(--pp-tomato-soft); color: #ad4528; }
.pp-badge.neutral { background: var(--pp-cream-deep); color: #625f55; }
.pp-chip {
  display: inline-block; font-size: 0.81rem; padding: 0.34rem 0.68rem; border-radius: 10px;
  margin: 0.17rem 0.3rem 0.17rem 0; background: var(--pp-cream-deep); color: #3c463f; border: 1px solid var(--pp-border);
}
.pp-meal-meta { text-align: right; padding-top: 0.2rem; }
.pp-calories { color: var(--pp-ink); font-weight: 700; font-size: 0.92rem; }
.pp-coverage {
  display: inline-block; margin-top: 0.4rem; padding: 0.28rem 0.58rem; border-radius: 9px;
  color: var(--pp-green-deep); background: var(--pp-green-soft); font-size: 0.75rem; font-weight: 700;
}
.pp-shop-row {
  display: flex; justify-content: space-between; align-items: center; gap: 1rem;
  padding: 0.78rem 0.2rem; border-bottom: 1px solid #eee8dc;
}
.pp-shop-row:last-child { border-bottom: 0; }
.pp-shop-name { font-weight: 700; }
.pp-shop-qty { color: var(--pp-green-deep); font-weight: 700; white-space: nowrap; }
.pp-shop-src { color: #8a938d; font-size: 0.77rem; font-weight: 500; }

@media (max-width: 700px) {
  .block-container { padding: 1rem 1rem 3.5rem; }
  .pp-brand-name { font-size: 1.62rem; }
  .pp-page-intro { margin-bottom: 1.1rem; }
  .pp-page-title { font-size: 2rem; }
  .pp-meal-meta { text-align: left; margin-top: 0.55rem; }
  .pp-shop-row { align-items: flex-start; }
  .stButton > button { padding-left: 0.45rem; padding-right: 0.45rem; font-size: 0.83rem; }
}
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
        "<div class='pp-brand-mark'>"
        "<div class='pp-brand-name'>🍅 Pantry to Plan<span class='pp-dot'>.</span></div>"
        "</div>"
        "<div class='pp-tagline'>from shelf to supper</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    # Clickable step pills: jump back to any completed step, or restart.
    st.markdown("<div class='pp-nav-label'>Your progress</div>", unsafe_allow_html=True)
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


def _page_intro(eyebrow: str, title: str, copy: str) -> None:
    """Render the shared visual heading used by each wizard step."""
    st.markdown(
        f"<div class='pp-page-intro'>"
        f"<div class='pp-eyebrow'>{eyebrow}</div>"
        f"<div class='pp-page-title'>{title}</div>"
        f"<div class='pp-page-copy'>{copy}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------------- steps
def step_upload() -> None:
    _page_intro(
        "Step 1 · Upload",
        "Let's see what you have!",
        "Upload a photo of your pantry or fridge and we'll identify your ingredients.",
    )

    with st.container(border=True):
        st.markdown("<div class='pp-upload-icon'>↥</div>", unsafe_allow_html=True)
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

    st.markdown("<div style='height: 0.55rem'></div>", unsafe_allow_html=True)
    how_cols = st.columns(3)
    how_steps = [
        ("1", "Snap it", "Upload a photo"),
        ("2", "We identify it", "Detect your ingredients"),
        ("3", "We plan it", "Build your multi-day meal plan"),
    ]
    for col, (number, title, copy) in zip(how_cols, how_steps):
        with col:
            st.markdown(
                f"<div class='pp-how-card'><div class='pp-how-number'>{number}</div>"
                f"<div class='pp-how-title'>{title}</div>"
                f"<div class='pp-how-copy'>{copy}</div></div>",
                unsafe_allow_html=True,
            )


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

    _page_intro(
        "Step 2 · Pantry",
        "Here's what we found",
        "Review your pantry items, adjust anything you need, then confirm.",
    )
    st.markdown(
        f"<div style='text-align:center;margin:-0.55rem 0 1.15rem'>"
        f"<span class='pp-count-pill'>{len(parse_result.items)} ingredients detected</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
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

    _page_intro(
        "Step 3 · Preferences",
        "Make it yours",
        "Tell us what you like and we'll create a personalized meal plan.",
    )

    with st.container(border=True):
        st.markdown("<div class='pp-section-label'>What sounds good?</div>", unsafe_allow_html=True)
        cuisines = st.multiselect(
            "Cuisines",
            options=svc.CUISINES,
            default=[c for c in prefs.get("cuisines", []) if c in svc.CUISINES],
            format_func=str.title,
        )

    with st.container(border=True):
        st.markdown("<div class='pp-section-label'>Shape your plan</div>", unsafe_allow_html=True)
        col_a, col_b = st.columns(2)
        with col_a:
            days = st.slider(
                "Days to plan", min_value=3, max_value=5, value=int(prefs.get("days", 3))
            )
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

    with st.container(border=True):
        st.markdown("<div class='pp-section-label'>AI smart planning</div>", unsafe_allow_html=True)
        advisor_available, _advisor_reason = svc.advisor_status()
        use_advisor = st.toggle(
            "Smart planning (agentic)",
            value=advisor_available,
            disabled=not advisor_available,
            help="Let a model shape the whole week and repair days that can't be filled. "
            "The deterministic core still enforces every constraint.",
        )
        if not advisor_available:
            st.caption("AI Smart Planning is unavailable until AI configuration is enabled.")

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
            dietary = "<span class='pp-badge neutral'>Vegetarian</span>" if recipe.vegetarian else ""
            st.markdown(
                f"<span class='pp-daykicker'>Day {day_plan.day}</span>"
                f"<div class='pp-daytitle'>{recipe.title}</div>"
                f"<div>{_badges_html(recipe.cuisine_tags, day_plan.flags)}{dietary}</div>",
                unsafe_allow_html=True,
            )
        with meta:
            coverage = round(day_plan.pantry_coverage * 100)
            st.markdown(
                f"<div class='pp-meal-meta'>"
                f"<span class='pp-calories'>{recipe.calories_per_serving} kcal</span><br>"
                f"<span class='pp-shop-src'>{recipe.cook_time_min} min</span><br>"
                f"<span class='pp-coverage'>✓ {coverage}% from your pantry</span>"
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
    st.markdown(
        "<div class='pp-page-intro' style='margin-top:0.4rem;margin-bottom:1rem'>"
        "<div class='pp-eyebrow'>The finishing touches</div>"
        "<div class='pp-page-title' style='font-size:1.75rem'>Shopping list</div>"
        f"<div class='pp-page-copy'>Everything you need for your {n_days}-day meal plan, "
        "with ingredients already in your pantry removed.</div></div>",
        unsafe_allow_html=True,
    )
    if not plan.shopping_list:
        st.success("Nothing to buy: your pantry already covers the whole plan!")
        return

    titles = {d.recipe.recipe_id: d.recipe.title for d in plan.day_plans}
    with st.container(border=True):
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

    _page_intro(
        "Step 4 · Plan",
        "Your meal plan is ready!",
        "Here's your personalized plan using ingredients you already have.",
    )

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

    summary_a, summary_b = st.columns(2)
    with summary_a:
        st.metric("Days planned", n_days)
    with summary_b:
        st.metric("Items to buy", len(plan.shopping_list))
    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

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
