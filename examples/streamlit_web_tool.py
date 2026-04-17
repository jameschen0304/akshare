"""
浏览器里查询 A 股历史行情的极简示例（需先安装 streamlit）。

在项目根目录执行::

    pip install -e .
    pip install -r examples/requirements-web.txt
    streamlit run examples/streamlit_web_tool.py
"""

from __future__ import annotations

import traceback

import streamlit as st

import akshare as ak


def main() -> None:
    st.set_page_config(page_title="AKShare 网页小工具", layout="wide")
    st.title("AKShare：A 股历史行情")
    st.caption("数据来自东方财富等公开接口，仅供学习研究；不构成投资建议。")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        symbol = st.text_input("股票代码（6 位）", value="000001", max_chars=6)
    with col2:
        period = st.selectbox("周期", options=["daily", "weekly", "monthly"])
    with col3:
        adjust = st.selectbox("复权", options=["", "qfq", "hfq"], format_func=lambda x: {
            "": "不复权",
            "qfq": "前复权",
            "hfq": "后复权",
        }[x])
    with col4:
        start_date = st.text_input("开始日期", value="20240101", max_chars=8)
        end_date = st.text_input("结束日期", value="20500101", max_chars=8)

    if st.button("查询", type="primary"):
        sym = symbol.strip()
        if not sym.isdigit() or len(sym) != 6:
            st.error("请输入 6 位数字股票代码，例如 600519、000001。")
            return
        try:
            with st.spinner("正在拉取数据…"):
                df = ak.stock_zh_a_hist(
                    symbol=sym,
                    period=period,
                    start_date=start_date.strip(),
                    end_date=end_date.strip(),
                    adjust=adjust,
                )
        except Exception:
            st.error("请求失败，请稍后重试或检查网络。")
            st.code(traceback.format_exc())
            return
        if df is None or df.empty:
            st.warning("未返回数据：请检查代码是否为沪深京 A 股、日期区间是否合理。")
            return
        st.success(f"共 {len(df)} 条记录")
        st.dataframe(df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
