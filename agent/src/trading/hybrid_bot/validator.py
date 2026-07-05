# agent/src/trading/hybrid_bot/validator.py
import json
import logging
from src.providers.llm import build_llm
from src.tools.web_search_tool import WebSearchTool

logger = logging.getLogger(__name__)

def validate_signal_with_llm(symbol: str, signal_type: str, context_notes: str) -> dict:
    """
    Validates a trading signal using Gemini LLM by checking for news anomalies or negative catalysts.
    Returns:
        dict: {"decision": "APPROVE" | "REJECT", "reason": "explanation"}
    """
    coin_name = symbol.split("/")[0]
    
    # 1. Fetch recent news
    search_query = f"{coin_name} crypto news hack exploit delist dump"
    logger.info(f"Performing Google/DDG search: '{search_query}'")
    
    search_results_json = "{}"
    try:
        search_tool = WebSearchTool()
        if search_tool.check_available():
            search_results_json = search_tool.execute(query=search_query, max_results=5)
        else:
            logger.warning("WebSearchTool not available, proceeding without web search.")
    except Exception as e:
        logger.error(f"Failed to fetch web search results: {e}")
        
    # Parse search results
    search_snippet = ""
    try:
        search_data = json.loads(search_results_json)
        if search_data.get("status") == "ok":
            results = search_data.get("results", [])
            for r in results:
                search_snippet += f"- Title: {r.get('title')}\n  Snippet: {r.get('snippet')}\n  URL: {r.get('url')}\n\n"
        else:
            search_snippet = f"Search returned error: {search_data.get('error')}"
    except Exception as e:
        search_snippet = f"Error parsing search: {e}"
        
    if not search_snippet.strip():
        search_snippet = "No recent negative news found."

    # 2. Construct LLM prompt
    prompt = f"""
You are a senior risk manager at a crypto trading desk.
A quantitative indicator has triggered a trading signal:
Symbol: {symbol}
Signal Action: {signal_type}
Technical context: {context_notes}

Here are the latest news snippets for {coin_name} related to safety, hacks, or crashes:
---
{search_snippet}
---

Your Task:
Assess if there is a major negative catalyst (such as a smart contract hack, developer exploit, regulatory action, delisting announcement, or security breach) that makes executing this trade extremely risky.
For example, if the signal is LONG but the coin was just hacked 10 minutes ago, you must REJECT it.
If the signal is SHORT but there's a major positive partnership announced, you must REJECT it.
Otherwise, if there is no major counter-news, you should APPROVE the technical trade.

You MUST reply with a valid JSON block containing exactly two fields: "decision" (either "APPROVE" or "REJECT") and "reason" (a short, clear explanation of your decision).
Example output format:
{{
  "decision": "APPROVE",
  "reason": "No negative news detected. Technical setup is clear to execute."
}}

Do NOT output any markdown formatting, thoughts, or HTML tags. Output only the raw JSON.
"""

    # 3. Call LLM
    try:
        llm = build_llm()
        logger.info(f"Invoking LLM to validate {signal_type} for {symbol}...")
        response = llm.invoke(prompt)
        response_text = response.content if hasattr(response, "content") else str(response)
        
        # Clean any markdown wrap if generated
        clean_text = response_text.strip()
        if clean_text.startswith("```"):
            # strip ```json or ```
            lines = clean_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_text = "\n".join(lines).strip()
            
        decision_data = json.loads(clean_text)
        logger.info(f"LLM validation decision: {decision_data}")
        return decision_data
        
    except Exception as e:
        logger.error(f"LLM validation error: {e}. Failing closed (REJECT).")
        return {
            "decision": "REJECT",
            "reason": f"Validation process failed, rejecting as a safety default: {e}"
        }
