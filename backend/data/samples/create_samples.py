"""Script to generate 3 synthetic sample contracts as .docx files.

Generates:
1. sample_contract_compliant.docx (Mostly compliant / Acceptable)
2. sample_contract_needs_negotiation.docx (Several 'Needs Negotiation' clauses)
3. sample_contract_unacceptable.docx (Multiple clearly 'Unacceptable' clauses)
"""

import os
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH


def add_document_header(doc: Document, title: str, subtitle: str) -> None:
    """Add a professional title and metadata header to the document."""
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_before = Pt(0)
    title_p.paragraph_format.space_after = Pt(4)
    title_p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title_p.add_run(title)
    run.font.size = Pt(18)
    run.font.bold = True
    run.font.color.rgb = RGBColor(30, 41, 59)

    sub_p = doc.add_paragraph()
    sub_p.paragraph_format.space_after = Pt(18)
    sub_p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_run = sub_p.add_run(subtitle)
    sub_run.font.size = Pt(11)
    sub_run.font.italic = True
    sub_run.font.color.rgb = RGBColor(100, 116, 139)

    intro_p = doc.add_paragraph()
    intro_p.paragraph_format.space_after = Pt(14)
    intro_p.add_run(
        "This Master Services Agreement (\"Agreement\") is entered into by and between "
        "Company Technologies, Inc. (\"Company\") and the client party identified in the "
        "applicable Order Form (\"Customer\"). The parties agree to the following terms:"
    )


def add_section(doc: Document, section_num: str, section_title: str) -> None:
    """Add a section heading (Heading 1)."""
    h = doc.add_heading(f"{section_num}. {section_title}", level=1)
    h.paragraph_format.space_before = Pt(12)
    h.paragraph_format.space_after = Pt(6)


def add_clause(doc: Document, clause_num: str, clause_title: str, clause_text: str) -> None:
    """Add a sub-clause heading and body text."""
    h2 = doc.add_heading(f"{clause_num} {clause_title}", level=2)
    h2.paragraph_format.space_before = Pt(8)
    h2.paragraph_format.space_after = Pt(3)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(8)
    p.paragraph_format.line_spacing = 1.15
    p.add_run(clause_text)


def create_compliant_contract(output_path: str) -> None:
    """Create sample_contract_compliant.docx (standard, acceptable positions)."""
    doc = Document()
    add_document_header(
        doc,
        "MASTER SERVICES AGREEMENT",
        "Synthetic Sample Contract 1: Standard & Mostly Compliant",
    )

    add_section(doc, "1", "Limitation of Liability")
    add_clause(
        doc,
        "1.1",
        "Aggregate Liability Cap.",
        "Except for breaches of Section 4 (Confidentiality) or indemnification obligations under Section 2, "
        "neither party's aggregate cumulative liability arising out of or related to this Agreement shall "
        "exceed the total amount of fees paid or payable by Customer to Company in the twelve (12) month "
        "period immediately preceding the event giving rise to liability.",
    )
    add_clause(
        doc,
        "1.2",
        "Waiver of Consequential Damages.",
        "In no event shall either party be liable to the other party for any indirect, incidental, "
        "consequential, special, punitive, or exemplary damages, including but not limited to loss of profits, "
        "data, revenue, or business interruption, regardless of whether advised of the possibility of such "
        "damages and regardless of the theory of liability.",
    )

    add_section(doc, "2", "Indemnification")
    add_clause(
        doc,
        "2.1",
        "Intellectual Property Indemnification.",
        "Company shall defend, indemnify, and hold harmless Customer, its officers, directors, and employees "
        "from and against any third-party claim, suit, or proceeding alleging that the Services or Deliverables "
        "infringe or misappropriate any valid United States patent, copyright, or trade secret. Customer shall "
        "defend, indemnify, and hold Company harmless against any third-party claim arising from Customer Data "
        "or Customer's unauthorized modification of the Services. The indemnified party must provide prompt "
        "written notice and give the indemnifying party sole control of the defense and settlement.",
    )
    add_clause(
        doc,
        "2.2",
        "Mutual General Indemnity.",
        "Each party ('Indemnifying Party') shall defend and indemnify the other party from and against third-party "
        "claims, liabilities, and expenses (including reasonable attorney fees) arising directly from the "
        "Indemnifying Party's gross negligence, intentional misconduct, or bodily injury or tangible property "
        "damage caused by its personnel.",
    )

    add_section(doc, "3", "Term and Termination")
    add_clause(
        doc,
        "3.1",
        "Termination for Convenience.",
        "Either party may terminate this Agreement or any Statement of Work without cause and for its "
        "convenience at any time by providing at least thirty (30) days' advance written notice to the other "
        "party. Upon such termination, Customer shall promptly pay Company for all work performed and authorized "
        "expenses incurred up to the effective date of termination.",
    )
    add_clause(
        doc,
        "3.2",
        "Termination for Material Breach and Insolvency.",
        "Either party may terminate this Agreement immediately upon written notice if the other party: "
        "(a) materially breaches any provision of this Agreement and fails to cure such breach within thirty (30) "
        "days after receipt of written notice specifying the breach; or (b) becomes insolvent, makes an assignment "
        "for the benefit of creditors, or files for bankruptcy.",
    )

    add_section(doc, "4", "Confidentiality")
    add_clause(
        doc,
        "4.1",
        "Mutual Confidentiality and Standard Exclusions.",
        "Each party agrees to hold the other party's Confidential Information in confidence using at least the "
        "same degree of care it uses for its own confidential information of like nature, but not less than "
        "reasonable care. Confidential Information does not include information that: (a) is or becomes publicly "
        "known through no breach; (b) was already known to the recipient prior to disclosure; (c) is independently "
        "developed without reference to the disclosing party's information; or (d) is rightfully received from a "
        "third party without duty of confidentiality. These obligations shall survive termination of this "
        "Agreement for three (3) years, provided trade secrets shall be protected for so long as they remain trade "
        "secrets under applicable law.",
    )

    add_section(doc, "5", "Governing Law and Jurisdiction")
    add_clause(
        doc,
        "5.1",
        "Governing Law and Forum.",
        "This Agreement and all disputes arising out of or related to it shall be governed by and construed in "
        "accordance with the laws of the State of Delaware, without giving effect to any choice of law or conflict "
        "of law provisions. The parties consent to the exclusive personal jurisdiction and venue of the state and "
        "federal courts located in Wilmington, Delaware.",
    )

    add_section(doc, "6", "Intellectual Property Ownership")
    add_clause(
        doc,
        "6.1",
        "Pre-Existing IP and Deliverables.",
        "Company retains sole and exclusive ownership of all right, title, and interest in and to its pre-existing "
        "technology, proprietary tools, software, methodologies, models, and background intellectual property "
        "('Background IP'). Conditioned upon receipt of full payment, Customer shall own all custom, bespoke "
        "deliverables created specifically for Customer under an applicable Statement of Work, excluding Background "
        "IP. To the extent Background IP is embedded in any deliverable, Company grants Customer a perpetual, "
        "non-exclusive, royalty-free license to use such Background IP solely in conjunction with the deliverable.",
    )

    add_section(doc, "7", "Fees and Payment Terms")
    add_clause(
        doc,
        "7.1",
        "Payment Terms and Invoicing.",
        "Customer shall pay all undisputed invoiced fees within thirty (30) days from the date of invoice. Overdue "
        "undisputed balances shall accrue interest at the rate of 1.5% per month or the maximum rate permitted by "
        "law, whichever is less. If Customer disputes any invoice in good faith, Customer shall notify Company in "
        "writing within fifteen (15) days of receipt of such invoice, specifying the grounds for the dispute.",
    )

    add_section(doc, "8", "Term and Auto-Renewal")
    add_clause(
        doc,
        "8.1",
        "Term and Automatic Renewal.",
        "Following the Initial Term, this Agreement shall automatically renew for successive terms of one (1) "
        "year (each a 'Renewal Term') unless either party provides written notice of non-renewal to the other party "
        "at least thirty (30) days prior to the expiration of the then-current term.",
    )

    add_section(doc, "9", "Data Protection and Security")
    add_clause(
        doc,
        "9.1",
        "Data Privacy Compliance and Incident Notification.",
        "Each party shall comply with its obligations under applicable data privacy and security legislation, "
        "including GDPR and CCPA. Company shall maintain commercially reasonable administrative, technical, and "
        "physical safeguards designed to protect Customer Personal Data against accidental or unlawful destruction, "
        "loss, alteration, or unauthorized disclosure. In the event of a confirmed security incident impacting "
        "Customer Personal Data, Company shall notify Customer without undue delay and in any event within "
        "seventy-two (72) hours after becoming aware of the incident.",
    )

    add_section(doc, "10", "Assignment")
    add_clause(
        doc,
        "10.1",
        "Assignment and Corporate Reorganization.",
        "Neither party may assign or transfer this Agreement, in whole or in part, without the prior written "
        "consent of the other party (such consent not to be unreasonably withheld or delayed); provided, however, "
        "that either party may assign this Agreement without consent to an affiliate or to a successor in interest "
        "in connection with a merger, acquisition, corporate reorganization, or sale of all or substantially all of "
        "its assets.",
    )

    doc.save(output_path)
    print(f"Created: {output_path}")


def create_needs_negotiation_contract(output_path: str) -> None:
    """Create sample_contract_needs_negotiation.docx (contains fallback positions)."""
    doc = Document()
    add_document_header(
        doc,
        "MASTER SERVICES AGREEMENT",
        "Synthetic Sample Contract 2: Contains Multiple 'Needs Negotiation' Fallback Clauses",
    )

    add_section(doc, "1", "Limitation of Liability")
    add_clause(
        doc,
        "1.1",
        "Aggregate Liability Cap.",
        "Neither party's total aggregate liability arising out of or related to this Agreement shall exceed two "
        "times (2x) the total fees paid or payable by Customer to Company in the twelve (12) month period "
        "immediately preceding the event giving rise to liability, or two million dollars ($2,000,000), whichever "
        "is greater.",
    )
    add_clause(
        doc,
        "1.2",
        "Consequential Damages and Super-Cap.",
        "Except for liability arising from gross negligence, willful misconduct, or unauthorized breach of data "
        "protection obligations (which shall be subject to a separate aggregate cap of three times (3x) annual fees), "
        "neither party shall be liable to the other for indirect, incidental, or consequential damages.",
    )

    add_section(doc, "2", "Indemnification")
    add_clause(
        doc,
        "2.1",
        "Intellectual Property Indemnity.",
        "Company shall defend, indemnify, and hold harmless Customer from any third-party claims alleging that "
        "the Deliverables infringe any United States copyright or trade secret. Customer shall indemnify Company "
        "solely with respect to third-party trademark infringement claims arising from Customer trademarks.",
    )
    add_clause(
        doc,
        "2.2",
        "Mutual General Indemnity.",
        "Each party agrees to defend and indemnify the other party against third-party claims arising from the "
        "indemnifying party's gross negligence, willful misconduct, or bodily injury caused by its employees.",
    )

    add_section(doc, "3", "Term and Termination")
    add_clause(
        doc,
        "3.1",
        "Termination for Convenience.",
        "Either party may terminate this Agreement without cause by providing at least ninety (90) days' advance "
        "written notice to the other party. In the event of convenience termination by Customer, Customer shall pay "
        "for services performed plus reasonable non-cancellable third-party expenses committed by Company.",
    )
    add_clause(
        doc,
        "3.2",
        "Termination for Cause.",
        "Either party may terminate this Agreement upon written notice if the other party materially breaches this "
        "Agreement and fails to cure such breach within thirty (30) days of receipt of written notice, or within "
        "fifteen (15) days in the case of failure to pay undisputed invoices.",
    )

    add_section(doc, "4", "Confidentiality")
    add_clause(
        doc,
        "4.1",
        "Confidentiality Duration and Exclusions.",
        "Each party agrees to protect the Confidential Information of the other using reasonable care. The "
        "obligations of confidentiality and non-disclosure herein shall survive termination of this Agreement for "
        "a period of five (5) years. Standard exclusions for public information, independent development, and legally "
        "compelled disclosure shall apply.",
    )

    add_section(doc, "5", "Governing Law and Jurisdiction")
    add_clause(
        doc,
        "5.1",
        "Governing Law and Venue.",
        "This Agreement shall be governed by and construed in accordance with the laws of the State of New York, "
        "without regard to its conflict of laws principles. The parties submit to the exclusive jurisdiction of the "
        "courts located in the Borough of Manhattan, City of New York.",
    )

    add_section(doc, "6", "Intellectual Property Ownership")
    add_clause(
        doc,
        "6.1",
        "Deliverables and Background Technology.",
        "Customer shall own all custom deliverables created under an applicable Statement of Work upon receipt "
        "of payment. Company retains ownership of all pre-existing tools, algorithms, and libraries, and hereby "
        "grants Customer a non-exclusive, perpetual, worldwide license to use such tools solely as integrated into "
        "the deliverables.",
    )

    add_section(doc, "7", "Fees and Payment Terms")
    add_clause(
        doc,
        "7.1",
        "Invoicing and Payment Window.",
        "Customer shall pay all undisputed invoiced fees within forty-five (45) days from receipt of invoice. "
        "Undisputed overdue amounts shall accrue interest at 1.0% per month. If Customer disputes any invoice, "
        "Customer shall provide written notice of dispute within twenty (20) days of receipt.",
    )

    add_section(doc, "8", "Term and Auto-Renewal")
    add_clause(
        doc,
        "8.1",
        "Renewal and Extended Notice.",
        "This Agreement shall automatically renew for successive one (1) year terms unless either party gives "
        "written notice of its intent not to renew at least sixty (60) days prior to the expiration of the current "
        "term.",
    )

    add_section(doc, "9", "Data Protection and Security")
    add_clause(
        doc,
        "9.1",
        "Data Protection and Annual Audit Reporting.",
        "Company shall maintain appropriate technical and organizational safeguards in accordance with industry "
        "standards. In the event of a confirmed breach of Customer Personal Data, Company shall notify Customer "
        "within forty-eight (48) hours. Company agrees to provide Customer with its annual SOC 2 Type II audit report "
        "upon written request.",
    )

    add_section(doc, "10", "Assignment")
    add_clause(
        doc,
        "10.1",
        "Assignment and Competitor Restriction.",
        "Neither party may assign this Agreement without the prior written consent of the other party; provided "
        "that either party may assign this Agreement upon thirty (30) days' advance written notice to an affiliate "
        "or successor in interest pursuant to a merger or acquisition, provided that such assignee is not a direct "
        "commercial competitor of the non-assigning party and agrees in writing to assume all obligations.",
    )

    doc.save(output_path)
    print(f"Created: {output_path}")


def create_unacceptable_contract(output_path: str) -> None:
    """Create sample_contract_unacceptable.docx (contains multiple aggressive/unacceptable triggers)."""
    doc = Document()
    add_document_header(
        doc,
        "MASTER SERVICES AGREEMENT",
        "Synthetic Sample Contract 3: Contains Multiple Clearly 'Unacceptable' Aggressive Clauses",
    )

    add_section(doc, "1", "Limitation of Liability")
    add_clause(
        doc,
        "1.1",
        "Uncapped Liability of Company and Unilateral Cap.",
        "Company shall have unlimited liability for any and all claims, breaches, losses, damages, or liabilities "
        "under or relating to this Agreement, whether in contract, tort, or otherwise. Customer's aggregate cumulative "
        "liability under this Agreement shall under no circumstances exceed one hundred dollars ($100).",
    )
    add_clause(
        doc,
        "1.2",
        "One-Sided Consequential Damages and Lost Profits.",
        "Customer may recover all indirect, special, punitive, consequential, exemplary, and lost-profit damages "
        "from Company for any breach of this Agreement. Company hereby unconditionally and irrevocably waives all "
        "rights to claim indirect, incidental, or consequential damages of any kind from Customer.",
    )

    add_section(doc, "2", "Indemnification")
    add_clause(
        doc,
        "2.1",
        "Worldwide Patent Indemnification and Unilateral Settlement.",
        "Company shall defend, indemnify, and hold harmless Customer against any third-party claim alleging patent, "
        "copyright, or trademark infringement anywhere in the world. Customer shall have the sole right to direct the "
        "defense and enter into any settlement or compromise at Company's sole expense without requiring Company's "
        "consent. Customer provides no reciprocal indemnity of any kind.",
    )
    add_clause(
        doc,
        "2.2",
        "Broad Uncapped Indemnity for Simple Breach and Customer Negligence.",
        "Company agrees to indemnify, defend, and hold harmless Customer from and against any and all claims, damages, "
        "losses, and legal expenses arising out of any breach of this Agreement by Company, or any acts or omissions "
        "of Company, whether negligent or not. Company further agrees to indemnify Customer against claims arising from "
        "Customer's own concurrent or sole negligence.",
    )

    add_section(doc, "3", "Term and Termination")
    add_clause(
        doc,
        "3.1",
        "Immediate Customer Convenience Termination and 5-Year Lock-In.",
        "Customer may terminate this Agreement immediately for convenience at any time without advance notice and "
        "without further payment or compensation. Company is bound to a mandatory five (5) year term and shall have "
        "no right to terminate this Agreement for convenience under any circumstances.",
    )
    add_clause(
        doc,
        "3.2",
        "Immediate Termination Without Cure and Non-Payment Clause.",
        "Customer may terminate this Agreement immediately for cause with zero (0) days notice or opportunity to cure. "
        "In no event shall Company have any right to terminate this Agreement or suspend services for Customer's "
        "failure to pay invoices.",
    )

    add_section(doc, "4", "Confidentiality")
    add_clause(
        doc,
        "4.1",
        "Perpetual One-Sided Confidentiality Without Exclusions.",
        "Company shall hold all Customer information in strict confidentiality in perpetuity. Company shall be strictly "
        "liable for any accidental disclosure. No exceptions for publicly available information, prior possession, "
        "independent development, or court orders shall apply to Company's obligations.",
    )

    add_section(doc, "5", "Governing Law and Jurisdiction")
    add_clause(
        doc,
        "5.1",
        "Foreign Governing Law and Exclusive Foreign Venue.",
        "This Agreement shall be governed by, construed, and enforced in accordance with the substantive laws of the "
        "Cayman Islands, and Company irrevocably submits to the exclusive personal jurisdiction and venue of the courts "
        "of Grand Cayman for any dispute arising out of this Agreement.",
    )

    add_section(doc, "6", "Intellectual Property Ownership")
    add_clause(
        doc,
        "6.1",
        "Total Assignment of Pre-Existing IP, Code, and Tools.",
        "All software, code, algorithms, background materials, machine learning models, tools, and methodologies "
        "utilized, developed, or provided by Company in connection with this Agreement shall be deemed 'work made for "
        "hire' and are hereby irrevocably assigned to Customer as Customer's sole and exclusive intellectual property. "
        "Company is permanently prohibited from creating similar software or providing similar services to any other client.",
    )

    add_section(doc, "7", "Fees and Payment Terms")
    add_clause(
        doc,
        "7.1",
        "Net-90 Days, Pay-When-Paid, and Unilateral Set-Off.",
        "Customer shall pay invoiced fees within Net-ninety (90) days from receipt of invoice; provided that Customer's "
        "obligation to pay is strictly contingent upon Customer receiving payment from its own third-party client "
        "('pay-when-paid'). Customer reserves the unilateral right to set off any alleged claims, deductions, or "
        "counter-claims against undisputed fees. No late fees, interest, or service suspension shall be permitted.",
    )

    add_section(doc, "8", "Term and Auto-Renewal")
    add_clause(
        doc,
        "8.1",
        "Perpetual Auto-Renewal and 25% Annual Escalation.",
        "This Agreement shall automatically renew perpetually for successive three (3) year periods, with no right "
        "of termination or cancellation by Company. Annual service fees payable to Company shall remain fixed, while "
        "licensing costs payable by Customer shall automatically escalate by twenty-five percent (25%) each year.",
    )

    add_section(doc, "9", "Data Protection and Security")
    add_clause(
        doc,
        "9.1",
        "2-Hour Breach SLA and Unannounced Physical Facility Audits.",
        "Company shall notify Customer in writing within two (2) hours of any suspected security vulnerability or "
        "incident. Customer shall have the unrestricted right at any time, without advance notice, to enter Company's "
        "offices and physical server rooms to conduct audits at Company's sole expense. Company shall bear unlimited "
        "strict liability for any data security incident.",
    )

    add_section(doc, "10", "Assignment")
    add_clause(
        doc,
        "10.1",
        "Strict Assignment Prohibition and Change of Control Poison Pill.",
        "Company shall not assign, transfer, or delegate this Agreement or any rights hereunder, in whole or in part, "
        "including by operation of law, merger, consolidation, acquisition, or sale of substantially all assets. Any "
        "attempted assignment or corporate reorganization shall be null and void and constitutes an immediate non-curable "
        "material breach entitling Customer to liquidated damages of $500,000.",
    )

    doc.save(output_path)
    print(f"Created: {output_path}")


if __name__ == "__main__":
    samples_dir = os.path.dirname(__file__)
    create_compliant_contract(os.path.join(samples_dir, "sample_contract_compliant.docx"))
    create_needs_negotiation_contract(os.path.join(samples_dir, "sample_contract_needs_negotiation.docx"))
    create_unacceptable_contract(os.path.join(samples_dir, "sample_contract_unacceptable.docx"))
