# Expected Findings for Synthetic Sample Contracts

> **LEGAL NOTICE: ADVISORY ONLY**  
> This document specifies the ground-truth benchmark and expected risk classifications for the synthetic sample contracts. It is intended for automated evaluation and regression testing of the agentic review system.

---

## 1. Sample Contract 1: Standard & Mostly Compliant (`sample_contract_compliant.docx`)

Overall Profile: **Low Risk / Mostly Compliant**

| Clause # | Section Title | Clause Type | Expected Risk Level | Cited Rule ID(s) | Benchmark Rationale |
|---|---|---|---|---|---|
| **1.1** | Aggregate Liability Cap | `limitation_of_liability` | **Acceptable** | `LOL-01` | Mutual liability capped at 12 months fees paid or payable. |
| **1.2** | Waiver of Consequential Damages | `limitation_of_liability` | **Acceptable** | `LOL-02` | Standard mutual waiver of indirect, consequential, and lost profit damages. |
| **2.1** | Intellectual Property Indemnification | `indemnification` | **Acceptable** | `IND-01` | Mutual IP indemnity with standard defense and settlement control procedures. |
| **2.2** | Mutual General Indemnity | `indemnification` | **Acceptable** | `IND-02` | Mutual indemnity strictly limited to gross negligence, intentional misconduct, and bodily injury. |
| **3.1** | Termination for Convenience | `termination` | **Acceptable** | `TRM-01` | Mutual 30-day notice for convenience termination with payment for accrued work. |
| **3.2** | Termination for Cause and Insolvency | `termination` | **Acceptable** | `TRM-02` | Mutual 30-day notice and cure period for material breach; immediate insolvency termination. |
| **4.1** | Mutual Confidentiality and Standard Exclusions | `confidentiality` | **Acceptable** | `CNF-01` | Mutual 3-year term (trade secrets indefinite) with standard 4 legal exclusions. |
| **5.1** | Governing Law and Forum | `governing_law` | **Acceptable** | `GOV-01` | Delaware governing law with exclusive venue in Wilmington, DE. |
| **6.1** | Pre-Existing IP and Deliverables | `ip_ownership` | **Acceptable** | `IP-01` | Company retains Background IP; Customer owns bespoke deliverables upon payment with license. |
| **7.1** | Payment Terms and Invoicing | `payment_terms` | **Acceptable** | `PAY-01` | Net-30 payment, 1.5% late fee interest, 15-day good faith dispute window. |
| **8.1** | Term and Automatic Renewal | `auto_renewal` | **Acceptable** | `RNW-01` | 1-year auto-renewal with standard 30-day non-renewal notice. |
| **9.1** | Data Privacy Compliance and Incident Notification | `data_protection` | **Acceptable** | `DAT-01` | GDPR/CCPA compliance, industry standard safeguards, 72-hour breach notification SLA. |
| **10.1** | Assignment and Corporate Reorganization | `assignment` | **Acceptable** | `ASG-01` | Mutual consent required, with standard carve-out for affiliates and M&A / asset sale. |

---

## 2. Sample Contract 2: Needs Negotiation (`sample_contract_needs_negotiation.docx`)

Overall Profile: **Moderate Risk / Contains Fallback Positions Requiring Redlines or Confirmation**

| Clause # | Section Title | Clause Type | Expected Risk Level | Cited Rule ID(s) | Benchmark Rationale |
|---|---|---|---|---|---|
| **1.1** | Aggregate Liability Cap | `limitation_of_liability` | **Needs Negotiation** | `LOL-01` | Cap is 2x annual fees or $2,000,000 (acceptable fallback, but exceeds preferred 1x annual fees). |
| **1.2** | Consequential Damages and Super-Cap | `limitation_of_liability` | **Needs Negotiation** | `LOL-02` | Carves out data breaches for consequential damages under a 3x super-cap (negotiable fallback). |
| **2.1** | Intellectual Property Indemnity | `indemnification` | **Unacceptable** | `IND-01` | *Label revised from Needs Negotiation to Unacceptable*: Section 2.1 hits verbatim IND-01 unacceptable triggers: failure to provide reciprocal indemnity for Customer-furnished materials, and obligation to indemnify without receiving prompt written notice or sole control of defense. |
| **2.2** | Mutual General Indemnity | `indemnification` | **Acceptable** | `IND-02` | Mutual indemnity for gross negligence and bodily injury adheres to acceptable baseline. |
| **3.1** | Termination for Convenience | `termination` | **Needs Negotiation** | `TRM-01` | 90-day advance notice for convenience termination exceeds preferred 30-day standard. |
| **3.2** | Termination for Cause | `termination` | **Acceptable** | `TRM-02` | 30-day cure period for general breach and 15 days for payment default is acceptable fallback. |
| **4.1** | Confidentiality Duration and Exclusions | `confidentiality` | **Needs Negotiation** | `CNF-01` | 5-year duration post-termination exceeds standard 3-year term. |
| **5.1** | Governing Law and Venue | `governing_law` | **Acceptable** | `GOV-01` | New York governing law and Manhattan venue is an acceptable commercial US jurisdiction. |
| **6.1** | Deliverables and Background Technology | `ip_ownership` | **Acceptable** | `IP-01` | Company retains background tools/libraries; Customer receives embedded license. |
| **7.1** | Invoicing and Payment Window | `payment_terms` | **Needs Negotiation** | `PAY-01` | Net-45 payment terms and 20-day dispute window represents acceptable fallback requiring note. |
| **8.1** | Renewal and Extended Notice | `auto_renewal` | **Needs Negotiation** | `RNW-01` | 60-day non-renewal notice window exceeds standard 30-day position. |
| **9.1** | Data Protection and Annual Audit Reporting | `data_protection` | **Needs Negotiation** | `DAT-01` | *Label revised from Acceptable to Needs Negotiation*: Benchmark rationale states 48-hour notice and annual SOC 2 report sharing conforms to acceptable fallback, which under the rubric maps to Needs Negotiation. |
| **10.1** | Assignment and Competitor Restriction | `assignment` | **Needs Negotiation** | `ASG-01` | 30-day notice and competitor restriction on M&A assignment requires legal check. |

---

## 3. Sample Contract 3: Unacceptable Aggressive (`sample_contract_unacceptable.docx`)

Overall Profile: **High Risk / Multiple Fatal Deal-Breakers**

| Clause # | Section Title | Clause Type | Expected Risk Level | Cited Rule ID(s) | Benchmark Rationale |
|---|---|---|---|---|---|
| **1.1** | Uncapped Liability and Unilateral Cap | `limitation_of_liability` | **Unacceptable** | `LOL-01` | Unlimited liability for Company; unilateral $100 nominal cap for Customer. |
| **1.2** | One-Sided Consequential Damages & Lost Profits | `limitation_of_liability` | **Unacceptable** | `LOL-02` | Customer recovers lost profits/indirect damages; Company waives all indirect claims. |
| **2.1** | Worldwide Patent Indemnification | `indemnification` | **Unacceptable** | `IND-01` | Non-US worldwide patent indemnity, zero defense/settlement control, no reciprocal indemnity. |
| **2.2** | Broad Uncapped Indemnity & Customer Negligence | `indemnification` | **Unacceptable** | `IND-02` | Indemnity for simple breach and requiring Company to indemnify Customer for Customer's own negligence. |
| **3.1** | Immediate Convenience Termination & 5-Year Lock-In | `termination` | **Unacceptable** | `TRM-01` | One-sided immediate convenience termination by Customer while Company is locked in for 5 years. |
| **3.2** | Immediate Termination & Non-Payment Bar | `termination` | **Unacceptable** | `TRM-02` | Zero days cure period for Customer termination; Company prohibited from terminating for non-payment. |
| **4.1** | Perpetual One-Sided Confidentiality | `confidentiality` | **Unacceptable** | `CNF-01` | One-sided perpetual obligation on Company with zero standard legal exclusions. |
| **5.1** | Foreign Governing Law & Exclusive Venue | `governing_law` | **Unacceptable** | `GOV-01` | Cayman Islands foreign jurisdiction and exclusive offshore venue. |
| **6.1** | Total Assignment of Pre-Existing IP & Tools | `ip_ownership` | **Unacceptable** | `IP-01` | Broad work-made-for-hire assigning pre-existing IP, models, and tools; non-compete covenant. |
| **7.1** | Net-90, Pay-When-Paid & Unilateral Set-Off | `payment_terms` | **Unacceptable** | `PAY-01` | Net-90 terms, conditional pay-when-paid, unilateral right of set-off, late fee prohibition. |
| **8.1** | Perpetual Auto-Renewal & 25% Escalation | `auto_renewal` | **Unacceptable** | `RNW-01` | Perpetual renewal with no Company termination right, and 25% annual price escalation. |
| **9.1** | 2-Hour Breach SLA & Unannounced Physical Audits | `data_protection` | **Unacceptable** | `DAT-01` | Impossible 2-hour notification SLA, unannounced on-site audits at Company expense. |
| **10.1** | Strict Assignment Prohibition & Poison Pill | `assignment` | **Unacceptable** | `ASG-01` | Absolute prohibition on M&A/change of control assignment with $500,000 penalty. |
