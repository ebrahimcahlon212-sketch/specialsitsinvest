from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
UI_DIR = PROJECT_DIR / "ui_dist"
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
APP_NAME = "InvestResearch"
DEV_URL = "http://127.0.0.1:5173"
MAX_SAVED_TEXT = 100_000
WEBVIEW2_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_BLOCK_CHARS = 4000
MAX_SEARCH_RESULTS = 50
CLEANER_VERSION = "2"
BACKUP_KEEP = 10
SEC_CONTACT_NAME = ""
SEC_CONTACT_EMAIL = ""
SEC_REQUEST_INTERVAL = 0.5
SEC_TIMEOUT = (10, 30)
SEC_ATTEMPTS = 3
SEC_MAX_IMPORT_BYTES = 50 * 1024 * 1024
SEC_MAX_DOCUMENTS = 100
CODEX_BINARY = Path.home() / 'AppData/Local/OpenAI/Codex/bin/247581e40ee272fb/codex.exe'
CODEX_VERSION = '0.155.0-alpha.9.2'
CODEX_SHA256 = 'bc45017e8239dc150258f69309ced9df6bbcdf5b8e4f346decf780ac0999e226'
MODEL_NAME = 'gpt-5.6-luna'
MODEL_EFFORT = 'low'
MODEL_DEADLINE_SECONDS = 60
MODEL_SETUP_SECONDS = 30
MODEL_CANCEL_SECONDS = 5
MODEL_MAX_PROTOCOL_BYTES = 2 * 1024 * 1024
CODEX_DISABLED_FEATURES = (
    'apps', 'plugins', 'remote_plugin', 'browser_use', 'browser_use_external',
    'computer_use', 'image_generation', 'shell_tool', 'unified_exec', 'code_mode',
    'code_mode_host', 'multi_agent', 'multi_agent_v2', 'hooks', 'skill_search',
    'skill_mcp_dependency_install', 'tool_suggest', 'goals', 'sleep_tool',
    'workspace_dependencies', 'in_app_browser', 'in_app_local_automation',
    'memories', 'unbounded_connection_retries', 'view_image',
)
SUMMARY_MAX_CHARS = 40_000
SUMMARY_MAX_NOTES_CHARS = 8_000
SUMMARY_MAX_OWNER_FACTS_CHARS = 40_000
FACT_RETRIEVAL_HITS = 3
FACT_RETRIEVAL_CHARS = 6000
FACT_FINANCIAL_RETRIEVAL_CHARS = 14000
FACT_TABLE_HEADER_CHARS = 2000
FACT_NEIGHBOUR_CHARS = 1000
FACT_BATCH_MAX_CHARS = 60_000
FACT_RETRIEVAL_VERSION = 'fts-context-3'
FACT_FINANCIAL_KEYS = ('shares_outstanding_after', 'debt_at_separation', 'cash_at_separation',
    'cash_payment_to_parent', 'pension_and_other_liabilities', 'pro_forma_revenue',
    'pro_forma_operating_income', 'pro_forma_ebitda', 'management_equity_awards')
FACT_KEYS = {
    'parent_name': 'Parent name', 'spinco_name': 'Spinco name',
    'distribution_ratio': 'Distribution ratio', 'record_date': 'Record date',
    'distribution_date': 'Distribution date', 'listing_exchange': 'Listing exchange',
    'expected_ticker': 'Expected ticker', 'when_issued_trading': 'When-issued trading',
    'shares_outstanding_after': 'Shares outstanding after distribution',
    'debt_at_separation': 'Debt at separation', 'cash_at_separation': 'Cash at separation',
    'cash_payment_to_parent': 'Cash payment to parent',
    'pension_and_other_liabilities': 'Pension and other liabilities',
    'pro_forma_revenue': 'Pro forma revenue', 'pro_forma_operating_income': 'Pro forma operating income',
    'pro_forma_ebitda': 'Pro forma EBITDA', 'conditions_to_distribution': 'Distribution conditions',
    'tax_free_condition': 'Tax-free condition', 'management_equity_awards': 'Management equity awards',
}
FACT_BATCHES = (
    ('parent_name','spinco_name','distribution_ratio','record_date','distribution_date',
     'listing_exchange','expected_ticker','when_issued_trading','shares_outstanding_after'),
    ('debt_at_separation','cash_at_separation','cash_payment_to_parent','pension_and_other_liabilities',
     'conditions_to_distribution','tax_free_condition','management_equity_awards'),
    ('pro_forma_revenue','pro_forma_operating_income','pro_forma_ebitda'),
)
FACT_QUERIES = {
    'parent_name': ('"parent"', '"separation from"'),
    'spinco_name': ('"Spinco"', '"corporation"'),
    'distribution_ratio': ('"for each share"', '"distribution ratio"'),
    'record_date': ('"record date"',), 'distribution_date': ('"distribution date"',),
    'listing_exchange': ('"list our common stock"', '"stock exchange"'),
    'expected_ticker': ('"symbol"', '"ticker"'),
    'when_issued_trading': ('"when issued"',),
    'shares_outstanding_after': ('"shares outstanding"', '"shares of our common stock outstanding"'),
    'debt_at_separation': ('"pro forma" AND "debt"', '"indebtedness" AND "distribution"'),
    'cash_at_separation': ('"pro forma" AND "cash"', '"cash and cash equivalents"'),
    'cash_payment_to_parent': ('"cash payment"', '"distribution" AND "billion"'),
    'pension_and_other_liabilities': ('"net unfunded status"', '"pension" AND "liabilities"',
                                    '"pro forma" AND "liabilities"'),
    'pro_forma_revenue': ('"pro forma" AND "statement of operations"', '"pro forma" AND "revenue"'),
    'pro_forma_operating_income': ('"pro forma" AND "statement of operations"', '"pro forma" AND "operating"'),
    'pro_forma_ebitda': ('"pro forma" AND "EBITDA"', '"EBITDA"'),
    'conditions_to_distribution': ('"conditions to the distribution"', '"conditions" AND "satisfied"'),
    'tax_free_condition': ('"tax opinion" AND "will have received"',
                           '"tax opinion" AND "condition" AND "counsel"'),
    'management_equity_awards': ('"vice president" AND "converted"',),
}
