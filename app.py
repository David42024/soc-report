"""Streamlit entrypoint. Operational behavior remains in the existing SOC API."""
import streamlit as st

from src.utils.errors import AnalyticsError
from src.utils.streamlit_runtime import get_runtime, render_account

try:
    runtime = get_runtime()
except AnalyticsError as error:
    st.error(str(error))
    st.stop()

st.set_page_config(page_title=runtime.settings.ui.title, page_icon="🛡️", layout="wide")
render_account(runtime)
navigation = st.navigation([
    st.Page(str(runtime.settings.path(page.path)), title=page.title, default=index == 0)
    for index, page in enumerate(runtime.settings.ui.pages)
])
navigation.run()
