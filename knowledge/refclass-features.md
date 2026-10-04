# Reference class features, version 1

Fixed on 4 October 2026. Two models tag each event independently from its source documents and cite the line for every tag. Phase 1 needs event_type, first_product, market_value_band and same_day_news.

| Feature | Values | Rule |
| --- | --- | --- |
| event_type | approval, crl, refusal_to_file, extension, resubmission_accepted | From the FDA letter or the company's announcement |
| first_product | yes, no | Yes if the company had no other product on the US market at the event date, including licensed-in products |
| market_value_band | under_500m, 500m_to_1bn, 1bn_to_3bn, over_3bn | Pre-news close multiplied by common shares from the latest filing before the event |
| same_day_news | yes, no | A takeover or financing announced the same day |
| modality | small_molecule, biologic, gene_therapy, cell_therapy, other | From the application type and the product description |
| orphan | yes, no | Yes if the FDA orphan database shows designation for the indication before the event date |
| breakthrough | yes, no | Yes if breakthrough designation for the indication was granted before the event date |
| priority_review | yes, no | From the acceptance announcement or Drugs@FDA |
| prior_crl_type | none, manufacturing, clinical, both, unknown | From earlier CRLs for the same application |
| prior_refusal_to_file | yes, no | Any refusal to file for the same product before the event |
| major_amendment_extension | yes, no | A three-month extension in the review cycle that ended in the event |
| adcomm | none, positive, negative, split | Majority vote on the main question, with split for a tie |
| contract_manufacturer | named, not_named | Named if the filings name a contract manufacturer for drug substance or drug product |
| runup_60d | number | Stock return minus XBI return over the 60 sessions before the pre-news close, computed in Python |
| short_interest | number | Short interest as a share of float on the last FINRA date before the event, computed in Python |
| label_surprise | none, narrower, boxed_warning, rems | Approvals only, judged against the indication the company sought |
