# Agent Tests Suite Map

Top-level `test_*.py` files: **315**.

Subdirs: `factors/`, `fixtures/`, `memory/`.

## By domain prefix

| prefix | count | examples |
|--------|------:|----------|
| `swarm` | 22 | `test_swarm_dag_gating.py`, `test_swarm_error_surfacing.py`, `test_swarm_grounding.py`, …(+19) |
| `cli` | 16 | `test_cli_channels.py`, `test_cli_connector_renderers.py`, `test_cli_continue.py`, …(+13) |
| `agent` | 11 | `test_agent_config.py`, `test_agent_goal_context.py`, `test_agent_guide_paths.py`, …(+8) |
| `mcp` | 11 | `test_mcp_client_adapter.py`, `test_mcp_factor_analysis_contract.py`, `test_mcp_host_origin_guard.py`, …(+8) |
| `runtime` | 7 | `test_runtime_flatten.py`, `test_runtime_jobstore.py`, `test_runtime_liveness.py`, …(+4) |
| `alpha` | 6 | `test_alpha_bench_cache.py`, `test_alpha_bench_forward_returns.py`, `test_alpha_bench_strict_cli.py`, …(+3) |
| `session` | 6 | `test_session_events.py`, `test_session_search.py`, `test_session_service_mcp.py`, …(+3) |
| `options` | 5 | `test_options_bs_nonpositive_strike.py`, `test_options_chain_tool.py`, `test_options_partial_close.py`, …(+2) |
| `ccxt` | 4 | `test_ccxt_interval_map.py`, `test_ccxt_loader_bounded.py`, `test_ccxt_loader_proxy.py`, …(+1) |
| `doc` | 4 | `test_doc_reader.py`, `test_doc_reader_inverted_pages.py`, `test_doc_reader_security.py`, …(+1) |
| `india` | 4 | `test_india_backtest_smoke.py`, `test_india_broker_loader.py`, `test_india_equity_engine.py`, …(+1) |
| `longbridge` | 4 | `test_longbridge_credentials.py`, `test_longbridge_loader.py`, `test_longbridge_period_hour_case.py`, …(+1) |
| `mandate` | 4 | `test_mandate_commit_security.py`, `test_mandate_enforcement.py`, `test_mandate_forex.py`, …(+1) |
| `market` | 4 | `test_market_data.py`, `test_market_data_tool.py`, `test_market_detection.py`, …(+1) |
| `channel` | 3 | `test_channel_media_roots.py`, `test_channels_api.py`, `test_channels_runtime.py` |
| `eastmoney` | 3 | `test_eastmoney_client.py`, `test_eastmoney_float_dates.py`, `test_eastmoney_loader.py` |
| `get` | 3 | `test_get_fundamentals_tool.py`, `test_get_market_data_size.py`, `test_get_market_data_unresolved.py` |
| `goal` | 3 | `test_goal_api.py`, `test_goal_store.py`, `test_goal_tools.py` |
| `mt5` | 3 | `test_mt5_connector.py`, `test_mt5_interval_lowercase.py`, `test_mt5_loader.py` |
| `qveris` | 3 | `test_qveris_loader.py`, `test_qveris_routes.py`, `test_qveris_tool.py` |
| `run` | 3 | `test_run_card.py`, `test_run_card_content_filter.py`, `test_run_card_strict_json.py` |
| `scheduled` | 3 | `test_scheduled_research_executor.py`, `test_scheduled_research_store.py`, `test_scheduled_routes.py` |
| `shadow` | 3 | `test_shadow_account.py`, `test_shadow_codegen_security.py`, `test_shadow_scanner.py` |
| `tushare` | 3 | `test_tushare_fallbacks.py`, `test_tushare_fundamentals_provider.py`, `test_tushare_loader.py` |
| `web` | 3 | `test_web_reader_privacy.py`, `test_web_reader_security.py`, `test_web_search_tool.py` |
| `akshare` | 2 | `test_akshare_interval_reject.py`, `test_akshare_loader.py` |
| `alpaca` | 2 | `test_alpaca_tap_routing.py`, `test_alpaca_timeframe_map.py` |
| `api` | 2 | `test_api_infrastructure.py`, `test_api_live_runtime.py` |
| `autopilot` | 2 | `test_autopilot_phase3.py`, `test_autopilot_tool.py` |
| `china` | 2 | `test_china_a_engine.py`, `test_china_futures_engine.py` |
| `content` | 2 | `test_content_filter_e2e.py`, `test_content_filter_gemini_detection.py` |
| `engine` | 2 | `test_engine_metrics_json.py`, `test_engine_robustness.py` |
| `factor` | 2 | `test_factor_gate_fund_prefix.py`, `test_factor_operators.py` |
| `financial` | 2 | `test_financial_rigor_tool.py`, `test_financial_statements_tool.py` |
| `fundamental` | 2 | `test_fundamental_filter_example.py`, `test_fundamental_schema.py` |
| `futu` | 2 | `test_futu_excel_serial_dates.py`, `test_futu_loader.py` |
| `global` | 2 | `test_global_equity_engine.py`, `test_global_futures_engine.py` |
| `ibkr` | 2 | `test_ibkr_local.py`, `test_ibkr_mcp_seed.py` |
| `llm` | 2 | `test_llm.py`, `test_llm_provider_defaults.py` |
| `local` | 2 | `test_local_loader.py`, `test_local_source_routing.py` |
| `memory` | 2 | `test_memory_gc.py`, `test_memory_lifecycle.py` |
| `ocr` | 2 | `test_ocr_engine.py`, `test_ocr_integration.py` |
| `okx` | 2 | `test_okx_bar_map.py`, `test_okx_loader_bounded.py` |
| `redaction` | 2 | `test_redaction.py`, `test_redaction_shared.py` |
| `registry` | 2 | `test_registry.py`, `test_registry_mcp_integration.py` |
| `remember` | 2 | `test_remember_tool.py`, `test_remember_tool_security.py` |
| `risk` | 2 | `test_risk_parity.py`, `test_risk_xray.py` |
| `rsshub` | 2 | `test_rsshub_events_lookahead.py`, `test_rsshub_events_provider.py` |
| `sdk` | 2 | `test_sdk_connectors.py`, `test_sdk_order_gate.py` |
| `sec` | 2 | `test_sec_edgar_client.py`, `test_sec_filings_tool.py` |
| `security` | 2 | `test_security_auth_api.py`, `test_security_scanner.py` |
| `skill` | 2 | `test_skill_reference_links.py`, `test_skill_writer_tools.py` |
| `stock` | 2 | `test_stock_news_tool.py`, `test_stock_profile_tool.py` |
| `tool` | 2 | `test_tool_registry_security.py`, `test_tool_timeout.py` |
| `trading` | 2 | `test_trading212_connector.py`, `test_trading_connections.py` |
| `upload` | 2 | `test_upload_api.py`, `test_upload_security.py` |
| `validation` | 2 | `test_validation.py`, `test_validation_cli.py` |
| `yahoo` | 2 | `test_yahoo_client.py`, `test_yahoo_loader.py` |
| `yfinance` | 2 | `test_yfinance_crypto.py`, `test_yfinance_interval_map.py` |
| `advisory` | 1 | `test_advisory.py` |
| `audit` | 1 | `test_audit_redact.py` |
| `auth` | 1 | `test_auth_precedence.py` |
| `background` | 1 | `test_background_tools.py` |
| `backtest` | 1 | `test_backtest_runner_security.py` |
| `baostock` | 1 | `test_baostock_loader.py` |
| `base` | 1 | `test_base_engine.py` |
| `bench` | 1 | `test_bench_parallel.py` |
| `binance` | 1 | `test_binance_fallback.py` |
| `block` | 1 | `test_block_trades_tool.py` |
| `chat` | 1 | `test_chat_llm_streaming.py` |
| `classification` | 1 | `test_classification.py` |
| `composite` | 1 | `test_composite_engine_fallback.py` |
| `consent` | 1 | `test_consent_commit.py` |
| `context` | 1 | `test_context_attribution_layers.py` |
| `correlation` | 1 | `test_correlation.py` |
| `crypto` | 1 | `test_crypto_engine.py` |
| `daily` | 1 | `test_daily_count.py` |
| `data` | 1 | `test_data_routing_sources_subset.py` |
| `default` | 1 | `test_default_deny_unknown_robinhood_tool.py` |
| `distribution` | 1 | `test_distribution_skill_manifest.py` |
| `dividend` | 1 | `test_dividend_analysis_skill.py` |
| `dotenv` | 1 | `test_dotenv_observability.py` |
| `dragon` | 1 | `test_dragon_tiger_tool.py` |
| `enforcement` | 1 | `test_enforcement_l6.py` |
| `env` | 1 | `test_env_schema.py` |
| `equity` | 1 | `test_equity_regression.py` |
| `error` | 1 | `test_error_path_redaction.py` |
| `execution` | 1 | `test_execution_causality.py` |
| `feishu` | 1 | `test_feishu_parse_md_table_edge_columns.py` |
| `fetch` | 1 | `test_fetch_sina_penalties.py` |
| `file` | 1 | `test_file_tool_sandbox_security.py` |
| `finnhub` | 1 | `test_finnhub_loader.py` |
| `fmp` | 1 | `test_fmp_loader.py` |
| `forex` | 1 | `test_forex_engine.py` |
| `fred` | 1 | `test_fred_macro_tool.py` |
| `fund` | 1 | `test_fund_flow_tool.py` |
| `fundamentals` | 1 | `test_fundamentals_pit.py` |
| `halt` | 1 | `test_halt.py` |
| `hypothesis` | 1 | `test_hypothesis_registry.py` |
| `image` | 1 | `test_image_vision_tool.py` |
| `indicator` | 1 | `test_indicator_period_nonpositive.py` |
| `iwencai` | 1 | `test_iwencai_tool.py` |
| `journal` | 1 | `test_journal_inverted_date_filter.py` |
| `killswitch` | 1 | `test_killswitch_blocks_orders.py` |
| `kimi` | 1 | `test_kimi_reasoning_content.py` |
| `load` | 1 | `test_load_equity_aliases.py` |
| `loader` | 1 | `test_loader_retry_helpers.py` |
| `lockup` | 1 | `test_lockup_expiry_tool.py` |
| `loop` | 1 | `test_loop_helpers.py` |
| `margin` | 1 | `test_margin_trading_tool.py` |
| `metrics` | 1 | `test_metrics.py` |
| `models` | 1 | `test_models.py` |
| `mootdx` | 1 | `test_mootdx_loader.py` |
| `no` | 1 | `test_no_set_mandate_tool.py` |
| `northbound` | 1 | `test_northbound_tool.py` |
| `oauth` | 1 | `test_oauth_token_cache.py` |
| `ohlc` | 1 | `test_ohlc_validation.py` |
| `openai` | 1 | `test_openai_codex.py` |
| `optimizer` | 1 | `test_optimizer_causality.py` |
| `packaging` | 1 | `test_packaging_dependencies.py` |
| `parse` | 1 | `test_parse_period_inverted.py` |
| `path` | 1 | `test_path_safety.py` |
| `pattern` | 1 | `test_pattern_tool.py` |
| `persistent` | 1 | `test_persistent_memory.py` |
| `preflight` | 1 | `test_preflight.py` |
| `progress` | 1 | `test_progress.py` |
| `provider` | 1 | `test_provider_diagnostics.py` |
| `readonly` | 1 | `test_readonly_default.py` |
| `realized` | 1 | `test_realized_turnover.py` |
| `reasoning` | 1 | `test_reasoning_delta_throttle.py` |
| `rebalance` | 1 | `test_rebalance_notes.py` |
| `regime` | 1 | `test_regime.py` |
| `report` | 1 | `test_report_audit_tool.py` |
| `research` | 1 | `test_research_reports_tool.py` |
| `runner` | 1 | `test_runner_env.py` |
| `sector` | 1 | `test_sector_tool.py` |
| `serve` | 1 | `test_serve_bind.py` |
| `settings` | 1 | `test_settings_api.py` |
| `shareholder` | 1 | `test_shareholder_count_tool.py` |
| `shoonya` | 1 | `test_shoonya_interval_map.py` |
| `signal` | 1 | `test_signal_alignment_perf.py` |
| `sina` | 1 | `test_sina_loader.py` |
| `skills` | 1 | `test_skills.py` |
| `spa` | 1 | `test_spa_deep_link.py` |
| `special` | 1 | `test_special_token_neutralization.py` |
| `split` | 1 | `test_split_message_nonpositive.py` |
| `sse` | 1 | `test_sse_ticket_and_headers.py` |
| `state` | 1 | `test_state_fsync.py` |
| `stooq` | 1 | `test_stooq_loader.py` |
| `strategy` | 1 | `test_strategy_store.py` |
| `symbol` | 1 | `test_symbol_search_tool.py` |
| `system` | 1 | `test_system_routes.py` |
| `tap` | 1 | `test_tap_forward.py` |
| `telegram` | 1 | `test_telegram_split_fence_hang.py` |
| `tencent` | 1 | `test_tencent_loader.py` |
| `terminal` | 1 | `test_terminal_close_accounting.py` |
| `ths` | 1 | `test_ths_excel_serial_dates.py` |
| `tiger` | 1 | `test_tiger_period_hour_case.py` |
| `tiingo` | 1 | `test_tiingo_loader.py` |
| `trace` | 1 | `test_trace_writer.py` |
| `trade` | 1 | `test_trade_journal.py` |
| `turnover` | 1 | `test_turnover_aware_optimizer.py` |
| `ui` | 1 | `test_ui_services.py` |
| `url` | 1 | `test_url_target_security.py` |
| `vnpy` | 1 | `test_vnpy_export.py` |

## Notable areas (coverage intent)

- **swarm_***: DAG, grounding, registry, trust model, worker, presets packaging
- **loader / tushare / yahoo / okx / futu**: data fetch contracts
- **runner / backtest / validation**: execution pipeline
- **live / mandate / sdk / trading**: order gate & connectors
- **session / goal / sse / api**: HTTP + EventBus
- **mcp / security / web**: tool surface & SSRF
- **shadow / factor / alpha**: research artifacts

## Subpackages

- `factors/` — 14 test modules
- `fixtures/` — 0 test modules
- `memory/` — 2 test modules