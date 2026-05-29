import re
import requests
import pandas as pd
import streamlit as st
from io import BytesIO
from bs4 import BeautifulSoup
import pdfplumber

st.set_page_config(
    page_title="Ireland Visa Decision Checker – Ankara",
    page_icon="🇮🇪",
    layout="centered",
)

BASE_URL = "https://www.ireland.ie/en/turkiye/ankara/services/visas/weekly-decision-report/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    )
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize_app_number(value: str) -> str:
    return value.strip().upper().removeprefix("IRL")


def validate_input(raw: str) -> tuple[bool, str, str]:
    raw = raw.strip()
    if not raw:
        return False, "", ""

    upper = raw.upper()

    if not re.match(r'^[A-Za-z0-9]+$', raw):
        return False, "❌ No spaces or special characters allowed. Use format: `IRL12345678` or `12345678`", ""

    if upper.startswith("IRL"):
        numeric_part = raw[3:]
        if not numeric_part.isdigit():
            return False, "❌ After `IRL` only digits are allowed. Example: `IRL79001082`", ""
    else:
        if not raw.isdigit():
            letters_found = "".join(sorted(set(c for c in upper if c.isalpha())))
            if upper[-1].isalpha():
                return False, f"❌ Letters must come at the **start** as `IRL` prefix only. Found `{letters_found}` at end.", ""
            return False, f"❌ Only the prefix `IRL` is allowed. Found unexpected letters: `{letters_found}`. Use `IRL12345678` or `12345678`", ""
        numeric_part = raw

    if len(numeric_part) < 8:
        return False, f"❌ Too short ({len(numeric_part)} digits). Must be exactly **8 digits**. Example: `IRL79001082`", ""
    if len(numeric_part) > 8:
        return False, f"❌ Too long ({len(numeric_part)} digits). Must be exactly **8 digits**. Example: `IRL79001082`", ""

    return True, "", numeric_part


def parse_pdf(content: bytes) -> pd.DataFrame:
    """Parse PDF — tries text extraction first, falls back to OCR for scanned/image PDFs."""
    rows = []

    # ── Attempt 1: pdfplumber table extraction (text-based PDFs) ──────────────
    with pdfplumber.open(BytesIO(content)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    if not row or len(row) < 2:
                        continue
                    app_num = str(row[0]).strip() if row[0] else ""
                    decision = str(row[1]).strip() if row[1] else ""
                    if app_num.lower() in ("application number", "", "none"):
                        continue
                    if decision.lower() in ("decision", "", "none"):
                        continue
                    rows.append({"Application Number": app_num, "Decision": decision})

    if rows:
        return pd.DataFrame(rows)

    # ── Attempt 2: OCR fallback for image/scanned PDFs ────────────────────────
    try:
        import fitz
        import pytesseract
        from PIL import Image
        import io as _io
        import re
        import subprocess

        # Auto-detect tesseract path
        for candidate in ["/usr/bin/tesseract", "/usr/local/bin/tesseract"]:
            try:
                subprocess.run([candidate, "--version"], capture_output=True, timeout=5)
                pytesseract.pytesseract.tesseract_cmd = candidate
                break
            except Exception:
                continue

        doc = fitz.open(stream=content, filetype="pdf")
        for page in doc:
            mat = fitz.Matrix(2.5, 2.5)
            pix = page.get_pixmap(matrix=mat)
            img = Image.open(_io.BytesIO(pix.tobytes("png")))
            text = pytesseract.image_to_string(img, lang="eng", config="--psm 6")
            for line in text.splitlines():
                line = line.strip()
                m = re.match(r'^(\d{7,9})\s+(Approved|Refused|Granted|Rejected)', line, re.IGNORECASE)
                if m:
                    rows.append({
                        "Application Number": m.group(1),
                        "Decision": m.group(2).capitalize()
                    })
    except Exception:
        pass

    return pd.DataFrame(rows)


def df_to_html_table_nearest(dataframe):
    rows = ""
    for _, row in dataframe.iterrows():
        decision_val = str(row["Decision"])
        if "approv" in decision_val.lower():
            badge = f'<span style="color:#1e7e34;font-weight:600">{decision_val}</span>'
        elif "refus" in decision_val.lower():
            badge = f'<span style="color:#c0392b;font-weight:600">{decision_val}</span>'
        else:
            badge = decision_val
        rows += (
            f"<tr>"
            f"<td style='padding:6px'>{row['Nearest Application']}</td>"
            f"<td style='padding:6px;text-align:right'>{row['Application Number']}</td>"
            f"<td style='padding:6px'>{badge}</td>"
            f"<td style='padding:6px;text-align:right'>{row['Difference']}</td>"
            f"</tr>"
        )
    return (
        "<table style='width:100%;border-collapse:collapse;font-size:14px'>"
        "<thead><tr style='border-bottom:2px solid #ddd'>"
        "<th style='text-align:left;padding:6px'>Nearest Application</th>"
        "<th style='text-align:right;padding:6px'>Application Number</th>"
        "<th style='text-align:left;padding:6px'>Decision</th>"
        "<th style='text-align:right;padding:6px'>Difference</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def df_to_html_table(dataframe):
    rows = ""
    for _, row in dataframe.iterrows():
        decision_val = str(row["Decision"])
        if "approv" in decision_val.lower():
            badge = f'<span style="color:#1e7e34;font-weight:600">{decision_val}</span>'
        elif "refus" in decision_val.lower():
            badge = f'<span style="color:#c0392b;font-weight:600">{decision_val}</span>'
        else:
            badge = decision_val
        rows += f"<tr><td style='padding:6px'>{row['Application Number']}</td><td style='padding:6px'>{badge}</td></tr>"
    return (
        "<table style='width:100%;border-collapse:collapse;font-size:14px'>"
        "<thead><tr style='border-bottom:2px solid #ddd'>"
        "<th style='text-align:left;padding:6px'>Application Number</th>"
        "<th style='text-align:left;padding:6px'>Decision</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


@st.cache_data(ttl=3600)
def fetch_data() -> tuple[pd.DataFrame | None, list[str] | None]:
    try:
        response = requests.get(BASE_URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        return None, [str(e)]

    soup = BeautifulSoup(response.content, "html.parser")
    pdf_links = []
    for link in soup.find_all("a"):
        href = link.get("href", "")
        text = link.get_text(strip=True)
        if href.endswith(".pdf") and "Ankara" in text:
            full_url = href if href.startswith("http") else requests.compat.urljoin(BASE_URL, href)
            pdf_links.append({"label": text, "url": full_url})

    if not pdf_links:
        return None, ["No PDF decision reports found on the page."]

    # Try each PDF in order — skip image-based (scanned) PDFs that return no data
    all_frames = []
    period_labels = []
    for item in pdf_links:
        try:
            r = requests.get(item["url"], headers=HEADERS, timeout=60)
            r.raise_for_status()
            df_part = parse_pdf(r.content)
            if not df_part.empty:
                all_frames.append(df_part)
                period_labels.append(item["label"])
                break  # Use the first PDF that has parseable data
        except Exception:
            continue

    if not all_frames:
        return None, ["Could not parse any PDF files. The embassy may have published a scanned/image PDF this week. Please try again later."]

    df = pd.concat(all_frames, ignore_index=True)
    df.drop_duplicates(subset=["Application Number"], keep="last", inplace=True)
    df.reset_index(drop=True, inplace=True)

    return df, period_labels


# ── UI ────────────────────────────────────────────────────────────────────────

st.title("🇮🇪 Ireland Visa Decision Checker")
st.caption("Ankara Embassy · Data sourced from ireland.ie")

# ── How to use ────────────────────────────────────────────────────────────────
with st.expander("ℹ️ How to use this tool"):
    st.markdown("""
    1. Enter your 8-digit application number like `83276171` or with prefix `IRL83276171`
    2. Get instant status check.
    3. See nearest processed numbers if yours isn't found.
    4. Please share with your family and friends this application.
    5. More than 4130+ people have used this application as of April 2026. Last week usage 200 people.
    6. Contact the developer if any issues while using this application.
    7. #irelandvisaresult #ireland #AIforgood #studentinireland #irelandeducation #NCIcollege #NCI
    """)

with st.spinner("Loading latest visa decisions…"):
    df, meta = fetch_data()

if df is None:
    st.error(f"Could not load data: {meta}")
    st.stop()

with st.expander("📋 Weekly reports loaded"):
    for label in meta:
        st.write(f"• {label}")

# ── Stats ─────────────────────────────────────────────────────────────────────
total = len(df)
decision_counts = df["Decision"].value_counts()

col1, col2, col3 = st.columns(3)
col1.metric("Total Decisions", total)
col2.metric("Approved", int(decision_counts.get("Approved", 0)))
col3.metric("Refused", int(decision_counts.get("Refused", 0)))

st.divider()

# ── Search ────────────────────────────────────────────────────────────────────
st.subheader("Check your application")
st.caption("Valid formats: `79001082` · `IRL79001082` · `irl79001082` — exactly 8 digits, optional IRL prefix")

query = st.text_input(
    "Enter your Application Number",
    placeholder="e.g. IRL79001082 or 79001082",
    max_chars=11,
).strip()

if query:
    is_valid, error_msg, normalized_query = validate_input(query)

    if not is_valid:
        st.error(error_msg)
    else:
        df_normalized = df["Application Number"].apply(normalize_app_number)
        result = df[df_normalized == normalized_query]

        if result.empty:
            st.warning(f"No record found for Application Number: {normalized_query}.")

            try:
                query_int = int(normalized_query)
                nums = df["Application Number"].apply(
                    lambda x: int(normalize_app_number(x)) if normalize_app_number(x).isdigit() else None
                ).dropna().astype(int)

                below = nums[nums < query_int]
                above = nums[nums > query_int]

                nearest_rows = []
                if not below.empty:
                    closest_below_num = below.max()
                    closest_below = df[nums == closest_below_num].iloc[0]
                    nearest_rows.append({
                        "Nearest Application": "Before",
                        "Application Number": str(closest_below["Application Number"]),
                        "Decision": closest_below["Decision"],
                        "Difference": query_int - closest_below_num,
                    })
                if not above.empty:
                    closest_above_num = above.min()
                    closest_above = df[nums == closest_above_num].iloc[0]
                    nearest_rows.append({
                        "Nearest Application": "After",
                        "Application Number": str(closest_above["Application Number"]),
                        "Decision": closest_above["Decision"],
                        "Difference": closest_above_num - query_int,
                    })

                if nearest_rows:
                    st.subheader("Nearest Application Numbers")
                    nearest_df = pd.DataFrame(nearest_rows)
                    st.markdown(df_to_html_table_nearest(nearest_df), unsafe_allow_html=True)
            except ValueError:
                pass
        else:
            decision = result.iloc[0]["Decision"]
            app_num = result.iloc[0]["Application Number"]
            if "approv" in decision.lower():
                st.success(f"**Application {app_num} — Decision: {decision}** ✅")
            elif "refus" in decision.lower():
                st.error(f"**Application {app_num} — Decision: {decision}** ❌")
            else:
                st.info(f"**Application {app_num} — Decision: {decision}**")

st.divider()

# ── Download ──────────────────────────────────────────────────────────────────
csv = df.to_csv(index=False).encode("utf-8")
st.download_button(
    label="⬇️ Download full dataset (CSV)",
    data=csv,
    file_name="ankara_visa_decisions.csv",
    mime="text/csv",
)

# with st.expander("Browse first 100 decisions"):
#     st.markdown(df_to_html_table(df.head(100)), unsafe_allow_html=True)

# ── Error fallback ────────────────────────────────────────────────────────────
with st.expander("⚠️ If any error click on me"):
    st.markdown(f"""
    1. Visit the [original website]({BASE_URL}) and download the file.
    2. Mostly the error is due to the file not being available on the server.
       Once the embassy website has the file, this application will work.
    """)

st.caption(
    "Data refreshes every hour. "
    f"[Source]({BASE_URL})"
)
