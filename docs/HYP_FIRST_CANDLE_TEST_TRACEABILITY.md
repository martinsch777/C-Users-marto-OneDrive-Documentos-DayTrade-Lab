# HYP-FCR-01 Test Traceability

Status: pre-discovery audit.

No discovery, validation, holdout, or historical profitability metrics were executed while creating this matrix.

| requirement_id | requisito | archivo | test_name | cobertura | estado |
| --- | --- | --- | --- | --- | --- |
| FCR-REQ-001 | Seis barras exactas del Opening Range | `tests/test_hyp_first_candle.py` | `test_opening_range_uses_exactly_six_bars` | Verifica seis barras 09:30-10:00 y high/low resultantes. | covered |
| FCR-REQ-002 | Alineacion 1m a 5m | `tests/test_hyp_first_candle.py` | `test_five_minute_alignment_from_one_minute_rth` | Verifica buckets 09:30 y 09:35 desde datos 1m RTH. | covered |
| FCR-REQ-003 | DST | `tests/test_hyp_first_candle.py` | `test_dst_alignment_uses_america_new_york` | Verifica cambio UTC entre enero y julio para 09:30 New York. | covered |
| FCR-REQ-004 | Feriados | `tests/test_hyp_first_candle.py` | `test_holidays_and_early_closes_are_calendar_driven` | Verifica que 2024-07-04 no sea sesion. | covered |
| FCR-REQ-005 | Early closes | `tests/test_hyp_first_candle.py` | `test_holidays_and_early_closes_are_calendar_driven`; `test_normal_and_early_close_forced_exit_no_overnight_research_primary`; `test_tradingview_parity_preserves_fixed_close_early_close_semantics` | Verifica calendario 13:00, cierre research_primary y preservacion del bug de Pine en parity. | covered |
| FCR-REQ-006 | Toque exacto del minimo | `tests/test_hyp_first_candle.py` | `test_exact_opening_low_and_high_touches_count` | Verifica que `low == opening_low` cuenta. | covered |
| FCR-REQ-007 | Toque exacto del maximo | `tests/test_hyp_first_candle.py` | `test_exact_opening_low_and_high_touches_count` | Verifica que `high == opening_high` cuenta. | covered |
| FCR-REQ-008 | Actualizacion al toque mas reciente | `tests/test_hyp_first_candle.py` | `test_most_recent_touch_updates_and_same_bar_confirmation_blocked` | Verifica que el ultimo toque reemplaza el anterior y deja `bars_since_last_sweep == 1`. | covered |
| FCR-REQ-009 | Confirmacion posterior al toque mas reciente | `tests/test_hyp_first_candle.py` | `test_most_recent_touch_updates_and_same_bar_confirmation_blocked` | Verifica que la senal aceptada ocurre despues del toque mas reciente. | covered |
| FCR-REQ-010 | Prohibicion de confirmar en la misma vela | `tests/test_hyp_first_candle.py` | `test_most_recent_touch_updates_and_same_bar_confirmation_blocked` | Fixture con toque/FVG en la misma vela no genera senal. | covered |
| FCR-REQ-011 | Bullish FVG | `tests/test_hyp_first_candle.py` | `test_bullish_bearish_and_zero_tick_fvg_rules` | Verifica `low[t] > high[t-2]`. | covered |
| FCR-REQ-012 | Bearish FVG | `tests/test_hyp_first_candle.py` | `test_bullish_bearish_and_zero_tick_fvg_rules` | Verifica `high[t] < low[t-2]`. | covered |
| FCR-REQ-013 | Gap de cero rechazado | `tests/test_hyp_first_candle.py` | `test_bullish_bearish_and_zero_tick_fvg_rules` | Verifica que igualdad exacta no cuenta aunque `minimum_fvg_ticks=0`. | covered |
| FCR-REQ-014 | Cierre exactamente en borde rechazado | `tests/test_hyp_first_candle.py` | `test_close_on_edge_rejected_and_strict_inside_accepted` | Verifica rechazo en opening_low y opening_high. | covered |
| FCR-REQ-015 | Cierre estrictamente dentro aceptado | `tests/test_hyp_first_candle.py` | `test_close_on_edge_rejected_and_strict_inside_accepted` | Verifica `opening_low < close < opening_high`. | covered |
| FCR-REQ-016 | Senales simultaneas producen no trade | `tests/test_hyp_first_candle.py` | `test_simultaneous_long_short_signal_records_conflict_without_trade` | Verifica no trade y diagnostico de conflicto. | covered |
| FCR-REQ-017 | Stop long por cuerpos | `tests/test_hyp_first_candle.py` | `test_stop_long_short_buffer_and_target_from_signal_close` | Verifica minimo de cuerpos de tres velas. | covered |
| FCR-REQ-018 | Stop short por cuerpos | `tests/test_hyp_first_candle.py` | `test_stop_long_short_buffer_and_target_from_signal_close` | Verifica maximo de cuerpos de tres velas. | covered |
| FCR-REQ-019 | Buffer de un tick | `tests/test_hyp_first_candle.py` | `test_stop_long_short_buffer_and_target_from_signal_close` | Verifica +/- 0.01 con tick baseline. | covered |
| FCR-REQ-020 | Target desde signal_close | `tests/test_hyp_first_candle.py` | `test_stop_long_short_buffer_and_target_from_signal_close` | Verifica target 2R long y short desde cierre de senal. | covered |
| FCR-REQ-021 | Position sizing por riesgo | `tests/test_hyp_first_candle.py` | `test_position_sizing_rounding_exposure_and_quantity_rejection` | Verifica riesgo 0.50% antes de la operacion. | covered |
| FCR-REQ-022 | Floor de cantidad | `tests/test_hyp_first_candle.py` | `test_position_sizing_rounding_exposure_and_quantity_rejection` | Verifica redondeo hacia abajo a acciones enteras. | covered |
| FCR-REQ-023 | Limite de exposicion | `tests/test_hyp_first_candle.py` | `test_position_sizing_rounding_exposure_and_quantity_rejection` | Verifica notional <= equity. | covered |
| FCR-REQ-024 | Rechazo quantity < 1 | `tests/test_hyp_first_candle.py` | `test_position_sizing_rounding_exposure_and_quantity_rejection` | Verifica `quantity_below_minimum`. | covered |
| FCR-REQ-025 | Maximo una operacion diaria | `tests/test_hyp_first_candle.py` | `test_one_trade_per_day_limit` | Verifica una senal por sesion y reinicio al dia siguiente. | covered |
| FCR-REQ-026 | Comision en ambos lados | `tests/test_hyp_first_candle.py` | `test_commission_and_adverse_slippage_long_and_short` | Verifica comision positiva sobre entrada y salida. | covered |
| FCR-REQ-027 | Slippage adverso long y short | `tests/test_hyp_first_candle.py` | `test_commission_and_adverse_slippage_long_and_short` | Verifica entrada long peor y entrada short peor por un tick. | covered |
| FCR-REQ-028 | TP y SL simultaneos: stop-first | `tests/test_hyp_first_candle.py` | `test_stop_first_when_target_and_stop_touch_same_minute` | Verifica `STOP_FIRST_AMBIGUOUS_BAR`. | covered |
| FCR-REQ-029 | Gap atravesando stop | `tests/test_hyp_first_candle.py` | `test_gap_through_stop_and_target_without_improvement` | Verifica `GAP_THROUGH_STOP`. | covered |
| FCR-REQ-030 | Gap atravesando target sin mejora | `tests/test_hyp_first_candle.py` | `test_gap_through_stop_and_target_without_improvement` | Verifica fill en target sin mejora de precio. | covered |
| FCR-REQ-031 | Cierre normal | `tests/test_hyp_first_candle.py` | `test_normal_and_early_close_forced_exit_no_overnight_research_primary` | Verifica cierre forzado en sesion normal. | covered |
| FCR-REQ-032 | Cierre en early close | `tests/test_hyp_first_candle.py` | `test_normal_and_early_close_forced_exit_no_overnight_research_primary` | Verifica salida 12:59 en sesion con cierre 13:00. | covered |
| FCR-REQ-033 | Prohibicion overnight | `tests/test_hyp_first_candle.py` | `test_normal_and_early_close_forced_exit_no_overnight_research_primary` | Verifica que no arrastra posicion al siguiente dia. | covered |
| FCR-REQ-034 | Respeto de manifests y exclusiones | `tests/test_hyp_first_candle.py` | `test_manifest_gate_and_excluded_sessions_are_respected`; `test_unapproved_manifest_is_rejected` | Verifica manifest aprobado, exclusiones y rechazo de manifest no aprobado. | covered |
| FCR-REQ-035 | Ausencia de look-ahead | `tests/test_hyp_first_candle.py` | `test_absence_of_lookahead_and_repeatability` | Compara senal con frame completo contra prefijo hasta la barra de senal. | covered |
| FCR-REQ-036 | Determinismo | `tests/test_hyp_first_candle.py` | `test_absence_of_lookahead_and_repeatability` | Verifica resultados identicos en ejecuciones repetidas. | covered |
| FCR-REQ-037 | Diferencia documentada entre parity y research_primary | `tests/test_hyp_first_candle.py`; `docs/FIRST_CANDLE_TRADINGVIEW_PARITY_SPEC.md` | `test_tradingview_parity_preserves_fixed_close_early_close_semantics`; `test_normal_and_early_close_forced_exit_no_overnight_research_primary` | Verifica que parity preserva la semantica fuente y research_primary corrige metodologicamente early close. | covered |
| FCR-RUN-001 | Comando por defecto prepare-only | `tests/test_hyp_first_candle.py` | `test_runner_default_is_prepare_only` | Verifica que el runner por defecto solo emite manifest de preparacion y flags de seguridad. | covered |
| FCR-RUN-002 | Discovery congelado a 2022-2024 | `tests/test_hyp_first_candle.py` | `test_period_guards_reject_2025_before_gate_and_2026_discovery`; `test_cli_date_override_validation_hash_mismatch_and_holdout_fail` | Verifica rechazo de 2026 y de cambios de fecha por CLI. | covered |
| FCR-RUN-003 | Validation bloqueada y hash-gated | `tests/test_hyp_first_candle.py` | `test_period_guards_reject_2025_before_gate_and_2026_discovery`; `test_cli_date_override_validation_hash_mismatch_and_holdout_fail` | Verifica bloqueo sin artefacto y rechazo con hash distinto. | covered |
| FCR-RUN-004 | 2026 solo parity/debug no decisional | `tests/test_hyp_first_candle.py` | `test_2026_requires_explicit_non_decisional_parity_debug` | Verifica que 2026 requiere ruta explicita no decisional. | covered |
| FCR-RUN-005 | Holdout no ejecutable | `tests/test_hyp_first_candle.py` | `test_cli_date_override_validation_hash_mismatch_and_holdout_fail` | Verifica que holdout no tiene implementacion ejecutable. | covered |
| FCR-PAR-001 | Buckets y clasificacion de paridad | `tests/test_hyp_first_candle.py` | `test_prepare_signal_frame_and_parity_comparison_tool`; `test_parity_comparison_buckets_and_difference_types`; `test_parity_comparison_cli_requires_both_csvs` | Verifica matched/missing/mismatch y tipo intrabar; CLI exige ambos CSVs. | covered |

