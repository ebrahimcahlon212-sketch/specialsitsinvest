# Write cards for upcoming FDA decisions

Each entry below is a listed company whose filing mentions an upcoming FDA decision date. It gives the sentence the date came from, excerpts from the filing around it, and figures Python worked out from the SEC's data. For each company, write one card as a line of JSON.

| Key | What to put in it |
|---|---|
| id | The ID as given, for example BIO-ABCD |
| drug | The product's name or code |
| indication | The disease or use being decided |
| application | NDA, BLA, sNDA, sBLA or other |
| modality | Small molecule, biologic, cell therapy, gene therapy, vaccine, device or other |
| review | Priority, standard or unknown |
| adcom | Whether an FDA advisory committee is scheduled, with its date, or "not planned" or "unknown" |
| manufacturing | Who makes it and where, whether in-house or a contract manufacturer, and any inspection, supply or process-change issue the excerpts mention |
| value_share | High, medium or low, meaning how much of the company's value rides on this decision, with a short reason |
| summary | One plain sentence on what is being decided and when |
| why_mispriced | One sentence on why a careful reader might see something the market misses, or "No obvious reason" |
| red_flags | Financing needs, earlier rejections, safety signals, manufacturing problems, or anything an ISA may not be able to hold |
| score | A whole number from 1 to 5, where 5 means a decision within months at a smaller company where the evidence or the manufacturing gives a careful reader an edge |

Use only what the excerpts and figures support, and write "unknown" rather than guessing. Do not use em dashes. Put the JSON lines, one per company and nothing else, between the output markers.
