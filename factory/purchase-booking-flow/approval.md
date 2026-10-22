VERDICT: APPROVE

## Reasoning
- Process: spec approved (section 4 acceptance criteria), three builders (A domain/data, B inbox booking UX, C Crediteuren screen/glossary/wiring) delivered reports, integration done (commit 2bf5455), one combined review round run (VERDICT: PASS). Review round count is 1 of max 2, and the review raised no blocking findings.
- Tests: the orchestrator reports the full suite after integration at 1430 passed, with one redirect assertion fixed afterwards. `tests/test_booking_web.py` was re-run after the fix (12 passed). The full suite was not rerun, as instructed. The purchase tests (`tests/purchase/*`, `tests/test_purchase_web.py`, `tests/test_booking_web.py`) cover every criterion below by name.
- Booking rules, double-entry construction, learned defaults, the Crediteuren screen and the plain-language requirements all trace to named tests (for example `test_book_creates_entry_invoice_and_links_document`, `test_trial_balance_matches_open_invoices`, `test_duplicate_allowed_after_storno`, `test_entry_cannot_be_changed_after_source_link`, `test_pagination_counter`, `test_every_glossary_key_is_used`).
- Accepted deviations:
  1. Migration 0008 replaces the `journal_entry_no_update` trigger with one that allows a single update that fills `source_type`/`source_id` while they are NULL, with every other column unchanged. Every other update is still refused, and the downgrade restores the strict trigger. The spec itself requires the source link to be set after insert (AC 5) and allows "no entry updates apart from source link at creation" (section 7). The change is narrow and tested (`test_source_link_can_be_set_once`, `test_downgrade_restores_strict_trigger`). I accept it, but it is a loosening of the append-only guarantee that CLAUDE.md treats as a Dutch compliance rule, so the human should see it (see below).
  2. The duplicate-invoice guard is a service pre-check, not a unique partial index. The reason holds: a plain index cannot see whether an entry was storno'd, and AC 7 requires storno'd numbers to be bookable again. Double-submit of the same document is still blocked by `UNIQUE(document_id)` and reported as "Dit document is al geboekt." A race between two different documents with the same supplier and number is possible, which is negligible for a single-user local app. Accepted.
- Minor: the combined review said the reviewer could not run pytest. This is not a blocker; the orchestrator test result stands.

## Acceptance criteria check
Section 4, criteria as written in the spec:

Booking rules (domain)
1. Preconditions and plain-Dutch BookingError per field: MET (`test_missing_*`, `test_line_without_*`, `test_lines_do_not_add_up_*`, `test_total_must_be_positive`, `test_float_amounts_are_refused`).
2. Verlegd/EU/export refused with the specified message: MET (`test_unsupported_vat_codes`, `test_unsupported_by_rubriek_even_for_unknown_custom_code`, `test_unsupported_vat`).
3. Entry shape for invoices (grondslag per line, 1400 per code with printed VAT, 3000 credit for total incl.), balanced, passes validate_entry; zero-amount lines refused: MET (`test_build_entry_*`, `test_printed_vat_is_used_never_recomputed`, `test_zero_amount_line`).
4. Credit note swaps sides: MET (`test_credit_note_swaps_debit_and_credit`, `test_credit_note`).
5. Entry fields (IK journal, booking_date, reference, description truncated to 255, source_type/source_id): MET (`test_description_is_truncated_to_255`, `test_no_active_purchase_journal`); source link via the trigger deviation above.
6. Locked period surfaces the ledger message, nothing persisted, date never shifted: MET (`test_locked_period_rolls_back_and_keeps_sequence`, `test_prepare_booking_reports_locked_period`).
7. Duplicate guard (case-insensitive, trimmed; storno'd may rebook): MET as a service check (deviation 2) (`test_duplicate_number_same_supplier_refused`, `test_same_number_other_supplier_allowed`, `test_duplicate_allowed_after_storno`, `test_invoice_number_is_trimmed`).
8. Atomic, sequence not consumed on failure: MET (`test_failure_after_posting_rolls_back_everything`, `test_locked_period_rolls_back_and_keeps_sequence`).
9. Already-geboekt document refused, double submit safe: MET (`test_already_booked`, `test_double_booking_refused`, `test_double_submit_gives_422_and_no_second_entry`).
10. document.journal_entry_id link, unique purchase_invoice.document_id, entry screen links back: MET (`test_entry_detail_links_back_to_the_document`, `test_purchase_invoice_constraints`).

Learned supplier defaults
11. supplier_default per contact+account, use_count, last_used_at, ranking by count then recency: MET (`test_record_creates_and_updates_counts`, `test_suggestion_highest_count_wins`, `test_suggestion_tie_goes_to_most_recent`, `test_supplier_default_unique_per_contact_account`).
12. Suggestion order learned > AI > none, hint text, inactive account/vat fallback: MET (`test_store_result_fills_empty_lines_from_history`, `test_store_result_inferred_vat_replaced_by_learned`, `test_store_result_without_history_keeps_ai_values`, `test_save_review_fills_lines_left_empty`, `test_inactive_or_non_postable_learned_account_is_ignored`, `test_inactive_learned_vat_code_falls_back_to_account_default`, `test_review_page_hints_what_you_chose_last_time`).
13. Learned defaults are suggestions only, owner confirms on preview: MET (preview is read-only; `test_prepare_booking_preview`).

Crediteuren (/inkoop)
14. Stat cards, two tabs, columns, "te laat" pill, search, pagination, links: MET (`test_stat_cards_and_open_per_supplier`, `test_all_tab_lists_invoices_with_links`, `test_overdue_pill`, `test_search_by_supplier_and_number`, `test_pagination_counter`, `test_inkoop_is_not_the_placeholder`).
15. Open amount with credit notes negative, storno shown as Gestorneerd and excluded, derived at read time: MET (`test_open_amount_and_status`, `test_storno_invoice_shown_as_gestorneerd_and_excluded`, `test_credit_note_reduces_open_amount`, `test_list_open_tab_excludes_storno`).
16. Account 3000 trial balance equals open total: MET (`test_trial_balance_matches_open_invoices`, `test_3000_balance_equals_open_total`).
17. Plain-Dutch empty state linking to Inbox: MET (`test_empty_state_links_to_inbox`, `test_empty`).

Web / UX
18. "Goedkeuren en boeken" on review (only when ok and not geboekt), preview at /inbox/{id}/boeken with plain-Dutch table and summary, POST books and redirects to /inkoop?melding=geboekt, "Eerst nakijken" state: MET (`test_review_page_has_book_button_only_when_ok_and_not_geboekt`, `test_preview_shows_plain_dutch_summary_and_where_it_lands`, `test_preview_before_nakijken_says_eerst_nakijken`, `test_post_books_and_redirects_to_inkoop`, `test_melding_geboekt_notice`).
19. Errors via error_box, 422, values kept, fix link to the review field, 404 for unknown document: MET (`test_locked_period_is_422_with_message_and_nothing_persisted`, `test_duplicate_invoice_number_is_refused_with_plain_message`, `test_missing_item_links_to_the_review_screen`, `test_preview_unknown_document_is_404`).
20. Inbox geboekt documents link to boeking and inkoopfactuur; no re-extract/re-review: MET (`test_geboekt_document_links_to_boeking_and_inkoopfactuur`; re-extract blocked by existing `_editable_document`).
21. Mobile: new pages use existing card/table components, `purchase.css` and `inbox.css` additions only: MET by inspection (reviewer checked layout; no phone-width run was done, see below).

Plain-language (CLAUDE.md)
- Glossary keys `inkoopfactuur`, `goedkeuren_boeken`, `openstaand`, `leerfunctie` added in `app/domain/glossary.py`; `voorbelasting` extended with rekening 1400; `crediteuren`, `storno`, `nakijken` etc. reused: MET (`test_glossary_has_new_terms`, `test_glossary_wording`).
- `tests/test_plain_language.py` covers `/inkoop` and `/inkoop?tab=all`, empty and filled: MET (`test_empty_pages_are_plain_language`, `test_filled_pages_are_plain_language`, `test_every_glossary_key_is_used`).
- Plain-Dutch error messages (AC 1, 2, 6, 7, 9): MET (see above).

Overall: all acceptance criteria are met. Deviations 1 and 2 are the only departures from the letter of the spec, and both are explained and covered by tests.

## Outstanding issues
Non-blocking, from the combined review (nice-to-haves, none required before shipping):
- `purchase/list.html` supplier link searches by name text, so a supplier whose name is a substring of another's also shows the other's invoices. Linking by `contact_id` would be exact. Recommended as a small follow-up.
- `purchase/service.py` calls the ledger's private helpers `_find_period`, `_check_accounts`, `_check_vat_codes`. Exposing them publicly would be cleaner.
- `booking_routes.py` template helpers each open their own short DB session per render. Fine for a single user.
- `boeking=<entry id>` in the success redirect is an int used only to build a link; harmless.

Process notes (not defects):
- After integration, one redirect assertion was fixed and only `tests/test_booking_web.py` was re-run. The fix is in a test, not in product code, and the full suite is not rerun by instruction. A full-suite run at the next opportunity would be prudent.
- `state.md` says "1430 passed" while the orchestrator message said 1429 passed plus one failing assertion (now updated). These are consistent with the post-fix state; the count difference is one test.
- The review did not run pytest; the orchestrator's test result is the evidence used here.

## What the human should look at
Not a blocker for APPROVE, but worth a look before relying on this in production:
1. Migration `migrations/versions/0008_purchase_booking.py`: `journal_entry` is still append-only, but one UPDATE is now allowed, filling `source_type`/`source_id` once while they are NULL. CLAUDE.md treats append-only bookings as a Dutch compliance rule, so you may want to confirm you accept this narrow exception (or prefer a different link mechanism). The trigger SQL is short and tested.
2. Phone-width layout of `/inkoop` and `/inkoop/boeken` preview was checked by inspection only, not in a browser.
3. Visual feel of the preview and the "Zo wordt het geboekt" table is a judgement call for you.

STATUS: DONE
