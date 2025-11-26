# app.py
import streamlit as st
from datetime import datetime, time, timedelta
from pymongo import MongoClient, ReturnDocument

# Google Sheets
from google.oauth2.service_account import Credentials
import gspread
from gspread.exceptions import WorksheetNotFound
from zoneinfo import ZoneInfo
import json

# ❗ MUST be the first Streamlit command in the file:
st.set_page_config(page_title="Straddle Shift Strategy Controls", page_icon="🟢", layout="centered")


class StraddleShiftInput:
    # ---------------- Time/Display Constants ----------------
    # Allowed trading time window
    MIN_T = time(9, 15, 0)
    MAX_T = time(15, 30, 0)

    DEFAULT_START = time(9, 15, 0)  # 09:15:00
    DEFAULT_END = time(15, 15, 0)   # 15:15:00

    # Google Sheet scope (static)
    GSCOPE = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    # --------- Streamlit Cached Resources ----------
    @staticmethod
    @st.cache_resource
    def _get_mongo_client(uri: str):
        # NOTE: move credentials to env vars for production use.
        return MongoClient(uri)

    @staticmethod
    @st.cache_resource
    def _get_gsheet(creds_source, scope: list[str], spreadsheet_url: str, worksheet_name: str):
        """
        Accepts Google creds as:
        - dict (service account info),
        - JSON string (service account info),
        - file path to a JSON key.
        """


        # Build Credentials from whichever type we got
        if isinstance(creds_source, dict):
            creds = Credentials.from_service_account_info(creds_source, scopes=scope)
        elif isinstance(creds_source, str):
            # Try JSON first; if that fails, treat as file path
            try:
                creds_info = json.loads(creds_source)
                creds = Credentials.from_service_account_info(creds_info, scopes=scope)
            except json.JSONDecodeError:
                creds = Credentials.from_service_account_file(creds_source, scopes=scope)
        else:
            raise TypeError("Provide creds as dict, JSON string, or file path.")

        client = gspread.authorize(creds)
        sh = client.open_by_url(spreadsheet_url)
        try:
            ws = sh.worksheet(worksheet_name)
        except WorksheetNotFound:
            ws = sh.add_worksheet(title=worksheet_name, rows=1000, cols=50)
        return ws

    # ---------------- Init ----------------
    def __init__(self) -> None:
        # ---- Load from Streamlit secrets ----

        self.DB_NAME            = st.secrets["app"]["db_name"]
        self.COLLECTION_NAME    = st.secrets["app"]["collection_name"]
        self.STRATEGY_ID        = st.secrets["app"]["strategy_id"]
        self.GS_SPREADSHEET_URL = st.secrets["app"]["gs_spreadsheet_url"]
        self.GS_WORKSHEET_NAME  = st.secrets["app"]["gs_worksheet_name"]

        self.MONGO_URI = st.secrets["mongo"]["uri"]

        self.GSCOPE = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        self.GS_CREDS_INFO = dict(st.secrets["google_service_account"])
        self.creds = Credentials.from_service_account_info(self.GS_CREDS_INFO, scopes=self.GSCOPE)

        # Clients
        self.mongo_client = MongoClient(self.MONGO_URI, tls=True, tlsAllowInvalidCertificates=True)
        self.db = self.mongo_client[self.DB_NAME]
        self.collection = self.db[self.COLLECTION_NAME]

        self.gc = gspread.authorize(self.creds)
        self.ws = self.gc.open_by_url(self.GS_SPREADSHEET_URL).worksheet(self.GS_WORKSHEET_NAME)

        # Build the allowed time choices once (09:15:00 → 15:30:00, 1-minute steps)
        self.allowed_times, self.allowed_labels = self._build_time_options(self.MIN_T, self.MAX_T)

       
    # ---------------- Page Setup ----------------
    def _config_page(self):
        st.title("Selected Strategies Inputs • CST0005")
        st.markdown(
            """
                <style>
                .inline-label {
                font-size: 0.92rem;
                line-height: 1.7;
                padding-top: 0.25rem;
                white-space: nowrap;
                }
                </style>
                """,
            unsafe_allow_html=True,
        )

    # ---------------- Time Utils ----------------
    def _parse_time_hms(self, s: str, default_t: time) -> time:
        try:
            hh, mm, *rest = s.split(":")
            ss = int(rest[0]) if rest else 0
            return time(int(hh), int(mm), ss)
        except Exception:
            return default_t

    def _fmt_hms(self, t: time) -> str:
        return t.strftime("%H:%M:%S")

    def _build_time_options(self, min_t: time, max_t: time):
        base = datetime(2000, 1, 1)
        start_dt = datetime.combine(base.date(), min_t)
        end_dt = datetime.combine(base.date(), max_t)
        times = []
        cur = start_dt
        while cur <= end_dt:
            times.append(cur.time())
            cur += timedelta(minutes=1)
        labels = [t.strftime("%H:%M:%S") for t in times]
        return times, labels

    def _time_to_index(self, t: time) -> int:
        try:
            return self.allowed_times.index(t)
        except ValueError:
            def seconds_between(a: time, b: time) -> float:
                d0 = datetime.combine(datetime(2000, 1, 1), a)
                d1 = datetime.combine(datetime(2000, 1, 1), b)
                return abs((d0 - d1).total_seconds())
            return min(
                range(len(self.allowed_times)),
                key=lambda i: seconds_between(self.allowed_times[i], t),
            )

    def _clamp_and_parse_time(self, existing: dict | None, key: str, fallback: time) -> time:
        if existing and isinstance(existing.get(key), str):
            t = self._parse_time_hms(existing[key], fallback)
        else:
            t = fallback
        if t < self.MIN_T:
            t = self.MIN_T
        if t > self.MAX_T:
            t = self.MAX_T
        return t

    # ---------------- Prefill Helpers ----------------
    def _pre_bool(self, existing: dict | None, key: str, default=False) -> bool:
        return bool(existing.get(key, default)) if existing else default

    def _pre_int(self, existing: dict | None, key: str, default: int = 0) -> int:
        if not existing:
            return default
        try:
            v = existing.get(key, default)
            return int(v) if v is not None else default
        except Exception:
            return default

    def _pre_str(self, existing: dict | None, key: str, default: str = "") -> str:
        if not existing:
            return default
        try:
            v = existing.get(key, default)
            return str(v) if v is not None else default
        except Exception:
            return default

    # ---------------- Mongo Access ----------------
    def _get_collection(self, db_name: str):
        if not db_name:
            return None
        db = self.mongo_client[db_name]  # DB name == client_id
        return db[self.COLLECTION_NAME]

    def _load_existing(self, db_name: str):
        col = self._get_collection(db_name)
        if col is None:
            return None
        return col.find_one({"StrategyID": self.STRATEGY_ID})

    def _upsert_strategy(self, db_name: str, doc: dict):
        col = self._get_collection(db_name)
        if col is None:
            return None
        return col.find_one_and_update(
            {"StrategyID": self.STRATEGY_ID},
            {"$set": doc, "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

    # ---------------- Google Sheet Helpers ----------------
    def _ensure_gsheet_header(self):
        try:
            a1 = self.ws.acell("A1").value
        except Exception:
            a1 = None
        if not a1:
            header = [
                "SavedAt_IST", "SavedAt_UTC",
                "ClientID", "StrategyID",
                "Start", "Pause", "Stop",
                "CallEntry", "PutEntry", "ShiftHedge","FirstEntry",
                "ShiftPoints", "HedgePoints", "OTMPoints",
                "Symbol", "ExpiryNo", "OrderLot",
                "StartTime", "EndTime",
            ]
            self.ws.append_row(header, value_input_option="USER_ENTERED")

    def _append_to_gsheet(self, client_id: str, doc: dict):
        ist_now = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")
        utc_now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        self._ensure_gsheet_header()
        row = [
            ist_now,
            utc_now,
            client_id,
            doc.get("StrategyID", ""),
            str(doc.get("Start", False)),
            str(doc.get("Pause", False)),
            str(doc.get("Stop", False)),
            str(doc.get("CallEntry", False)),
            str(doc.get("PutEntry", False)),
            str(doc.get("ShiftHedge", False)),
            str(doc.get("FirstEntry", False)),
            str(doc.get("ShiftPoints", "")),
            str(doc.get("HedgePoints", "")),
            str(doc.get("OTMPoints", "")),
            str(doc.get("Symbol", "")),
            str(doc.get("ExpiryNo", "")),
            str(doc.get("OrderLot", "")),
            str(doc.get("StartTime", "")),
            str(doc.get("EndTime", "")),
        ]
        self.ws.append_row(row, value_input_option="USER_ENTERED")

    # ---------------- Inline UI Primitives ----------------
    def _inline_label(self, text: str):
        st.markdown(f"<div class='inline-label'>{text}</div>", unsafe_allow_html=True)

    def _inline_checkbox(self, label: str, key: str, value: bool = False) -> bool:
        lcol, icol = st.columns([1, 1.3], vertical_alignment="center")
        with lcol:
            self._inline_label(label)
        with icol:
            return st.checkbox(label="", key=key, value=value, label_visibility="collapsed")

    def _inline_text(self, label: str, key: str, value: str = "", placeholder: str = "") -> str:
        lcol, icol = st.columns([1, 1.3], vertical_alignment="center")
        with lcol:
            self._inline_label(label)
        with icol:
            return st.text_input(
                label="", key=key, value=value, placeholder=placeholder, label_visibility="collapsed"
            )

    def _inline_number(self, label: str, key: str, value: int = 0, min_value: int | None = None) -> int:
        # integer number input with label inline
        lcol, icol = st.columns([1, 1.3], vertical_alignment="center")
        with lcol:
            self._inline_label(label)
        with icol:
            if min_value is not None:
                return int(st.number_input(label="", key=key, value=int(value), min_value=int(min_value), step=1, format="%d", label_visibility="collapsed"))
            else:
                return int(st.number_input(label="", key=key, value=int(value), step=1, format="%d", label_visibility="collapsed"))

    # ---------------- Validation ----------------
    def _digits_only(self, s: str) -> bool:
        return s.isdigit()

    # ---------------- UI Sections ----------------
    def _client_input(self) -> tuple[str, dict | None]:
        client_id = st.text_input(
            "Enter Client ID",
            placeholder="e.g. CL001",
            autocomplete="off",
            key="client_id_input",
        )
        existing = self._load_existing(client_id) if client_id else None
        return client_id, existing

    def _controls_section(self, existing: dict | None, k: str):
        st.subheader("Controls")
        c1, c2, c3, c4 = st.columns(4)

        with c1:
            Start = self._inline_checkbox("Start", key=f"Start_{k}", value=self._pre_bool(existing, "Start"))
            Pause = self._inline_checkbox("Pause", key=f"Pause_{k}", value=self._pre_bool(existing, "Pause"))
            Stop = self._inline_checkbox("Stop", key=f"Stop_{k}", value=self._pre_bool(existing, "Stop"))

        with c2:
            CallEntry = self._inline_checkbox("CallEntry", key=f"CallEntry_{k}", value=self._pre_bool(existing, "CallEntry"))
            PutEntry = self._inline_checkbox("PutEntry", key=f"PutEntry_{k}", value=self._pre_bool(existing, "PutEntry"))
            ShiftHedge = self._inline_checkbox("ShiftHedge", key=f"ShiftHedge_{k}", value=self._pre_bool(existing, "ShiftHedge"))
            FirstEntry = self._inline_checkbox("FirstEntry", key=f"FirstEntry_{k}", value=self._pre_bool(existing, "FirstEntry"))

        with c3:
            OTMPoints = self._inline_number(
                "OTMPoints", key=f"OTMPoints_{k}",
                value=self._pre_int(existing, "OTMPoints", 0), min_value=0
            )
            HedgePoints = self._inline_number(
                "HedgePoints", key=f"HedgePoints_{k}",
                value=self._pre_int(existing, "HedgePoints", 0), min_value=0
            )
            ShiftPoints = self._inline_number(
                "ShiftPoints", key=f"ShiftPoints_{k}",
                value=self._pre_int(existing, "ShiftPoints", 0), min_value=0
            )

        with c4:
            Symbol = self._inline_text(
                "Symbol", key=f"Symbol_{k}",
                value=self._pre_str(existing, "Symbol", ""), placeholder="e.g. NIFTY"
            )
            ExpiryNo = self._inline_number(
                "ExpiryNo", key=f"ExpiryNo_{k}",
                value=self._pre_int(existing, "ExpiryNo", 0), min_value=0
            )
            OrderLot = self._inline_number(
                "OrderLot", key=f"OrderLot_{k}",
                value=self._pre_int(existing, "OrderLot", 1), min_value=1
            )

        return {
            "Start": Start, "Pause": Pause, "Stop": Stop,
            "CallEntry": CallEntry, "PutEntry": PutEntry, "ShiftHedge": ShiftHedge,"FirstEntry": FirstEntry,
            "OTMPoints": OTMPoints, "HedgePoints": HedgePoints, "ShiftPoints": ShiftPoints,
            "Symbol": Symbol, "ExpiryNo": ExpiryNo, "OrderLot": OrderLot
        }

    def _timing_section(self, existing: dict | None, k: str):
        st.subheader("Timing (allowed only 09:15:00 to 15:30:00)")
        pre_start_t = self._clamp_and_parse_time(existing, "StartTime", self.DEFAULT_START)
        pre_end_t = self._clamp_and_parse_time(existing, "EndTime", self.DEFAULT_END)

        start_idx_default = self._time_to_index(pre_start_t)
        end_idx_default = self._time_to_index(pre_end_t)

        StartTimeLabel = self._inline_select(
            "StartTime", key=f"StartTime_{k}",
            options=self.allowed_labels, index=start_idx_default,
            help="Only allowed times are listed."
        )
        EndTimeLabel = self._inline_select(
            "EndTime", key=f"EndTime_{k}",
            options=self.allowed_labels, index=end_idx_default,
            help="Only allowed times are listed."
        )

        st.caption("⏱️ Allowed time range: **09:15:00** to **15:30:00** (1-minute steps).")

        StartTime = self.allowed_times[self.allowed_labels.index(StartTimeLabel)]
        EndTime = self.allowed_times[self.allowed_labels.index(EndTimeLabel)]

        st.divider()
        return StartTime, EndTime

    def _save_section(self, client_id: str, ui_values: dict, StartTime: time, EndTime: time):
        # Save button is handled by the form submit (see run)
        if not st.session_state.get("_form_submitted", False):
            return

        # Reset flag
        st.session_state["_form_submitted"] = False

        if not client_id:
            st.error("client_id (DB name) enter kijiye.")
            return

        errors = []
        # All numeric fields are coming as ints because we used number_input
        if not isinstance(ui_values["ShiftPoints"], int) or ui_values["ShiftPoints"] < 0:
            errors.append("ShiftPoints must be a non-negative integer.")
        if not isinstance(ui_values["HedgePoints"], int) or ui_values["HedgePoints"] < 0:
            errors.append("HedgePoints must be a non-negative integer.")
        if not isinstance(ui_values["OTMPoints"], int) or ui_values["OTMPoints"] < 0:
            errors.append("OTMPoints must be a non-negative integer.")
        if not isinstance(ui_values["ExpiryNo"], int) or ui_values["ExpiryNo"] < 0:
            errors.append("ExpiryNo must be a non-negative integer.")
        if not isinstance(ui_values["OrderLot"], int) or ui_values["OrderLot"] < 1:
            errors.append("OrderLot must be an integer ≥ 1.")
        if StartTime > EndTime:
            errors.append("StartTime must be ≤ EndTime")

        if errors:
            for e in errors:
                st.error(e)
            return

        # All good — build doc
        doc = {
            "StrategyID": self.STRATEGY_ID,
            "Start": bool(ui_values["Start"]),
            "Pause": bool(ui_values["Pause"]),
            "Stop": bool(ui_values["Stop"]),
            "ShiftHedge": bool(ui_values["ShiftHedge"]),
            "CallEntry": bool(ui_values["CallEntry"]),
            "PutEntry": bool(ui_values["PutEntry"]),
            "FirstEntry": bool(ui_values.get("FirstEntry", False)),
            "ShiftPoints": int(ui_values["ShiftPoints"]),
            "HedgePoints": int(ui_values["HedgePoints"]),
            "OTMPoints": int(ui_values["OTMPoints"]),
            "Symbol": ui_values["Symbol"],
            "ExpiryNo": int(ui_values["ExpiryNo"]),
            "OrderLot": int(ui_values["OrderLot"]),
            "StartTime": self._fmt_hms(StartTime),
            "EndTime": self._fmt_hms(EndTime),
            "updated_at": datetime.utcnow(),
        }

        result = self._upsert_strategy(client_id, doc)
        if result is None:
            st.error("Could not open the database for this client_id.")
            return

        st.success("Save Inputs.")

        # ✅ Also append to Google Sheet
        try:
            self._append_to_gsheet(client_id, doc)
        except Exception as e:
            st.warning(f"Error in Google Sheet: {e}")

        with st.expander("Saved Document", expanded=False):
            st.json(result)

    def _current_doc_section(self, client_id: str):
        if not client_id:
            return
        current = self._load_existing(client_id)
        if current:
            with st.expander("Current Document", expanded=False):
                st.json(current)
        else:
            st.warning("No document yet for this DB and StrategyID. Defaults shown; save to create one.")

    # ---------------- Orchestration ----------------
    def run(self):
        self._config_page()
        client_id, existing = self._client_input()
        key_suffix = (client_id or "no_client").replace(" ", "_")

        # Put controls + timing + save inside one form so intermediate widget changes don't immediately trigger 'save' logic
        with st.form(key=f"strategy_form_{key_suffix}"):
            ui_values = self._controls_section(existing, key_suffix)
            StartTime, EndTime = self._timing_section(existing, key_suffix)

            submit = st.form_submit_button("Save Inputs")
            if submit:
                # set a session flag so we can run save logic after the form (to avoid double render issues)
                st.session_state["_form_submitted"] = True

        # Run save logic (outside the form) which checks the submitted flag
        self._save_section(client_id, ui_values if 'ui_values' in locals() else {}, StartTime if 'StartTime' in locals() else self.DEFAULT_START, EndTime if 'EndTime' in locals() else self.DEFAULT_END)
        self._current_doc_section(client_id)


# ---------------- Main ----------------nif __name__ == "__main__":
    StraddleShiftInput().run()
